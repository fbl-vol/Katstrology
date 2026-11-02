"""Actual geocentric syzygies and Swiss global eclipses, without visibility claims."""

from datetime import datetime, timedelta, timezone

import swisseph as swe

from m2.natal import BODY_IDS
from m2.transits import Transits, _angle, _position_at, _root, _utc
from m2.core_calc import aspect_separation

METHOD = 'actual-geocentric-lunations-global-eclipses-v1'
STEP = timedelta(hours=6)
MAX_WINDOW = timedelta(days=2 * 366)
MAX_ECLIPSES_PER_FAMILY = 32
PHASE_ANGLES = {'new': 0, 'full': 180}


def _jd(instant):
    instant = _utc(instant)
    return swe.utc_to_jd(instant.year, instant.month, instant.day, instant.hour,
                          instant.minute, instant.second + instant.microsecond / 1e6,
                          swe.GREG_CAL)[1]


def _utc_from_jdut(jd):
    year, month, day, hour, minute, second = swe.jdut1_to_utc(jd, swe.GREG_CAL)
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) + timedelta(seconds=second)


def _eclipse_type(planet, flags):
    if planet == 'solar':
        choices = ((swe.ECL_ANNULAR_TOTAL, 'hybrid'), (swe.ECL_TOTAL, 'total'),
                   (swe.ECL_ANNULAR, 'annular'), (swe.ECL_PARTIAL, 'partial'))
    else:
        choices = ((swe.ECL_TOTAL, 'total'), (swe.ECL_PARTIAL, 'partial'),
                   (swe.ECL_PENUMBRAL, 'penumbral'))
    for bit, label in choices:
        if flags & bit:
            return label
    raise ValueError('Swiss returned unrecognized global eclipse type')


class Lunations:
    def __init__(self, store):
        self.transits = Transits(store)

    def calculate(self, session, chart_id, start, end, natal_target, aspect):
        start, end = _utc(start), _utc(end)
        if not start < end <= start + MAX_WINDOW:
            raise ValueError(f'Choose a positive real-sky lunation window of at most {MAX_WINDOW.days} days')
        chart, natal, unavailable = self.transits.selected_natal(session, chart_id)
        if unavailable:
            return {'status': unavailable, 'chart_id': chart_id}
        settings = chart['result']['profile']['settings']
        if aspect not in settings['aspects']:
            raise ValueError('Choose an aspect declared in the saved natal profile')
        allowed = set(BODY_IDS) | ({'chiron'} if settings.get('include_chiron') else set())
        if natal_target in ('ascendant', 'midheaven'):
            if natal['houses']['status'] != 'supported':
                return {'status': 'unsupported_natal_angle', 'chart_id': chart_id,
                        'house_status': natal['houses']['status']}
            target = next(item['longitude_degrees'] for item in natal['houses']['angles']
                          if item['id'] == natal_target)
        elif natal_target in allowed:
            target = next(item['longitude_degrees'] for item in natal['positions']
                          if item['id'] == natal_target)
        else:
            raise ValueError('Choose a saved natal planet or qualified axis')

        def sky(instant):
            sun = _position_at('sun', instant)[0] % 360
            moon = _position_at('moon', instant)[0] % 360
            return sun, moon, (moon - sun) % 360

        def contacts(sun, moon):
            facts = []
            for body, longitude in (('sun', sun), ('moon', moon)):
                orb = aspect_separation(longitude, target, aspect)
                facts.append({'sky_body': body, 'longitude_degrees': longitude,
                              'natal_target': natal_target, 'natal_longitude_degrees': target,
                              'aspect': aspect, 'orb_degrees': orb,
                              'in_orb': orb <= settings['orbs'][aspect]})
            return facts

        # Include two-day edges solely for linking a maximum to its nearby
        # geocentric syzygy. Return only requested-window syzygies themselves.
        scan_start = max(datetime(1900, 1, 1, tzinfo=timezone.utc), start - timedelta(days=2))
        scan_end = min(datetime(2099, 12, 31, 23, 59, tzinfo=timezone.utc),
                       end + timedelta(days=2))
        syzygies = []
        cursor = scan_start
        last_sep = sky(cursor)[2]
        while cursor < scan_end:
            following = min(cursor + STEP, scan_end)
            next_sep = sky(following)[2]
            advance = (next_sep - last_sep) % 360
            if not 0 <= advance < 10:
                raise ValueError('Unsupported geocentric Moon–Sun motion within scan step')
            for phase, angle in PHASE_ANGLES.items():
                left, right = _angle(last_sep - angle), _angle(next_sep - angle)
                if abs(right - left) >= 10:
                    continue  # the opposite-phase discontinuity, not a root
                if left == 0 or left * right < 0:
                    instant = cursor if left == 0 else _root(cursor, following,
                        lambda when: _angle(sky(when)[2] - angle))
                    sun, moon, sep = sky(instant)
                    syzygies.append({'phase': phase, 'instant_utc': instant.isoformat(),
                                     'sun_degrees': sun, 'moon_degrees': moon,
                                     'separation_degrees': sep,
                                     'angular_residual_degrees': abs(_angle(sep - angle)),
                                     'contacts': contacts(sun, moon)})
            cursor, last_sep = following, next_sep

        eclipses = []
        for family in ('solar', 'lunar'):
            finder = (swe.sol_eclipse_when_glob if family == 'solar'
                      else swe.lun_eclipse_when)
            jd = _jd(max(datetime(1900, 1, 1, tzinfo=timezone.utc),
                         start - timedelta(days=1)))
            for _ in range(MAX_ECLIPSES_PER_FAMILY):  # fail closed if scan coverage is exhausted
                flags, times = finder(jd, swe.FLG_SWIEPH, 0, False)
                maximum = _utc_from_jdut(times[0])
                if maximum >= end:
                    break
                if maximum >= start:
                    sun, moon, sep = sky(maximum)  # checked Swiss-only flags
                    phase = 'new' if family == 'solar' else 'full'
                    matches = [event for event in syzygies if event['phase'] == phase and
                               abs(datetime.fromisoformat(event['instant_utc']) - maximum) <=
                               timedelta(days=2)]
                    if len(matches) != 1:
                        raise ValueError('Global eclipse lacked a unique nearby geocentric syzygy')
                    eclipses.append({'family': family, 'eclipse_type': _eclipse_type(family, flags),
                                     'global_flags': flags, 'maximum_utc': maximum.isoformat(),
                                     'linked_syzygy_utc': matches[0]['instant_utc'],
                                     'sun_degrees_at_maximum': sun,
                                     'moon_degrees_at_maximum': moon,
                                     'separation_degrees_at_maximum': sep,
                                     'contacts_at_maximum': contacts(sun, moon),
                                     'visibility': 'global_only_not_calculated_for_location'})
                jd = times[0] + 1  # next eclipse; never loop on the same maximum
            else:
                raise ValueError('More global eclipses than supported bounded search capacity')
        return {'status': 'supported', 'technique': 'actual_lunations_eclipses',
                'method_version': METHOD, 'chart_id': chart_id,
                'person_id': chart['person_id'], 'source_birth_id': chart['birth_id'],
                'source_status': chart['source_status'], 'profile_id': chart['profile_id'],
                'profile_revision': chart['profile_revision'],
                'engine_version': chart['engine_version'],
                'ephemeris_sha256': natal['ephemeris_sha256'],
                'natal_target': natal_target, 'natal_target_degrees': target,
                'aspect': aspect, 'orb_degrees': settings['orbs'][aspect],
                'window_utc': [start.isoformat(), end.isoformat()],
                'window_end_inclusive': False, 'scan_step_hours': 6,
                'root_bracket_seconds': 60,
                'syzygy_policy': 'geocentric apparent Moon–Sun ecliptic longitude crossing; not eclipse maximum',
                'eclipse_policy': 'Swiss global UT maximum and class; not locally visible by inference',
                'lunations': [event for event in syzygies
                              if start <= datetime.fromisoformat(event['instant_utc']) < end],
                'eclipses': sorted(eclipses, key=lambda item: item['maximum_utc'])}
