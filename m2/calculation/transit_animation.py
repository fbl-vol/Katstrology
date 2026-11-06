"""Opt-in, bounded dated Swiss transit samples for a fixed owned natal.

The client interpolates only for motion. Exact degrees at intervening times must
be obtained from the ordinary dated transit view, not from the animation.
"""

from datetime import date, datetime, timedelta, timezone

from m2.calculation.core_calc import END_YEAR, START_YEAR
from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import BODY_IDS, position_at as _position_at

STEP = timedelta(minutes=15)
MAX_SPAN = timedelta(days=7)


def frames(store, session, chart_id, first_day, last_day):
    if not isinstance(first_day, date) or not isinstance(last_day, date):
        raise ValueError('Choose UTC calendar dates')
    start = datetime.combine(first_day, datetime.min.time(), timezone.utc)
    end = datetime.combine(last_day, datetime.min.time(), timezone.utc)
    if (end <= start or end - start > MAX_SPAN or
            not START_YEAR <= start.year <= END_YEAR or
            not START_YEAR <= end.year <= END_YEAR):
        raise ValueError('Choose a UTC interval of 1–7 days within 1900–2099')
    chart, natal, unsupported = NatalChartSource(store).selected_natal(session, store._id(chart_id))
    if unsupported:
        return {'status': unsupported, 'chart_id': chart_id}
    bodies = tuple(BODY_IDS)  # only actual transiting planets, never an interpolated apogee
    samples = []
    instant = start
    while instant <= end:
        samples.append([round(_position_at(body, instant)[0], 8) for body in bodies])
        instant += STEP
    return {'status': 'supported', 'method_version': 'transit-motion-sampled-v1',
            'chart_id': chart_id, 'person_id': chart['person_id'],
            'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
            'source_status': chart['source_status'], 'engine_version': chart['engine_version'],
            'ephemeris_sha256': natal['ephemeris_sha256'], 'start_utc': start.isoformat(),
            'end_utc': end.isoformat(), 'step_seconds': 900, 'bodies': bodies,
            'longitudes': samples,
            'qualification': 'Swiss dated 15-minute samples. Between samples, shortest-circle interpolation is illustrative, not an exact ephemeris position. Natal chart stays fixed; no houses or aspect events calculated.'}
