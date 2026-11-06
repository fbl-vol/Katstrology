"""Read-only, bounded sky-at-instant and selected natal-plus-transit geometry.

The view is an ephemeral calculation, never a saved chart or conversation turn.
No local houses, birth time or geographic coordinates are inferred for the sky.
"""

from datetime import datetime, timezone
import re

import swisseph as swe

from m2.operations.app_clock import reporting_zone
from m2.calculation.chart_source import NatalChartSource
from m2.calculation.ephemeris import BODY_IDS, LILITH_IDS, ephemeris as _ephemeris, position_at as _position_at
from m2.calculation.time import utc as _utc
from m2.calculation.natal import DEFAULT_ORBS, _aspects
from m2.calculation.synastry import pair_aspects

MAX_ASPECTS = 2048  # above the finite supported body-pair geometry
SKY_SETTINGS = {'zodiac': 'tropical', 'aspects': list(DEFAULT_ORBS), 'orbs': DEFAULT_ORBS}


class TransitInputError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def reporting_instant(day, clock, zone_name, occurrence='unspecified'):
    """Resolve a user-entered local wall time without inventing DST occurrence."""
    if (not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)
            or not isinstance(clock, str) or not re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', clock)
            or not isinstance(zone_name, str) or not zone_name
            or occurrence not in ('unspecified', 'earlier', 'later')):
        raise ValueError('Choose a date, clock time and IANA reporting zone')
    try:
        zone, _ = reporting_zone(zone_name)
        wall = datetime.fromisoformat(f'{day}T{clock}')
    except ValueError as exc:
        raise ValueError('Invalid date, time or IANA reporting zone') from exc
    candidates = [wall.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
    if not all(value.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == wall
               for value in candidates):
        raise TransitInputError('nonexistent_local_time')
    ambiguous = candidates[0].utcoffset() != candidates[1].utcoffset()
    if ambiguous and occurrence == 'unspecified':
        raise TransitInputError('choose_dst_occurrence')
    if not ambiguous and occurrence != 'unspecified':
        raise TransitInputError('occurrence_not_applicable')
    instant = candidates[1 if occurrence == 'later' else 0].astimezone(timezone.utc)
    return _utc(instant), {'date': day, 'time': clock, 'zone': zone_name,
                           'occurrence': occurrence, 'offset': candidates[1 if occurrence == 'later'
                                                                         else 0].strftime('%z')}


def view(store, session, day, clock, zone, occurrence, mode, chart_id=None):
    """Always fetch a selected immutable chart through the owner-scoped chart service."""
    store.owner(session)
    if mode not in ('sky', 'natal_transits') or (mode == 'sky' and chart_id is not None):
        raise ValueError('Choose sky only or one selected natal chart')
    if mode == 'natal_transits' and not isinstance(chart_id, str):
        raise ValueError('Select one immutable natal chart')
    instant, reporting = reporting_instant(day, clock, zone, occurrence)
    source = NatalChartSource(store)
    chart = natal = None
    if mode == 'natal_transits':
        chart, natal, unsupported = source.selected_natal(session, store._id(chart_id))
        if unsupported:
            return {'status': unsupported, 'mode': mode, 'chart_id': chart_id,
                    'instant_utc': instant.isoformat(), 'reporting': reporting}
        settings = chart['result']['profile']['settings']
        if settings['zodiac'] != 'tropical':
            raise ValueError('Selected chart is not tropical')
    else:
        settings = SKY_SETTINGS
    optional_chiron = settings.get('include_chiron', False)
    digests = _ephemeris(include_chiron=optional_chiron)
    positions = []
    lilith_id = LILITH_IDS[settings['include_lilith']] if settings.get('include_lilith') else None
    for body in (*BODY_IDS, *(('chiron',) if optional_chiron else ()),
                 *((lilith_id,) if lilith_id else ())):
        longitude, speed = _position_at(body, instant)
        positions.append({'id': body, 'longitude_degrees': longitude,
                          'sign': int(longitude // 30), 'speed_degrees_per_day': speed,
                          'retrograde': speed < 0})
    same_sky = _aspects(positions, settings)
    natal_aspects = []
    if natal:
        participants = [point for point in natal['positions'] if point['id'] in BODY_IDS
                        or (optional_chiron and point['id'] == 'chiron')
                        or point['id'] == 'north_node' or point['id'] == lilith_id]
        if natal['houses']['status'] == 'supported':
            participants += natal['houses']['angles']
        natal_aspects = pair_aspects(positions, participants, settings)
    return {'status': 'supported', 'mode': mode, 'instant_utc': instant.isoformat(),
            'reporting': reporting, 'zodiac': 'tropical', 'engine_version': swe.version,
            'ephemeris_sha256': digests, 'method': 'Swiss geocentric apparent tropical ecliptic longitude and speed; major longitude aspects',
            'orb_policy': settings['orbs'], 'positions': positions,
            **({'lilith_convention': settings['include_lilith'],
                'lilith_method': 'mean lunar apogee' if settings['include_lilith'] == 'mean'
                else 'true / osculating lunar apogee (not a claim of greater accuracy)'}
               if lilith_id else {}),
            'same_sky_aspects': same_sky[:MAX_ASPECTS], 'same_sky_total': len(same_sky),
            'transit_to_natal_aspects': natal_aspects[:MAX_ASPECTS],
            'transit_to_natal_total': len(natal_aspects), 'aspect_limit': MAX_ASPECTS,
            'aspect_order': 'smallest orb first, remaining omitted not absent',
            'chart_id': chart_id, 'source_status': chart['source_status'] if chart else None,
            'profile_id': chart['profile_id'] if chart else None,
            'profile_revision': chart['profile_revision'] if chart else None,
            'birth_time_status': 'exact_supplied_not_verified' if chart else 'not_applicable',
            'natal_house_status': natal['houses']['status'] if natal else 'not_applicable',
            'natal_positions': participants if natal else []}
