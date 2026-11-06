"""Small declared Swiss core: solar transit crossings and qualified solar intervals.

No station search, generic aspect-orb policy, rectification or specialist prognosis.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe


START_YEAR, END_YEAR = 1900, 2099  # conservative tested subset, not ephemeris file limits
STEP = timedelta(hours=1)
TOLERANCE = timedelta(seconds=60)
ASPECTS = {'conjunction': 0, 'sextile': 60, 'square': 90,
           'trine': 120, 'opposition': 180}


class NonexistentLocalTime(ValueError):
    pass


class AmbiguousLocalTime(ValueError):
    pass


def difference_degrees(actual, expected):
    """Signed shortest separation with the retained [-180, 180) convention."""
    return (actual - expected + 180) % 360 - 180


def local_instant(wall_time, zone, fold=None):
    """Reject gaps and unresolved folds; never use the machine's local zone."""
    if wall_time.tzinfo is not None:
        raise ValueError('Expected naive local wall time')
    if fold not in (None, 0, 1):
        raise ValueError('Fold must be 0 or 1')
    tz = ZoneInfo(zone)
    candidates = []
    for choice in (0, 1):
        local = wall_time.replace(tzinfo=tz, fold=choice)
        if local.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == wall_time:
            candidates.append(local)
    if not candidates:
        raise NonexistentLocalTime('Nonexistent local time')
    if candidates[0].utcoffset() != candidates[-1].utcoffset() and fold is None:
        raise AmbiguousLocalTime('Ambiguous local time: supply fold')
    return candidates[fold or 0].astimezone(timezone.utc)


def solar_longitude(instant):
    if instant.tzinfo is None:
        raise ValueError('UTC-aware instant required')
    utc = instant.astimezone(timezone.utc)
    if not START_YEAR <= utc.year <= END_YEAR:
        raise ValueError('Unsupported date outside declared 1900–2099 range')
    _, jd_ut = swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour,
                             utc.minute, utc.second + utc.microsecond / 1e6, swe.GREG_CAL)
    values, flags = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
    if not flags & swe.FLG_SWIEPH:
        raise RuntimeError('Unexpected Swiss ephemeris fallback')
    return values[0]


def aspect_separation(first, second, aspect):
    """Smallest absolute orb in degrees; not an assertion that an aspect is in orb."""
    if aspect not in ASPECTS:
        raise ValueError('Unsupported aspect')
    return abs(abs(difference_degrees(first, second)) - ASPECTS[aspect])


def solar_interval(start, end, *, max_hours=24):
    """Return endpoint span and sign stability for a bounded uncertain time.

    Solar motion is forward over this bounded interval; no houses/reference birth time.
    """
    if max_hours not in (24, 26) or end <= start or end - start > timedelta(hours=max_hours):
        raise ValueError('Unsupported solar interval')
    first, last = solar_longitude(start), solar_longitude(end)
    unwrapped_last = first + (last - first) % 360
    if not 0 < unwrapped_last - first < 2:
        raise ValueError('Unsupported solar motion')
    return {'start_degrees': first, 'end_degrees': last,
            'stable_sign': int(first // 30) if int(first // 30) == int(unwrapped_last // 30) else None,
            'houses': 'unsupported_without_verified_birth_time',
            'reference_time': None}


def solar_crossings(start, end, natal_longitude, aspect='conjunction'):
    """Locate Sun-to-fixed-natal ecliptic-longitude aspect crossings in <=30d.

    Hourly scan + bisection within 60 seconds. Not a general event/station engine.
    """
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=30):
        raise ValueError('Unsupported event window')
    if not 0 <= natal_longitude < 360:
        raise ValueError('Natal longitude must be degrees in [0, 360)')
    if aspect not in ASPECTS:
        raise ValueError('Unsupported aspect')
    targets = {(natal_longitude + ASPECTS[aspect]) % 360,
               (natal_longitude - ASPECTS[aspect]) % 360}
    found = []
    left = start
    left_position = solar_longitude(left)
    while left < end:
        right = min(left + STEP, end)
        right_position = solar_longitude(right)
        motion = (right_position - left_position) % 360
        if not 0 <= motion < 1:
            raise ValueError('Unsupported solar motion in scan')
        for target in targets:
            distance = (target - left_position) % 360
            if distance == 0:
                # A bisection just before this exact scan boundary may have
                # already reported the same crossing within its 60s tolerance.
                if not found or left - found[-1] > TOLERANCE:
                    found.append(left)
            elif distance <= motion:
                low, high = left, right
                while high - low > TOLERANCE:
                    middle = low + (high - low) / 2
                    if (solar_longitude(middle) - left_position) % 360 >= distance:
                        high = middle
                    else:
                        low = middle
                found.append(low + (high - low) / 2)
        left, left_position = right, right_position
    return sorted(found)
