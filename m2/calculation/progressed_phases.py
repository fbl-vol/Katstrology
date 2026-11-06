"""Symbolic progressed Moon–Sun phase cycle on the UTC secondary map."""

from datetime import datetime, timedelta
from math import floor

from m2.calculation.progressions import METHOD as PROGRESSION_METHOD, calendar_map
from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import position_at as _position_at
from m2.calculation.time import signed_angle as _angle, utc as _utc

METHOD = 'progressed-moon-sun-four-phase-utc-v1'
PHASES = {'new': 0, 'first_quarter': 90, 'full': 180, 'last_quarter': 270}
STEP = timedelta(days=5)
TOLERANCE = timedelta(seconds=60)
MAX_WINDOW = timedelta(days=40 * 366)


class ProgressedPhases:
    def __init__(self, store):
        self.chart_source = NatalChartSource(store)

    def calculate(self, session, chart_id, start, end):
        start, end = _utc(start), _utc(end)
        if not start < end <= start + MAX_WINDOW:
            raise ValueError('Choose a positive progressed phase interval of at most 40 years')
        chart, natal, unavailable = self.chart_source.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'chart_id': chart_id}
        source = chart['result']['natal_sun']
        if source['status'] != 'exact_supplied_time':
            return {'status': 'unsupported_uncertain_birth_time', 'chart_id': chart_id}
        birth = datetime.fromisoformat(source['instant_utc'])
        if start < birth:
            raise ValueError('Progressed phase interval cannot precede birth')

        def sample(effective):
            _, _, _, _, mapped = calendar_map(birth, effective)
            sun = _position_at('sun', mapped)[0] % 360
            moon = _position_at('moon', mapped)[0] % 360
            return (moon - sun) % 360, mapped, sun, moon

        def refine(left, right, target):
            sign = _angle(sample(left)[0] - target) >= 0
            while right - left > TOLERANCE:
                mid = left + (right - left) / 2
                if (_angle(sample(mid)[0] - target) >= 0) == sign:
                    left = mid
                else:
                    right = mid
            return left + (right - left) / 2

        natal_phase = (next(point['longitude_degrees'] for point in natal['positions']
                            if point['id'] == 'moon') -
                       next(point['longitude_degrees'] for point in natal['positions']
                            if point['id'] == 'sun')) % 360
        # Count full progressed lunations since birth, not just from the
        # requested search window. At most 200 mapped ephemeris days.
        cycle = 0
        past = natal_phase
        year_step = birth
        while year_step < start:
            year_step = min(year_step + timedelta(days=365), start)
            current = sample(year_step)[0]
            motion = (current - past) % 360
            if motion >= 90:
                raise ValueError('Unsupported progressed phase motion while assigning cycle')
            if current < past:
                cycle += 1
            past = current
        cursor = start
        (separation, _, _, _) = sample(cursor)
        absolute = separation + cycle * 360
        events = []
        while cursor < end:
            following = min(cursor + STEP, end)
            next_sep = sample(following)[0]
            advance = (next_sep - separation) % 360
            if not 0 <= advance < 10:
                raise ValueError('Unsupported progressed phase motion within scan step')
            next_absolute = absolute + advance
            for name, angle in PHASES.items():
                first_cycle = max(0, floor((absolute - angle) / 360))
                for index in range(first_cycle, floor((next_absolute - angle) / 360) + 2):
                    target = angle + index * 360
                    if not absolute <= target < next_absolute:
                        continue
                    instant = (cursor if abs(absolute - target) < 1e-10
                               else refine(cursor, following, angle))
                    if instant >= end:
                        continue
                    sep, mapped, sun, moon = sample(instant)
                    events.append({'phase': name, 'cycle_index': index,
                                   'effective_utc': instant.isoformat(),
                                   'mapped_ephemeris_utc': mapped.isoformat(),
                                   'progressed_sun_degrees': sun,
                                   'progressed_moon_degrees': moon,
                                   'separation_degrees': sep,
                                   'angular_residual_degrees': abs(_angle(sep - angle))})
            cursor, separation, absolute = following, next_sep, next_absolute
        events.sort(key=lambda event: event['effective_utc'])
        return {'status': 'supported', 'technique': 'progressed_lunar_phases',
                'method_version': METHOD, 'progression_method_version': PROGRESSION_METHOD,
                'chart_id': chart_id, 'person_id': chart['person_id'],
                'source_birth_id': chart['birth_id'], 'source_birth': chart['result']['birth'],
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'source_status': chart['source_status'], 'engine_version': chart['engine_version'],
                'ephemeris_sha256': natal['ephemeris_sha256'],
                'birth_utc': birth.isoformat(), 'natal_phase_degrees': natal_phase,
                'natal_positions': [{'id': point['id'], 'longitude_degrees': point['longitude_degrees']}
                                    for point in natal['positions'] if point['id'] in ('sun', 'moon')],
                'phase_targets_degrees': PHASES, 'window_utc': [start.isoformat(), end.isoformat()],
                'window_end_inclusive': False, 'scan_step_effective_days': 5,
                'root_bracket_seconds': 60, 'max_window_days': MAX_WINDOW.days,
                'phase_policy': ('Moon minus Sun ecliptic longitude at one-day-per-UTC-anniversary '
                                 'secondary mapped time; phase cycle counts from birth; '
                                 'not actual-sky lunations, lunar returns or predicted life events'),
                'events': events}
