"""Solar and lunar returns for one qualified, exact-time saved natal.

The crossing is geocentric and independent of the reference place. UTC/UT1
conversion and the source's checked Swiss data are shared with natal calculation.
"""

from datetime import datetime, timedelta, timezone
from math import isfinite

import swisseph as swe

from m2.natal import BODY_IDS, _position, calculate_natal
from m2.transits import Transits, _utc

METHOD = 'solar-return-utc-anniversary-v1'
LUNAR_METHOD = 'lunar-return-utc-interval-v1'
ROOT_SECONDS = 1
MAX_LUNAR_DAYS = 2 * 366
MAX_LUNAR_RETURNS = 32  # > two years of lunar cycles, while bounding chart generation


def _jd(instant):
    instant = _utc(instant)
    return swe.utc_to_jd(instant.year, instant.month, instant.day,
                         instant.hour, instant.minute,
                         instant.second + instant.microsecond / 1e6, swe.GREG_CAL)[1]


def _instant(jd):
    year, month, day, hour, minute, second = swe.jdut1_to_utc(jd, swe.GREG_CAL)
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) + timedelta(seconds=second)


def _distance(jd, body, target):
    return (_position(BODY_IDS[body], jd)[0] - target + 180) % 360 - 180


def _crossing(estimate, body, target):
    """Native candidate, verified flags, and a <=1s signed root bracket."""
    left, right = estimate - 2 / 24, estimate + 2 / 24
    a, b = _distance(left, body, target), _distance(right, body, target)
    if a > 0 or b < 0:
        raise ValueError('Return root is not bracketed; no result was published')
    while (right - left) * 86400 > ROOT_SECONDS:
        middle = (left + right) / 2
        if _distance(middle, body, target) < 0:
            left = middle
        else:
            right = middle
    root = (left + right) / 2
    residual = abs(_distance(root, body, target))
    # Moon moves at most ~16 degrees/day; a half-second bracket can account for
    # ~0.0001 degree. This bound also catches an unrelated native crossing.
    if residual > 0.0002:
        raise ValueError('Return angular residual exceeded the declared solver bound')
    return root, residual


def _anniversary(birth, year):
    try:
        return birth.replace(year=year)
    except ValueError:
        return birth.replace(year=year, day=28)  # February 29 convention.


def _place(latitude, longitude):
    if ((latitude is None) != (longitude is None) or
            latitude is None or type(latitude) not in (float, int) or
            type(longitude) not in (float, int) or
            not all(map(isfinite, (latitude, longitude))) or
            not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise ValueError('Choose an explicit valid reference latitude and longitude')


class Returns:
    def __init__(self, store):
        self.transits = Transits(store)

    def calculate(self, session, chart_id, technique, *, year=None, start=None, end=None,
                  latitude=None, longitude=None):
        if technique not in ('solar_return', 'lunar_return'):
            raise ValueError('Choose solar or lunar return')
        _place(latitude, longitude)
        chart, natal, unavailable = self.transits.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'technique': technique, 'chart_id': chart_id}
        if chart['result']['profile']['settings'].get('chart_kind') != 'natal':
            raise ValueError('Returns require a saved generated natal')
        source = chart['result']['natal_sun']
        if source['status'] != 'exact_supplied_time':
            return {'status': 'unsupported_uncertain_birth_time', 'technique': technique,
                    'chart_id': chart_id}
        birth = _utc(datetime.fromisoformat(source['instant_utc']))
        if technique == 'solar_return':
            if type(year) is not int or not birth.year <= year <= 2098 or start is not None or end is not None:
                raise ValueError('Choose a supported UTC anniversary year')
            start, end = _anniversary(birth, year), _anniversary(birth, year + 1)
        else:
            if year is not None or start is None or end is None:
                raise ValueError('Choose an explicit lunar return interval')
            start, end = _utc(start), _utc(end)
            if end <= start or end - start > timedelta(days=MAX_LUNAR_DAYS):
                raise ValueError(f'Lunar return interval must be positive and at most {MAX_LUNAR_DAYS} days')
        body = 'sun' if technique == 'solar_return' else 'moon'
        target = next(point['longitude_degrees'] for point in natal['positions'] if point['id'] == body)
        finder = swe.solcross_ut if body == 'sun' else swe.mooncross_ut
        lower, upper = _jd(start), _jd(end)
        roots = []
        start_residual = abs(_distance(lower, body, target))
        if start_residual < 1e-8:
            roots.append((lower, start_residual))
        cursor = lower + (1 / 86400 if roots else 0)
        while cursor < upper and len(roots) <= MAX_LUNAR_RETURNS:
            candidate = finder(target, cursor, swe.FLG_SWIEPH)
            if not isfinite(candidate) or candidate < cursor - 1e-8:
                raise ValueError('Swiss return crossing unavailable')
            root, residual = _crossing(candidate, body, target)
            if lower - 1e-8 <= root < upper - 1e-8 and (
                    not roots or root - roots[-1][0] > 1 / 86400):
                roots.append((root, residual))
            cursor = max(candidate, root) + 1 / 86400  # no second copy at a boundary
        if len(roots) > MAX_LUNAR_RETURNS:
            raise ValueError('Return interval exceeded bounded coverage')
        settings = chart['result']['profile']['settings']
        events = []
        for root, residual in roots:
            instant = _instant(root)
            calculated = calculate_natal(instant, latitude, longitude, settings)
            events.append({'instant_utc': instant.isoformat(), 'angular_residual_degrees': residual,
                           'root_bracket_seconds': ROOT_SECONDS, 'chart': calculated})
        return {'status': 'supported' if roots else 'no_return_in_window',
                'technique': technique, 'method_version': METHOD if body == 'sun' else LUNAR_METHOD,
                'chart_id': chart_id, 'person_id': chart['person_id'],
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'source_birth_id': chart['birth_id'], 'source_birth': chart['result']['birth'],
                'source_settings': settings, 'source_status': chart['source_status'],
                'engine_version': chart['engine_version'], 'ephemeris_sha256': natal['ephemeris_sha256'],
                'window_utc': [start.isoformat(), end.isoformat()], 'window_end_exclusive': True,
                'reference_place': {'latitude': latitude, 'longitude': longitude}, 'events': events}
