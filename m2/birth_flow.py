"""One durable owner-scoped birth-to-chart action; no inference from a draft or user-supplied place label."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from m2.natal import checked_natal_settings
from m2.people import DEFAULT_NATAL_SETTINGS, People
from m2.places import selected
from m2.core_calc import AmbiguousLocalTime, END_YEAR, NonexistentLocalTime, START_YEAR, local_instant


class BirthInputError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


FIELDS = {'request_id', 'birth_date', 'birth_time', 'time_unknown', 'birthplace', 'place_id',
          'provisional', 'zone_override', 'latitude_override', 'longitude_override', 'fold', 'settings'}


def _day_interval(day, zone):
    """Find real UTC bounds of a local civil day, including historical 23/25-hour days."""
    first = datetime.combine(day, time.min, timezone.utc) - timedelta(days=2)
    tz = ZoneInfo(zone)

    def lower_bound(target):
        left, right = 0, 5 * 86400
        while left < right:
            middle = (left + right) // 2
            if (first + timedelta(seconds=middle)).astimezone(tz).date() < target:
                left = middle + 1
            else:
                right = middle
        return first + timedelta(seconds=left)

    start, end = lower_bound(day), lower_bound(day + timedelta(days=1))
    if start >= end or start.astimezone(tz).date() != day:
        raise BirthInputError('unsupported_local_day')
    return start, end


def _checked_request(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise BirthInputError('invalid_birth_details')
    if (not isinstance(data['birth_date'], str) or not isinstance(data['birth_time'], str) or
            not isinstance(data['birthplace'], str) or len(data['birthplace'].encode()) > 160 or
            type(data['time_unknown']) is not bool or type(data['provisional']) is not bool):
        raise BirthInputError('invalid_birth_details')
    if (data['time_unknown'] and data['birth_time']) or (not data['time_unknown'] and not data['birth_time']):
        raise BirthInputError('invalid_birth_details')
    try:
        day = date.fromisoformat(data['birth_date'])
        hour = None if data['time_unknown'] else time.fromisoformat(data['birth_time'])
        if hour and hour.tzinfo is not None:
            raise ValueError('Local time cannot include an offset')
    except ValueError as exc:
        raise BirthInputError('invalid_birth_date_or_time') from exc
    if not START_YEAR <= day.year <= END_YEAR:
        raise BirthInputError('unsupported_birth_or_chart')
    if data['fold'] is not None and (type(data['fold']) is not int or data['fold'] not in (0, 1)):
        raise BirthInputError('invalid_fold')
    if data['time_unknown'] and data['fold'] is not None:
        raise BirthInputError('invalid_fold')
    if data['settings'] is not None:
        try:
            checked_natal_settings(data['settings'])
        except ValueError as exc:
            raise BirthInputError('unsupported_chart_settings') from exc
    return day, hour


class BirthFlow:
    def __init__(self, store):
        self.store = store
        self.people = People(store)

    def generate(self, session, person_id, data):
        day, hour = _checked_request(data)
        owner = self.store.owner(session)
        request_id = self.store._id(data['request_id'])
        self.people._person(session, person_id)
        digest = sha256(json.dumps({key: value for key, value in data.items() if key != 'request_id'},
                                   sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

        with self.store.db.transaction():
            self.people._person(session, person_id, lock=True)
            prior = self.store.db.execute('''
                SELECT * FROM birth_generation_requests
                WHERE owner_id=%s AND person_id=%s AND request_id=%s
            ''', (owner, person_id, request_id)).fetchone()
            if prior and prior['input_digest'] != digest:
                raise BirthInputError('request_conflict')
            if prior:
                return self._result(session, prior, reused=True)

            place_id = data['place_id']
            try:
                place = selected(place_id) if place_id is not None else None
            except ValueError as exc:
                raise BirthInputError('select_place_again') from exc
            if place and data['birthplace'] != self._label(place):
                raise BirthInputError('select_place_again')
            override_zone = data['zone_override']
            if override_zone is not None and (not isinstance(override_zone, str) or len(override_zone) > 80):
                raise BirthInputError('invalid_timezone')
            zone = override_zone or (place['zone'] if place else None)
            lat, lon = data['latitude_override'], data['longitude_override']
            if (lat is None) != (lon is None) or any(type(value) not in (int, float) for value in (lat, lon) if value is not None):
                raise BirthInputError('coordinates_required_together')
            if not place and (not zone or lat is None):
                raise BirthInputError('select_place_or_advanced_location')
            if lat is None and place:
                lat, lon = place['latitude'], place['longitude']
            try:
                ZoneInfo(zone)
            except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
                raise BirthInputError('invalid_timezone') from exc
            fold = data['fold']
            wall = None if hour is None else datetime.combine(day, hour)
            if wall is not None:
                try:
                    local_instant(wall, zone, fold)
                except AmbiguousLocalTime as exc:
                    raise BirthInputError('choose_dst_occurrence') from exc
                except NonexistentLocalTime as exc:
                    raise BirthInputError('nonexistent_local_time') from exc
            else:
                earliest, latest = _day_interval(day, zone)

            draft = {'birth_date': data['birth_date'], 'birth_time': data['birth_time'],
                     'birthplace': data['birthplace'], 'time_unknown': data['time_unknown']}
            revision = self.people.add_draft(session, person_id, draft)
            confidence = 'provisional' if data['provisional'] else 'user_reported_reliable'
            location_source = f'geonames_city_centre_{place_id}' if place else 'user_supplied_coordinates'
            if data['latitude_override'] is not None:
                location_source = f'user_supplied_coordinates_place_{place_id}' if place else 'user_supplied_coordinates'
            provenance = f'{confidence}:{location_source}'
            try:
                birth_id = self.people.add_birth(session, person_id, {
                    'mode': 'exact' if wall else 'interval', 'zone': zone, 'latitude': lat, 'longitude': lon,
                    **({'wall_time': wall.isoformat(timespec='minutes'), 'fold': fold} if wall else
                       {'earliest_utc': earliest.isoformat(), 'latest_utc': latest.isoformat()})
                }, provenance=provenance, max_interval_hours=26 if wall is None else 24)
                settings = data['settings'] or DEFAULT_NATAL_SETTINGS
                if data['settings'] is None:
                    profile_id, profile_revision = 'natal-default', 1
                else:
                    profile_id = f'natal-{person_id}'
                    profile_revision = self.people.add_profile(session, profile_id, settings)
                chart = self.people.create_chart(session, person_id, birth_id, profile_id, profile_revision)
            except (ValueError, OverflowError) as exc:
                # The transaction rolls the draft and birth back too; no half-saved version.
                if isinstance(exc, BirthInputError):
                    raise
                raise BirthInputError('unsupported_birth_or_chart') from exc

            self.store.db.execute('''
                INSERT INTO birth_generation_requests
                (owner_id,person_id,request_id,input_digest,provisional,place_id,draft_revision,birth_id,chart_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, request_id, digest, data['provisional'], place_id,
                  revision, birth_id, chart['id']))
            self.store.db.execute('''
                INSERT INTO person_active_charts(owner_id,person_id,chart_id)
                VALUES (%s,%s,%s)
                ON CONFLICT (owner_id,person_id) DO UPDATE SET chart_id=EXCLUDED.chart_id
            ''', (owner, person_id, chart['id']))
            return {'birth_id': birth_id, 'draft_revision': revision, 'chart': chart,
                    'active_chart_id': chart['id'], 'provisional': data['provisional'],
                    'place_id': place_id, 'reused': False}

    def editor_location(self, session, person_id, revision, label):
        """Read only the generation linked to this editor draft, never a nearby chart."""
        owner = self.store.owner(session)
        self.people._person(session, person_id)
        row = self.store.db.execute('''
            SELECT g.place_id,g.provisional,b.zone_name,b.latitude,b.longitude,b.fold,b.provenance
            FROM birth_generation_requests g
            JOIN person_drafts d ON d.owner_id=g.owner_id AND d.person_id=g.person_id
              AND d.revision=g.draft_revision
            JOIN birth_records b ON b.owner_id=g.owner_id AND b.person_id=g.person_id
              AND b.id=g.birth_id
            JOIN charts c ON c.owner_id=g.owner_id AND c.person_id=g.person_id
              AND c.id=g.chart_id AND c.birth_id=g.birth_id
            WHERE g.owner_id=%s AND g.person_id=%s AND g.draft_revision=%s
              AND d.details->>'birthplace'=%s
        ''', (owner, person_id, revision, label)).fetchone()
        if row is None:
            return None
        context = {'kind': 'review', 'latitude': row['latitude'], 'longitude': row['longitude'],
                   'zone': row['zone_name'], 'fold': row['fold'], 'provisional': row['provisional']}
        if row['latitude'] is None or row['longitude'] is None:
            return context
        source = row['provenance'].split(':', 1)
        if len(source) != 2 or source[0] != ('provisional' if row['provisional'] else 'user_reported_reliable'):
            return context
        if row['place_id'] is None:
            if source[1] == 'user_supplied_coordinates':
                context['kind'] = 'manual'
            return context
        try:
            place = selected(row['place_id'])
        except ValueError:
            return context
        if self._label(place) != label:
            return context
        if source[1] == f'user_supplied_coordinates_place_{place["id"]}':
            context['latitude_override'] = row['latitude']
            context['longitude_override'] = row['longitude']
        elif source[1] != f'geonames_city_centre_{place["id"]}' or (
                row['latitude'], row['longitude']) != (place['latitude'], place['longitude']):
            return context
        context['kind'] = 'catalogue'
        context['place'] = {key: place[key] for key in
                            ('id', 'name', 'region', 'country', 'latitude', 'longitude', 'zone')}
        context['zone_override'] = row['zone_name'] if row['zone_name'] != place['zone'] else None
        return context

    @staticmethod
    def _label(place):
        return ', '.join(part for part in (place['name'], place['region'], place['country']) if part)

    def _result(self, session, row, reused):
        return {'birth_id': row['birth_id'], 'draft_revision': row['draft_revision'],
                'chart': self.people.charts.get_chart(session, row['chart_id']),
                'active_chart_id': self.people.active_chart_id(session, row['person_id']),
                'provisional': row['provisional'], 'place_id': row['place_id'], 'reused': reused}
