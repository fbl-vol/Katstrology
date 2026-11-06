"""Secondary progressed positions and two distinct fixed-natal-MC contact branches.

One lived anniversary year maps to one exact 86400-second ephemeris day.
MCp is a calendar-bracket interpolation of astronomical mapped MC; MCr is
sampled progressed planets against the fixed saved natal astronomical MC.
No mapped ephemeris instant is presented as a simultaneous real sky.
"""

from datetime import datetime, timedelta
from math import isfinite

import swisseph as swe

from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import BODY_IDS, position as _position
from m2.calculation.time import julian_ut as _jd, signed_angle as _angle, utc as _utc
from m2.calculation.returns import _anniversary
from m2.calculation.synastry import pair_aspects
from m2.calculation.core_calc import ASPECTS, END_YEAR, aspect_separation

METHOD = 'secondary-utc-calendar-naibod-mc-v1'


def calendar_map(birth, effective):
    birth, effective = _utc(birth), _utc(effective)
    if effective < birth:
        raise ValueError('Secondary progression before birth is unsupported')
    year = effective.year
    if effective < _anniversary(birth, year):
        year -= 1
    prior, following = _anniversary(birth, year), _anniversary(birth, year + 1)
    age = year - birth.year
    fraction = (effective - prior).total_seconds() / (following - prior).total_seconds()
    if not 0 <= fraction < 1:
        raise ValueError('Progressed anniversary fraction is outside its bracket')
    mapped = birth + timedelta(days=age + fraction)
    if mapped.year > END_YEAR:
        raise ValueError('Mapped progressed ephemeris date is unsupported')
    return age, fraction, prior, following, mapped


def interpolate_mc(left, right, fraction):
    if not 0 <= fraction <= 1:
        raise ValueError('MC interpolation fraction outside bracket')
    return (left + ((right - left + 180) % 360 - 180) * fraction) % 360


def _astronomical_mc(instant, latitude, longitude):
    if not all(isfinite(item) for item in (latitude, longitude)):
        return None
    if abs(latitude) >= 89.9 or instant.year > END_YEAR:
        return None
    try:
        _, axes = swe.houses_ex(_jd(instant), latitude, longitude, b'P')
    except swe.Error:
        return None
    return axes[1] % 360


def _contact(first, second, settings):
    matches = []
    for kind in settings['aspects']:
        orb = aspect_separation(first['longitude_degrees'], second['longitude_degrees'], kind)
        if orb <= settings['orbs'][kind]:
            matches.append({'first': first['id'], 'second': second['id'], 'kind': kind,
                            'orb_degrees': round(orb, 6), 'exact_degrees': ASPECTS[kind]})
    return matches


class Progressions:
    def __init__(self, store):
        self.chart_source = NatalChartSource(store)

    def mc_events(self, session, chart_id, start, end, branch, body, aspect):
        """Bounded effective-date exact contacts for one independently named MC branch."""
        start, end = _utc(start), _utc(end)
        if not start < end <= start + timedelta(days=2 * 366):
            raise ValueError('Choose a positive progressed MC window of at most 732 days')
        if branch not in ('mcp', 'mcr'):
            raise ValueError('Choose progressed MC or progressed planets to natal MC')
        chart, natal, unavailable = self.chart_source.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'chart_id': chart_id}
        settings = chart['result']['profile']['settings']
        if aspect not in settings['aspects']:
            raise ValueError('Aspect not declared in the selected natal')
        planets = dict(BODY_IDS)
        if settings.get('include_chiron'):
            planets['chiron'] = swe.CHIRON
        if body not in planets:
            raise ValueError('Choose a supported natal or progressed planet')
        if natal['houses']['status'] != 'supported':
            return {'status': 'unsupported_natal_mc_houses', 'chart_id': chart_id,
                    'mc_status': natal['houses']['status']}
        birth = datetime.fromisoformat(chart['result']['natal_sun']['instant_utc'])
        if start < birth:
            raise ValueError('Progressed MC interval cannot precede birth')
        natal_mc = next(item['longitude_degrees'] for item in natal['houses']['angles']
                        if item['id'] == 'midheaven')
        target = (next(point['longitude_degrees'] for point in natal['positions']
                       if point['id'] == body) if branch == 'mcp' else natal_mc)
        place = chart['result']['birth']

        def sample(instant):
            age, fraction, _, _, mapped = calendar_map(birth, instant)
            if branch == 'mcr':
                values = _position(planets[body], _jd(mapped))
                return values[0] % 360, values[3]
            left = _astronomical_mc(birth + timedelta(days=age),
                                    place['latitude'], place['longitude'])
            right = _astronomical_mc(birth + timedelta(days=age + 1),
                                     place['latitude'], place['longitude'])
            if left is None or right is None:
                raise ValueError('Mapped astronomical MC is unavailable in the requested interval')
            return interpolate_mc(left, right, fraction), None

        def refine(left, right, aim):
            sign = _angle(sample(left)[0] - aim) >= 0
            while right - left > timedelta(seconds=60):
                mid = left + (right - left) / 2
                if (_angle(sample(mid)[0] - aim) >= 0) == sign:
                    left = mid
                else:
                    right = mid
            return left + (right - left) / 2

        def stationary_longitude(left, right, initial_speed):
            sign = initial_speed >= 0
            while right - left > timedelta(seconds=60):
                mid = left + (right - left) / 2
                if (sample(mid)[1] >= 0) == sign:
                    left = mid
                else:
                    right = mid
            return sample(left + (right - left) / 2)[0]

        targets = sorted({(target + ASPECTS[aspect]) % 360,
                          (target - ASPECTS[aspect]) % 360})
        events = []
        cursor = start
        longitude, speed = sample(cursor)
        while cursor < end:
            following = min(cursor + timedelta(hours=12), end)
            next_longitude, next_speed = sample(following)
            if abs(_angle(next_longitude - longitude)) >= 10:
                raise ValueError('Progressed MC scan step has unsupported motion')
            station = (stationary_longitude(cursor, following, speed)
                       if branch == 'mcr' and speed is not None and next_speed is not None
                       and speed * next_speed < 0 else None)
            for aim in targets:
                a, b = _angle(longitude - aim), _angle(next_longitude - aim)
                if abs(b - a) >= 10:
                    continue  # wrapped signed distance at the opposite point
                if a == 0 or a * b < 0:
                    instant = cursor if a == 0 else refine(cursor, following, aim)
                    if instant < end and (not events or instant - events[-1]['instant_value'] >
                                          timedelta(seconds=60)):
                        events.append({'instant_value': instant, 'target_degrees': aim})
                if station is not None and abs(_angle(station - aim)) < .001:
                    # A near-station tangent need not change signed distance, even
                    # when both 12-hour endpoints lie on the same side of target.
                    # Do not claim complete coverage when that contact is ambiguous.
                    return {'status': 'partial_near_station_contact', 'chart_id': chart_id,
                            'branch': branch, 'window_utc': [start.isoformat(), end.isoformat()],
                            'reason': 'Station near selected target needs a separate tangency solver'}
            cursor, longitude, speed = following, next_longitude, next_speed
        return {'status': 'supported', 'technique': 'progressed_mc_contacts',
                'method_version': METHOD, 'branch': branch,
                'branch_description': ('MCp progressed astronomical MC to fixed natal planet'
                                       if branch == 'mcp' else
                                       'MCr directly progressed planet to fixed natal astronomical MC'),
                'chart_id': chart_id, 'person_id': chart['person_id'],
                'source_birth_id': chart['birth_id'], 'source_status': chart['source_status'],
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'engine_version': chart['engine_version'], 'ephemeris_sha256': natal['ephemeris_sha256'],
                'mc_status': natal['houses']['status'], 'natal_mc_degrees': natal_mc,
                'body': body, 'aspect': aspect, 'target_source_degrees': target,
                'window_utc': [start.isoformat(), end.isoformat()], 'window_end_inclusive': False,
                'scan_step_hours': 12, 'time_tolerance_seconds': 60,
                'events': [{'instant_utc': event['instant_value'].isoformat(),
                            'target_degrees': event['target_degrees']}
                           for event in events]}

    def calculate(self, session, chart_id, effective):
        effective = _utc(effective)
        chart, natal, unavailable = self.chart_source.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'chart_id': chart_id}
        source = chart['result']['natal_sun']
        if source['status'] != 'exact_supplied_time':
            return {'status': 'unsupported_uncertain_birth_time', 'chart_id': chart_id}
        birth = datetime.fromisoformat(source['instant_utc'])
        age, fraction, prior, following, mapped = calendar_map(birth, effective)
        settings = chart['result']['profile']['settings']
        planets = dict(BODY_IDS)
        if settings.get('include_chiron'):
            planets['chiron'] = swe.CHIRON
        jd = _jd(mapped)
        positions = []
        for name, body_id in planets.items():
            values = _position(body_id, jd)
            longitude = values[0] % 360
            positions.append({'id': name, 'longitude_degrees': longitude,
                'latitude_degrees': values[1], 'sign': int(longitude // 30),
                'speed_degrees_per_symbolic_day': values[3],
                'retrograde_at_mapped_time': values[3] < 0,
                'house': None})
        natal_points = [point for point in natal['positions'] if point['id'] in planets]
        natal_aspects = pair_aspects(positions, natal_points, settings)
        mc_status = natal['houses']['status']
        mcp, natal_mc = None, None
        mcp_contacts, mcr_contacts = [], []
        if mc_status == 'supported':
            natal_mc = next(item['longitude_degrees'] for item in natal['houses']['angles']
                            if item['id'] == 'midheaven')
            birth_place = chart['result']['birth']
            lat, lon = birth_place['latitude'], birth_place['longitude']
            mc_left = _astronomical_mc(birth + timedelta(days=age), lat, lon)
            mc_right = _astronomical_mc(birth + timedelta(days=age + 1), lat, lon)
            if mc_left is None or mc_right is None:
                mc_status = 'unsupported_mapped_mc'
            else:
                mcp = interpolate_mc(mc_left, mc_right, fraction)
                mcp_point = {'id': 'progressed_mc', 'longitude_degrees': mcp}
                natal_mc_point = {'id': 'natal_mc', 'longitude_degrees': natal_mc}
                mcp_contacts = [contact for point in natal_points for contact in
                                _contact(mcp_point, point, settings)]
                mcr_contacts = [contact for point in positions for contact in
                                _contact(point, natal_mc_point, settings)]
        return {'status': 'supported', 'technique': 'secondary_progression',
            'method_version': METHOD, 'chart_id': chart_id, 'person_id': chart['person_id'],
            'source_status': chart['source_status'], 'profile_id': chart['profile_id'],
            'profile_revision': chart['profile_revision'], 'source_birth_id': chart['birth_id'],
            'source_birth': chart['result']['birth'], 'source_settings': settings,
            'engine_version': chart['engine_version'], 'ephemeris_sha256': natal['ephemeris_sha256'],
            'birth_utc': birth.isoformat(), 'effective_utc': effective.isoformat(),
            'age_completed_years': age, 'anniversary_fraction': fraction,
            'anniversary_bracket_utc': [prior.isoformat(), following.isoformat()],
            'mapped_ephemeris_utc': mapped.isoformat(),
            'mapped_time_policy': 'one 86400-second symbolic ephemeris day per lived UTC anniversary year; not a simultaneous sky',
            'positions': positions,
            'natal_positions': [{'id': point['id'], 'longitude_degrees': point['longitude_degrees']}
                                for point in natal_points],
            'natal_aspects': natal_aspects,
            'natal_aspects_total': len(natal_aspects), 'natal_aspects_truncated': False,
            'mc_status': mc_status, 'natal_mc_degrees': natal_mc,
            'mcp_degrees': mcp, 'mcp_contacts': mcp_contacts,
            'mcr_contacts': mcr_contacts, 'mc_branch_policy': (
                'MCp is calendar-Naibod-style interpolation of mapped astronomical MC against fixed natal planets; '
                'MCr is directly sampled secondary progressed planets against the fixed natal astronomical MC; '
                'neither is a real-sky transit or a progressed Ascendant')}
