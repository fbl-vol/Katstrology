"""Owner-scoped immutable birth/profile/chart versions; solar legacy and natal.

An interval is a supplied uncertainty window, not a verified or invented birth
instant. Source-linked records disappear with their source conversation.
"""

from datetime import datetime, timezone
from pathlib import Path
from math import isfinite
from zoneinfo import ZoneInfo

import psycopg
import swisseph as swe

from m2.core_calc import (ASPECTS, aspect_separation, local_instant,
                              solar_crossings, solar_interval, solar_longitude)

from m2.natal import calculate_natal, checked_natal_settings
from m2.provenance import source_turn_current


PROFILE_KEYS = {'zodiac', 'house_system', 'node_type', 'aspects'}
BODY_ALIASES = {'sun': 'sun', 'sol': 'sun'}


def resolve_body(name):
    if not isinstance(name, str):
        raise ValueError('Unsupported body')
    key = name.strip().casefold()
    if key == 'vulcan':
        raise ValueError('Ambiguous Vulcan: specify an independently defined point and method')
    if key == 'vulcanus':
        raise ValueError('Unsupported hypothetical Vulcanus point')
    if key not in BODY_ALIASES:
        raise ValueError('Unsupported body')
    return BODY_ALIASES[key]



def checked_settings(settings):
    if isinstance(settings, dict) and settings.get('chart_kind') == 'natal':
        return checked_natal_settings(settings)
    if (not isinstance(settings, dict) or set(settings) != PROFILE_KEYS
            or settings['zodiac'] != 'tropical' or settings['house_system'] != 'none'
            or settings['node_type'] != 'true'
            or not isinstance(settings['aspects'], list) or not settings['aspects']
            or len(settings['aspects']) != len(set(settings['aspects']))
            or any(aspect not in ASPECTS for aspect in settings['aspects'])):
        raise ValueError('Unsupported calculation profile')
    return settings


def _swiss_files():
    swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Aware UTC boundary required')
    return value.astimezone(timezone.utc)


class Charts:
    def __init__(self, store):
        self.store = store

    def add_person(self, session, person_id, name):
        owner = self.store.owner(session)
        self.store._id(person_id)
        self.store._text(name, 128)
        if self.store.ledger.contains_person(owner, person_id):
            raise ValueError('Deleted person identity cannot be reused')
        self.store.db.execute('INSERT INTO people(owner_id,id,name) VALUES (%s,%s,%s)',
                              (owner, person_id, name))
        return person_id

    def add_birth(self, session, person_id, birth_id, zone_name, provenance,
                  wall_time=None, fold=None, earliest_utc=None, latest_utc=None,
                  latitude=None, longitude=None, source=None, max_interval_hours=24):
        owner = self.store.owner(session)
        self.store._id(person_id)
        self.store._id(birth_id)
        self.store._text(provenance, 256)
        ZoneInfo(zone_name)
        if (latitude is None) != (longitude is None) or (
                latitude is not None and (type(latitude) not in (int, float) or
                type(longitude) not in (int, float) or not isfinite(latitude) or
                not isfinite(longitude) or not -90 <= latitude <= 90 or
                not -180 <= longitude <= 180)):
            raise ValueError('Coordinates must be a valid pair')
        if (wall_time is None) == (earliest_utc is None or latest_utc is None):
            raise ValueError('Supply exact local time or an explicit UTC uncertainty interval')
        if wall_time is not None:
            if not isinstance(wall_time, datetime):
                raise ValueError('Local wall time required')
            instant = local_instant(wall_time, zone_name, fold)
            earliest = latest = None
        else:
            if fold is not None:
                raise ValueError('Fold only applies to a supplied local wall time')
            instant = None
            earliest, latest = _utc(earliest_utc), _utc(latest_utc)
            _swiss_files()
            solar_interval(earliest, latest, max_hours=max_interval_hours)  # validates supported interval/range
        if source is not None:
            conv_id, turn_id = source
            turn = self.store.read_turn(session, conv_id, turn_id)
            if turn['status'] != 'complete':
                raise ValueError('Birth source must be a completed owned turn')
        else:
            conv_id = turn_id = None
        self.store.db.execute('''
            INSERT INTO birth_records(owner_id,person_id,id,wall_time,zone_name,fold,
                instant_utc,earliest_utc,latest_utc,latitude,longitude,provenance,
                source_conversation_id,source_turn_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (owner, person_id, birth_id, wall_time.isoformat() if wall_time else None,
              zone_name, fold, instant, earliest, latest, latitude, longitude,
              provenance, conv_id, turn_id))
        return birth_id

    def add_profile(self, session, profile_id, settings):
        owner = self.store.owner(session)
        self.store._id(profile_id)
        checked_settings(settings)
        with self.store.db.transaction():
            revision = self.store.db.execute('''
                SELECT coalesce(max(revision),0)+1 AS next FROM calculation_profiles
                WHERE owner_id=%s AND id=%s
            ''', (owner, profile_id)).fetchone()['next']
            self.store.db.execute('''
                INSERT INTO calculation_profiles(owner_id,id,revision,settings)
                VALUES (%s,%s,%s,%s)
            ''', (owner, profile_id, revision, psycopg.types.json.Jsonb(settings)))
        return revision

    def create_chart(self, session, chart_id, person_id, birth_id, profile_id, revision):
        owner = self.store.owner(session)
        for value in (chart_id, person_id, birth_id, profile_id):
            self.store._id(value)
        birth = self.store.db.execute('''
            SELECT * FROM birth_records WHERE owner_id=%s AND person_id=%s AND id=%s
        ''', (owner, person_id, birth_id)).fetchone()
        profile = self.store.db.execute('''
            SELECT settings FROM calculation_profiles WHERE owner_id=%s AND id=%s AND revision=%s
        ''', (owner, profile_id, revision)).fetchone()
        if not birth or not profile:
            raise KeyError('Birth record or calculation profile not found')
        if birth['source_conversation_id']:
            conv_id, turn_id = birth['source_conversation_id'], birth['source_turn_id']
            head = self.store.active_head(session, conv_id)
            turn = self.store.read_turn(session, conv_id, turn_id)
            if (turn['corrections'] or not head or
                    turn_id not in self.store.ancestry(session, conv_id, head) or
                    not source_turn_current(self.store, session, conv_id, turn_id)):
                raise ValueError('Birth source is superseded or off the active branch')
        checked_settings(profile['settings'])
        # Swiss settings are process-global in this local single-owner gateway.
        _swiss_files()
        natal = None
        if birth['instant_utc']:
            if profile['settings'].get('chart_kind') == 'natal':
                natal = calculate_natal(birth['instant_utc'], birth['latitude'],
                                        birth['longitude'], profile['settings'])
                longitude = natal['positions'][0]['longitude_degrees']
            else:
                longitude = solar_longitude(birth['instant_utc'])
            values = {'status': 'exact_supplied_time', 'sun_longitude_degrees': longitude,
                      'sun_sign': int(longitude // 30), 'instant_utc': birth['instant_utc'].isoformat()}
        else:
            interval = solar_interval(birth['earliest_utc'], birth['latest_utc'],
                                      max_hours=26 if profile['settings'].get('chart_kind') == 'natal' else 24)
            values = {'status': 'uncertain_supplied_interval', 'solar_interval': interval,
                      'earliest_utc': birth['earliest_utc'].isoformat(),
                      'latest_utc': birth['latest_utc'].isoformat()}
            if profile['settings'].get('chart_kind') == 'natal':
                natal = {'status': 'unsupported_uncertain_birth_time', 'positions': [],
                         'aspects': [], 'houses': {'status': 'unsupported_uncertain_birth_time',
                             'system': profile['settings']['house_system'], 'cusps': [], 'angles': []},
                         'method_version': 'natal-tropical-v1',
                         'reason': 'No exact supplied instant; positions, angles and aspects not established'}
        result = {'natal_sun': values, 'houses': 'unsupported', 'aspects': 'unsupported_without_supported_second_body',
                  'profile': {'id': profile_id, 'revision': revision, 'settings': profile['settings']},
                  'birth': {'id': birth_id, 'person_id': person_id, 'zone': birth['zone_name'],
                            'wall_time': birth['wall_time'], 'fold': birth['fold'],
                            'latitude': birth['latitude'], 'longitude': birth['longitude'],
                            'provenance': birth['provenance'], 'source_conversation_id': birth['source_conversation_id'],
                            'source_turn_id': birth['source_turn_id']},
                  'engine': {'name': 'Swiss Ephemeris', 'version': swe.version,
                             'method': 'tropical geocentric apparent Sun; Swiss ephemeris required; 1900–2099'}}
        if natal is not None:
            result['natal'] = natal
            result['houses'] = natal['houses']['status']
            result['aspects'] = natal['aspects']
            result['engine']['method'] = ('tropical geocentric apparent planets; '
                                          'declared node, houses and orbs; Swiss files required; 1900–2099')
        self.store.db.execute('''
            INSERT INTO charts(owner_id,id,person_id,birth_id,profile_id,profile_revision,result,engine_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (owner, chart_id, person_id, birth_id, profile_id, revision,
              psycopg.types.json.Jsonb(result), swe.version))
        return self.get_chart(session, chart_id)

    def find_events(self, session, chart_id, start, end, body='sun', aspect='conjunction'):
        """Sun-to-fixed-natal-Sun crossing, closed <=30-day UTC window only."""
        if resolve_body(body) != 'sun':
            raise ValueError('Unsupported body')
        chart = self.get_chart(session, chart_id)
        profile = chart['result']['profile']['settings']
        if aspect not in profile['aspects']:
            raise ValueError('Unsupported aspect in chart profile')
        if chart['source_status'] != 'current':
            return {'status': 'unsupported_stale_birth_source', 'chart_id': chart_id,
                    'source_status': chart['source_status']}
        natal = chart['result']['natal_sun']
        if natal['status'] != 'exact_supplied_time':
            return {'status': 'unsupported_uncertain_birth_time', 'chart_id': chart_id,
                    'reason': 'Fixed natal degree not established across supplied interval'}
        start, end = _utc(start), _utc(end)
        _swiss_files()
        instants = solar_crossings(start, end, natal['sun_longitude_degrees'], aspect)
        return {'status': 'supported', 'chart_id': chart_id, 'profile_revision': chart['profile_revision'],
                'body_id': 'sun', 'natal_body_id': 'sun', 'aspect': aspect,
                'window_utc': [start.isoformat(), end.isoformat()], 'window_end_inclusive': True,
                'events': [{'instant_utc': item.isoformat(), 'tolerance_seconds': 60}
                           for item in instants], 'method': 'hourly scan and 60-second bisection',
                'engine_version': chart['engine_version']}

    def transit_at(self, session, chart_id, instant, body='sun', aspect='conjunction'):
        if resolve_body(body) != 'sun':
            raise ValueError('Unsupported body')
        chart = self.get_chart(session, chart_id)
        if aspect not in chart['result']['profile']['settings']['aspects']:
            raise ValueError('Unsupported aspect in chart profile')
        if chart['source_status'] != 'current':
            return {'status': 'unsupported_stale_birth_source', 'chart_id': chart_id,
                    'source_status': chart['source_status']}
        natal = chart['result']['natal_sun']
        if natal['status'] != 'exact_supplied_time':
            return {'status': 'unsupported_uncertain_birth_time', 'chart_id': chart_id,
                    'reason': 'Precise natal aspect is not established'}
        _swiss_files()
        transit = solar_longitude(_utc(instant))
        return {'status': 'supported', 'chart_id': chart_id, 'body_id': 'sun',
                'instant_utc': _utc(instant).isoformat(), 'transit_longitude_degrees': transit,
                'natal_longitude_degrees': natal['sun_longitude_degrees'], 'aspect': aspect,
                'separation_from_exact_aspect_degrees': aspect_separation(
                    transit, natal['sun_longitude_degrees'], aspect),
                'in_orb': 'unsupported_without_declared_orb_policy',
                'engine_version': chart['engine_version']}

    def get_chart(self, session, chart_id):
        owner = self.store.owner(session)
        row = self.store.db.execute('''
            SELECT id, person_id, birth_id, profile_id, profile_revision, result,
                   engine_version, created_at FROM charts WHERE owner_id=%s AND id=%s
        ''', (owner, self.store._id(chart_id))).fetchone()
        if not row:
            raise KeyError('Chart not found')
        birth = row['result']['birth']
        conv_id, turn_id = birth['source_conversation_id'], birth['source_turn_id']
        row['source_status'] = 'current'
        if conv_id:
            turn = self.store.read_turn(session, conv_id, turn_id)
            head = self.store.active_head(session, conv_id)
            ancestry = self.store.ancestry(session, conv_id, head) if head else []
            if turn['corrections']:
                row['source_status'] = 'superseded'
            elif turn_id not in ancestry:
                row['source_status'] = 'abandoned_branch'
            elif not source_turn_current(self.store, session, conv_id, turn_id):
                row['source_status'] = 'superseded'
        return row
