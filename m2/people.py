"""Owner-scoped people, unverified draft details and immutable chart selection."""

from datetime import date, datetime, time
from math import isfinite
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg

from m2.charts import Charts
from m2.natal import DEFAULT_ORBS


DEFAULT_SETTINGS = {'zodiac': 'tropical', 'house_system': 'none',
                    'node_type': 'true', 'aspects': ['conjunction']}
DEFAULT_NATAL_SETTINGS = {'chart_kind': 'natal', 'zodiac': 'tropical',
                          'house_system': 'placidus', 'node_type': 'true',
                          'aspects': list(DEFAULT_ORBS), 'orbs': DEFAULT_ORBS}
DRAFT_FIELDS = {'birth_date', 'birth_time', 'birthplace', 'time_unknown'}


def new_id(prefix):
    return prefix + uuid4().hex[:20]


def checked_draft(details):
    if not isinstance(details, dict) or set(details) != DRAFT_FIELDS:
        raise ValueError('Invalid draft fields')
    day, hour, place, unknown = (details[item] for item in
                                 ('birth_date', 'birth_time', 'birthplace', 'time_unknown'))
    if not isinstance(unknown, bool) or any(not isinstance(item, str) for item in (day, hour, place)):
        raise ValueError('Invalid draft details')
    if day:
        date.fromisoformat(day)
    if hour:
        time.fromisoformat(hour)
    if (unknown and hour) or len(place.encode('utf-8')) > 160:
        raise ValueError('Conflicting or oversized draft details')
    return details


class People:
    def __init__(self, store):
        self.store = store
        self.charts = Charts(store)

    def add(self, session, name, draft=None):
        person_id = new_id('p-')
        with self.store.db.transaction():
            self.charts.add_person(session, person_id, name.strip() if isinstance(name, str) else name)
            if draft is not None:
                self.add_draft(session, person_id, draft)
        return self.get(session, person_id)

    def _person(self, session, person_id, lock=False):
        owner = self.store.owner(session)
        query = 'SELECT id,name,created_at FROM people WHERE owner_id=%s AND id=%s'
        if lock:
            query += ' FOR UPDATE'
        row = self.store.db.execute(query, (owner, self.store._id(person_id))).fetchone()
        if row is None:
            raise KeyError('Person not found')
        return row

    def list(self, session, limit=50):
        owner = self.store.owner(session)
        if not 1 <= limit <= 50:
            raise ValueError('Invalid people page')
        return self.store.db.execute('''
            SELECT p.id,p.name,p.created_at,a.chart_id AS active_chart_id
            FROM people p LEFT JOIN person_active_charts a
              ON a.owner_id=p.owner_id AND a.person_id=p.id
            WHERE p.owner_id=%s ORDER BY p.created_at DESC,p.id DESC LIMIT %s
        ''', (owner, limit)).fetchall()

    def add_draft(self, session, person_id, details):
        owner = self.store.owner(session)
        checked_draft(details)
        with self.store.db.transaction():
            self._person(session, person_id, lock=True)
            revision = self.store.db.execute('''
                SELECT COALESCE(MAX(revision),0)+1 AS next FROM person_drafts
                WHERE owner_id=%s AND person_id=%s
            ''', (owner, person_id)).fetchone()['next']
            self.store.db.execute('''
                INSERT INTO person_drafts(owner_id,person_id,revision,details)
                VALUES (%s,%s,%s,%s)
            ''', (owner, person_id, revision, psycopg.types.json.Jsonb(details)))
            # Earlier answers derived from another draft version are historical;
            # invalidate summary/search epochs before the updated profile serves.
            for row in self.store.db.execute('''
                SELECT DISTINCT conversation_id FROM turn_people
                WHERE owner_id=%s AND person_id=%s AND draft_revision IS NOT NULL
            ''', (owner, person_id)).fetchall():
                self.store._changed(owner, row['conversation_id'])
        return revision

    def get(self, session, person_id):
        owner = self.store.owner(session)
        person = self._person(session, person_id)
        person['active_chart_id'] = self.active_chart_id(session, person_id)
        person['drafts'] = self.store.db.execute('''
            SELECT revision,details,created_at FROM person_drafts
            WHERE owner_id=%s AND person_id=%s ORDER BY revision DESC LIMIT 20
        ''', (owner, person_id)).fetchall()
        person['birth_records'] = self.store.db.execute('''
            SELECT id,wall_time,zone_name,fold,instant_utc,earliest_utc,latest_utc,
                   latitude,longitude,provenance,created_at
            FROM birth_records WHERE owner_id=%s AND person_id=%s
            ORDER BY created_at DESC,id DESC LIMIT 20
        ''', (owner, person_id)).fetchall()
        person['charts'] = [self.charts.get_chart(session, row['id']) for row in self.store.db.execute('''
            SELECT id FROM charts WHERE owner_id=%s AND person_id=%s
            ORDER BY created_at DESC,id DESC LIMIT 20
        ''', (owner, person_id)).fetchall()]
        person['attachments'] = self.store.db.execute('''
            SELECT id, filename, media_type, byte_count, created_at FROM person_attachments
            WHERE owner_id=%s AND person_id=%s ORDER BY created_at DESC,id DESC LIMIT 20
        ''', (owner, person_id)).fetchall()
        return person

    def active_chart_id(self, session, person_id):
        owner = self.store.owner(session)
        self._person(session, person_id)
        row = self.store.db.execute('''
            SELECT chart_id FROM person_active_charts WHERE owner_id=%s AND person_id=%s
        ''', (owner, person_id)).fetchone()
        return row['chart_id'] if row else None

    def resolve_active(self, session, selected):
        """Resolve browser person IDs to current generated versions on the Store worker."""
        if not isinstance(selected, list) or len(selected) > 8:
            raise ValueError('Select up to eight people')
        ids = []
        for item in selected:
            if not isinstance(item, dict) or set(item) != {'person_id'}:
                raise ValueError('Choose people, not chart versions')
            ids.append(self.store._id(item['person_id']))
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate selected person')
        return [{'person_id': person_id, 'chart_id': self.active_chart_id(session, person_id)}
                for person_id in ids]

    def add_birth(self, session, person_id, supplied, provenance='user_supplied_browser_inputs',
                  max_interval_hours=24):
        self._person(session, person_id)
        if not isinstance(supplied, dict) or supplied.get('mode') not in ('exact', 'interval'):
            raise ValueError('Specify exact time or a supplied UTC interval')
        allowed = {'mode', 'zone', 'wall_time', 'fold', 'earliest_utc', 'latest_utc',
                   'latitude', 'longitude'}
        if set(supplied) - allowed:
            raise ValueError('Unsupported birth fields')
        fold = supplied.get('fold')
        if fold is not None and (type(fold) is not int or fold not in (0, 1)):
            raise ValueError('Fold must be 0 or 1')
        for coordinate in ('latitude', 'longitude'):
            value = supplied.get(coordinate)
            if value is not None and (type(value) not in (int, float) or not isfinite(value)):
                raise ValueError('Coordinates must be finite numbers')
        zone = supplied.get('zone')
        if not isinstance(zone, str) or not zone or len(zone) > 80:
            raise ValueError('Explicit IANA zone required')
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Unknown IANA zone') from exc
        wall = None
        earliest = latest = None
        if supplied['mode'] == 'exact':
            if supplied.get('earliest_utc') or supplied.get('latest_utc'):
                raise ValueError('Exact birth cannot have an interval')
            if not isinstance(supplied.get('wall_time'), str):
                raise ValueError('Explicit local wall time required')
            wall = datetime.fromisoformat(supplied['wall_time'])
            if wall.tzinfo is not None:
                raise ValueError('Supply local wall time without offset')
        else:
            if supplied.get('wall_time') or supplied.get('fold') is not None:
                raise ValueError('Interval cannot have an exact wall time or fold')
            if not all(isinstance(supplied.get(key), str) for key in
                       ('earliest_utc', 'latest_utc')):
                raise ValueError('Explicit UTC interval required')
            earliest = datetime.fromisoformat(supplied['earliest_utc'])
            latest = datetime.fromisoformat(supplied['latest_utc'])
        birth_id = new_id('b-')
        self.charts.add_birth(session, person_id, birth_id, zone,
                              provenance, wall_time=wall,
                              fold=fold, earliest_utc=earliest, latest_utc=latest,
                              latitude=supplied.get('latitude'), longitude=supplied.get('longitude'),
                              max_interval_hours=max_interval_hours)
        return birth_id

    def profiles(self, session):
        owner = self.store.owner(session)
        return self.store.db.execute('''
            SELECT id,revision,settings,created_at FROM calculation_profiles
            WHERE owner_id=%s ORDER BY id,revision DESC LIMIT 50
        ''', (owner,)).fetchall()

    def add_profile(self, session, profile_id, settings):
        if (not isinstance(settings, dict) or
                not isinstance(settings.get('aspects'), list) or
                any(not isinstance(aspect, str) for aspect in settings['aspects'])):
            raise ValueError('Invalid calculation profile')
        return self.charts.add_profile(session, profile_id, settings)

    def create_chart(self, session, person_id, birth_id, profile_id, revision):
        self._person(session, person_id)
        defaults = {'solar-default': DEFAULT_SETTINGS, 'natal-default': DEFAULT_NATAL_SETTINGS}
        if profile_id in defaults and revision == 1:
            owner = self.store.owner(session)
            with self.store.db.transaction():
                row = self.store.db.execute('''
                    SELECT 1 FROM calculation_profiles
                    WHERE owner_id=%s AND id=%s AND revision=1
                ''', (owner, profile_id)).fetchone()
                if not row:
                    self.charts.add_profile(session, profile_id, defaults[profile_id])
        return self.charts.create_chart(session, new_id('chart-'), person_id,
                                        birth_id, profile_id, revision)
