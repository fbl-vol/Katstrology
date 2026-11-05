"""All bounded geocentric crossings of four named planets over their own natal longitudes."""

from datetime import datetime, timedelta

from m2.natal import calculate_natal
from m2.returns import _place
from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import position_at as _position_at
from m2.calculation.time import signed_angle as _angle, utc as _utc

METHOD = 'planet-own-natal-longitude-all-passes-v1'
MAX_DAYS = {'venus': 5 * 366, 'mars': 5 * 366,
            'jupiter': 15 * 366, 'saturn': 32 * 366}
STEP = timedelta(days=1)
TOLERANCE = timedelta(seconds=1)
MAX_EVENTS = 64  # finite event guard, not a three-pass/one-cycle limit


class PlanetaryReturns:
    def __init__(self, store):
        self.chart_source = NatalChartSource(store)

    def calculate(self, session, chart_id, body, start, end, latitude, longitude):
        if body not in MAX_DAYS:
            raise ValueError('Choose Venus, Mars, Jupiter or Saturn return explicitly')
        _place(latitude, longitude)
        start, end = _utc(start), _utc(end)
        if not start < end <= start + timedelta(days=MAX_DAYS[body]):
            raise ValueError(f'Choose a positive {body} return window of at most {MAX_DAYS[body]} days')
        chart, natal, unavailable = self.chart_source.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'chart_id': chart_id}
        birth = datetime.fromisoformat(chart['result']['natal_sun']['instant_utc'])
        if start < birth:
            raise ValueError('Planetary return interval cannot precede birth')
        target = next(point['longitude_degrees'] for point in natal['positions']
                      if point['id'] == body)

        def sample(instant):
            degree, speed = _position_at(body, instant)
            return _angle(degree - target), speed

        def refine(left, right):
            sign = sample(left)[0] >= 0
            while right - left > TOLERANCE:
                mid = left + (right - left) / 2
                if (sample(mid)[0] >= 0) == sign:
                    left = mid
                else:
                    right = mid
            return left + (right - left) / 2

        def stationary(left, right, first_speed):
            sign = first_speed >= 0
            while right - left > TOLERANCE:
                mid = left + (right - left) / 2
                if (sample(mid)[1] >= 0) == sign:
                    left = mid
                else:
                    right = mid
            return left + (right - left) / 2

        roots = []
        def crossing(left, right, a, b):
            if abs(b - a) >= 10:
                return  # opposite-target signed angle discontinuity, not a root
            if abs(a) < 1e-8 or a * b < 0:
                instant = left if abs(a) < 1e-8 else refine(left, right)
                if instant < end and (not roots or instant - roots[-1] > TOLERANCE):
                    residual, _ = sample(instant)
                    if abs(residual) > .00002:
                        raise ValueError('Planetary return root residual exceeded one-second bound')
                    roots.append(instant)
                    if len(roots) > MAX_EVENTS:
                        raise ValueError('Return search exceeded event capacity; no incomplete history published')

        cursor = start
        angle, speed = sample(cursor)
        while cursor < end:
            following = min(cursor + STEP, end)
            next_angle, next_speed = sample(following)
            if abs(_angle(next_angle - angle)) >= 10:
                raise ValueError('Planetary return scan step has unsupported motion')
            if speed * next_speed < 0:
                station = stationary(cursor, following, speed)
                at_station, _ = sample(station)
                crossing(cursor, station, angle, at_station)
                crossing(station, following, at_station, next_angle)
                if abs(at_station) < .0001 and not any(abs(root - station) < STEP for root in roots):
                    return {'status': 'partial_near_station_contact', 'chart_id': chart_id,
                            'body': body, 'reason': 'Near-station tangency is unresolved; do not claim complete coverage'}
            else:
                crossing(cursor, following, angle, next_angle)
            cursor, angle, speed = following, next_angle, next_speed
        settings = chart['result']['profile']['settings']
        events = []
        for instant in roots:
            # The reference place changes house geometry only, not the
            # geocentric longitude crossing itself.
            calculated = calculate_natal(instant, latitude, longitude, settings)
            calculated['aspects_total'] = len(calculated['aspects'])
            calculated['aspects_truncated'] = False
            degree, speed = _position_at(body, instant)
            events.append({'instant_utc': instant.isoformat(),
                           'longitude_degrees': degree % 360,
                           'speed_degrees_per_day': speed,
                           'pass_direction': 'retrograde' if speed < 0 else 'direct',
                           'angular_residual_degrees': abs(_angle(degree - target)),
                           'chart': calculated})
        return {'status': 'supported', 'technique': 'planetary_return',
                'method_version': METHOD, 'chart_id': chart_id,
                'person_id': chart['person_id'], 'source_birth_id': chart['birth_id'],
                'source_birth': chart['result']['birth'],
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'source_settings': settings, 'source_status': chart['source_status'],
                'engine_version': chart['engine_version'],
                'ephemeris_sha256': natal['ephemeris_sha256'],
                'body': body, 'natal_longitude_degrees': target,
                'window_utc': [start.isoformat(), end.isoformat()],
                'window_end_inclusive': False, 'scan_step_days': 1,
                'root_bracket_seconds': 1, 'max_window_days': MAX_DAYS[body],
                'reference_place': {'latitude': latitude, 'longitude': longitude},
                'pass_policy': 'all direct and retrograde own-natal-longitude crossings, not one chosen cycle',
                'events': events}
