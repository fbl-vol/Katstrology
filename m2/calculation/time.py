"""UTC/UT1 and signed-angle primitives shared by saved-chart techniques."""
from datetime import datetime, timedelta, timezone

import swisseph as swe

from m2.core_calc import START_YEAR, END_YEAR


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Timezone-aware instant required')
    instant = value.astimezone(timezone.utc)
    if not START_YEAR <= instant.year <= END_YEAR:
        raise ValueError('Transit instant outside supported 1900–2099 range')
    return instant


def julian_ut(instant):
    instant = utc(instant)
    return swe.utc_to_jd(instant.year, instant.month, instant.day,
                         instant.hour, instant.minute,
                         instant.second + instant.microsecond / 1e6, swe.GREG_CAL)[1]


def instant_from_julian_ut(jd):
    year, month, day, hour, minute, second = swe.jdut1_to_utc(jd, swe.GREG_CAL)
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) + timedelta(seconds=second)


def signed_angle(value):
    """Signed shortest ecliptic distance to target; safe for <=1h planet motion."""
    return (value + 180) % 360 - 180


def crossing_root(left, right, measure):
    """Refine a bracket to the shared 60-second scan tolerance, not a return root."""
    left_value = measure(left)
    while right - left > timedelta(seconds=60):
        middle = left + (right - left) / 2
        if (measure(middle) >= 0) == (left_value >= 0):
            left, left_value = middle, measure(middle)
        else:
            right = middle
    return left + (right - left) / 2
