"""Bounded Swiss transit snapshots and refined crossings for an immutable natal chart.

This is ecliptic-longitude calculation, not a forecast interpretation, house
transit, progression or claimed compatibility with specialist prognosis software.
"""

from datetime import datetime, timedelta, timezone

import swisseph as swe

from m2.charts import Charts
from m2.natal import BODY_IDS, _ephemeris, _position
from m2.core_calc import ASPECTS, START_YEAR, END_YEAR, aspect_separation

STEP = timedelta(hours=1)
TOLERANCE = timedelta(seconds=60)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Timezone-aware instant required')
    instant = value.astimezone(timezone.utc)
    if not START_YEAR <= instant.year <= END_YEAR:
        raise ValueError('Transit instant outside supported 1900–2099 range')
    return instant


def _position_at(body, instant):
    utc = _utc(instant)
    _, jd = swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour, utc.minute,
                          utc.second + utc.microsecond / 1e6, swe.GREG_CAL)
    values = _position(swe.CHIRON if body == 'chiron' else BODY_IDS[body], jd)
    return values[0], values[3]


def _angle(value):
    """Signed shortest ecliptic distance to target; safe for <=1h planet motion."""
    return (value + 180) % 360 - 180


def _root(left, right, measure):
    left_value = measure(left)
    while right - left > TOLERANCE:
        middle = left + (right - left) / 2
        if (measure(middle) >= 0) == (left_value >= 0):
            left, left_value = middle, measure(middle)
        else:
            right = middle
    return left + (right - left) / 2


class Transits:
    def __init__(self, store):
        self.charts = Charts(store)

    def selected_natal(self, session, chart_id):
        """Validate one immutable natal version against current engine and source."""
        chart = self.charts.get_chart(session, chart_id)
        if chart['source_status'] != 'current':
            return chart, None, 'unsupported_stale_birth_source'
        natal = chart['result'].get('natal')
        if not natal or natal['status'] not in ('complete', 'partial_unsupported_houses'):
            return chart, None, 'unsupported_uncertain_birth_time_or_non_natal_chart'
        if chart['engine_version'] != swe.version or natal['ephemeris_sha256'] != _ephemeris(
                include_chiron=chart['result']['profile']['settings'].get('include_chiron', False)):
            raise ValueError('Natal and transit engine/data versions differ')
        return chart, natal, None

    def snapshot(self, session, chart_id, instant, transit_body, natal_body, aspect):
        instant = _utc(instant)
        chart, natal, unsupported = self.selected_natal(session, chart_id)
        if unsupported:
            return {'status': unsupported, 'chart_id': chart_id}
        position = self._selection(chart, natal, transit_body, natal_body, aspect)
        if position is None:
            return {'status': 'unsupported_natal_mc_houses', 'chart_id': chart_id}
        degree, speed = _position_at(transit_body, instant)
        orb = aspect_separation(degree, position, aspect)
        return {**self._metadata(chart, natal, transit_body, natal_body, aspect),
                'status': 'supported', 'instant_utc': instant.isoformat(),
                'transit_longitude_degrees': degree,
                'transit_speed_degrees_per_day': speed,
                'natal_longitude_degrees': position,
                'orb_degrees': orb,
                'in_orb': orb <= chart['result']['profile']['settings']['orbs'][aspect]}

    def events(self, session, chart_id, start, end, transit_body, natal_body, aspect):
        start, end = _utc(start), _utc(end)
        if end <= start or end - start > timedelta(days=30):
            raise ValueError('Transit event window must be positive and at most 30 days')
        chart, natal, unsupported = self.selected_natal(session, chart_id)
        if unsupported:
            return {'status': unsupported, 'chart_id': chart_id}
        position = self._selection(chart, natal, transit_body, natal_body, aspect)
        if position is None:
            return {'status': 'unsupported_natal_mc_houses', 'chart_id': chart_id}
        angle = ASPECTS[aspect]
        targets = sorted({(position + angle) % 360, (position - angle) % 360})
        result = []
        left, (longitude, _) = start, _position_at(transit_body, start)
        while left < end:
            right = min(left + STEP, end)
            next_longitude, _ = _position_at(transit_body, right)
            if abs(_angle(next_longitude - longitude)) >= 10:
                raise ValueError('Unsupported transit motion within scan step')
            for target in targets:
                a, b = _angle(longitude - target), _angle(next_longitude - target)
                if abs(b - a) >= 10:
                    continue  # signed distance wraps at the target's antipode
                if a == 0 or a * b < 0 or (right == end and b == 0):
                    instant = (left if a == 0 else right if b == 0 else
                               _root(left, right, lambda t: _angle(_position_at(transit_body, t)[0] - target)))
                    if not result or instant - result[-1]['instant_utc_value'] > TOLERANCE:
                        result.append({'instant_utc_value': instant, 'target_degrees': target})
            left, longitude = right, next_longitude
        return {**self._metadata(chart, natal, transit_body, natal_body, aspect),
                'status': 'supported', 'natal_longitude_degrees': position,
                'window_utc': [start.isoformat(), end.isoformat()],
                'window_end_inclusive': True, 'events': [
                    {'instant_utc': event['instant_utc_value'].isoformat(),
                     'target_degrees': event['target_degrees'], 'tolerance_seconds': 60}
                    for event in result],
                'method': 'hourly signed crossing scan and 60-second bisection; exact longitude only'}

    def mc_events(self, session, chart_id, start, end, transit_body, aspect):
        """Exact transit-to-fixed-astronomical-natal-MC contacts, not a tenth cusp."""
        result = self.events(session, chart_id, start, end, transit_body, 'midheaven', aspect)
        if result['status'] != 'supported':
            return result
        return {**result, 'technique': 'mc_transit',
                'events': [event for event in result['events']
                           if datetime.fromisoformat(event['instant_utc']) < _utc(end)],
                'window_end_inclusive': False,
                'method_version': 'natal-mc-transit-ecliptic-v1',
                'natal_mc_longitude_degrees': result['natal_longitude_degrees'],
                'method': 'hourly signed longitude crossing scan and <=60-second bisection against the saved natal astronomical MC; no tenth-house substitution'}

    def sky_events(self, session, chart_id, start, end, transit_body, kind):
        """Planet sign ingress or longitude-speed station; no house or natal claim."""
        start, end = _utc(start), _utc(end)
        if end <= start or end - start > timedelta(days=30):
            raise ValueError('Sky event window must be positive and at most 30 days')
        chart = self.charts.get_chart(session, chart_id)
        if chart['source_status'] != 'current':
            return {'status': 'unsupported_stale_birth_source', 'chart_id': chart_id}
        if chart['result']['profile']['settings']['zodiac'] != 'tropical':
            raise ValueError('Unsupported sky zodiac')
        optional_chiron = chart['result']['profile']['settings'].get('include_chiron', False)
        ephemeris = _ephemeris(include_chiron=optional_chiron)
        natal = chart['result'].get('natal')
        if natal and natal.get('ephemeris_sha256') and natal['ephemeris_sha256'] != ephemeris:
            raise ValueError('Natal and sky data versions differ')
        if (transit_body not in BODY_IDS and not (transit_body == 'chiron' and optional_chiron)) or kind not in ('ingress', 'station'):
            raise ValueError('Unsupported sky event selector')
        entries = []
        left, (longitude, speed) = start, _position_at(transit_body, start)
        while left < end:
            right = min(left + STEP, end)
            next_longitude, next_speed = _position_at(transit_body, right)
            if abs(_angle(next_longitude - longitude)) >= 10:
                raise ValueError('Unsupported sky motion within scan step')
            if kind == 'station':
                if speed == 0 or speed * next_speed < 0 or (right == end and next_speed == 0):
                    instant = (left if speed == 0 else right if next_speed == 0 else
                               _root(left, right, lambda t: _position_at(transit_body, t)[1]))
                    if not entries or instant - entries[-1]['instant_utc_value'] > TOLERANCE:
                        entries.append({'instant_utc_value': instant,
                                        'direction_after': 'retrograde' if next_speed < 0 else 'direct'})
            else:
                for target in range(0, 360, 30):
                    a, b = _angle(longitude - target), _angle(next_longitude - target)
                    if abs(b - a) >= 10:
                        continue  # wrap at antipode is not a sign ingress
                    if a == 0 or a * b < 0 or (right == end and b == 0):
                        instant = (left if a == 0 else right if b == 0 else
                                   _root(left, right, lambda t: _angle(_position_at(transit_body, t)[0] - target)))
                        if not entries or instant - entries[-1]['instant_utc_value'] > TOLERANCE:
                            entries.append({'instant_utc_value': instant, 'sign_entered':
                                            int(target // 30) if next_speed >= 0 else
                                            int(((target - 1) % 360) // 30),
                                            'target_degrees': target})
            left, longitude, speed = right, next_longitude, next_speed
        return {'status': 'supported', 'chart_id': chart_id,
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'engine_version': chart['engine_version'],
                'ephemeris_sha256': ephemeris,
                'birth_time_status': ('exact_supplied_time_not_verified' if natal and
                    natal['status'] in ('complete', 'partial_unsupported_houses') else
                    'natal_positions_unsupported_sky_only'),
                'transit_body_id': transit_body, 'kind': kind, 'zodiac': 'tropical',
                'unit': 'ecliptic_degree' if kind == 'ingress' else 'degree_per_day',
                'window_utc': [start.isoformat(), end.isoformat()], 'window_end_inclusive': True,
                'events': [{'instant_utc': event['instant_utc_value'].isoformat(),
                            'tolerance_seconds': 60,
                            **{key: value for key, value in event.items()
                               if key != 'instant_utc_value'}} for event in entries],
                'method': 'hourly longitude/speed sign crossing scan and 60-second bisection'}

    @staticmethod
    def _selection(chart, natal, transit_body, natal_body, aspect):
        settings = chart['result']['profile']['settings']
        allowed = set(BODY_IDS) | ({'chiron'} if settings.get('include_chiron') else set())
        if transit_body not in allowed or natal_body not in allowed | {'midheaven'}:
            raise ValueError('Unsupported planet or unselected Chiron; nodes and other angles excluded')
        if aspect not in settings['aspects']:
            raise ValueError('Aspect not declared in selected chart profile')
        if natal_body == 'midheaven':
            if natal['houses']['status'] != 'supported':
                return None
            return next(point['longitude_degrees'] for point in natal['houses']['angles']
                        if point['id'] == 'midheaven')
        return next(item['longitude_degrees'] for item in natal['positions']
                    if item['id'] == natal_body)

    @staticmethod
    def _metadata(chart, natal, transit_body, natal_body, aspect):
        return {'chart_id': chart['id'], 'profile_id': chart['profile_id'],
                'profile_revision': chart['profile_revision'],
                'engine_version': chart['engine_version'],
                'ephemeris_sha256': natal['ephemeris_sha256'],
                'transit_body_id': transit_body, 'natal_body_id': natal_body,
                'aspect': aspect, 'zodiac': 'tropical', 'unit': 'ecliptic_degree',
                'birth_time_status': 'exact_supplied_time_not_verified',
                'source_status': chart['source_status']}
