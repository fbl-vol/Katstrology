"""Bounded Western tropical natal calculation; no inferred birth instant or location.

All numerical facts come from Swiss Ephemeris. A house failure is never silently
reinterpreted as another house system. Returned dictionaries are immutable once
stored as a chart result; rendering and conversation read the same result.
"""

from datetime import timezone
from hashlib import sha256
from math import floor
from pathlib import Path

import swisseph as swe

from m2.core_calc import ASPECTS, END_YEAR, START_YEAR, aspect_separation


# Swiss lunar-apogee points, not asteroid 1181 or a hypothetical second Moon.
# "True" is the traditional name for an osculating calculation, not an accuracy claim.
LILITH_IDS = {'mean': 'lilith_mean', 'osculating': 'lilith_osculating'}
LILITH_BODY_IDS = {'lilith_mean': swe.MEAN_APOG, 'lilith_osculating': swe.OSCU_APOG}
BODY_IDS = {
    'sun': swe.SUN, 'moon': swe.MOON, 'mercury': swe.MERCURY,
    'venus': swe.VENUS, 'mars': swe.MARS, 'jupiter': swe.JUPITER,
    'saturn': swe.SATURN, 'uranus': swe.URANUS, 'neptune': swe.NEPTUNE,
    'pluto': swe.PLUTO,
}
HOUSE_CODES = {'placidus': b'P', 'whole_sign': b'W'}
DEFAULT_ORBS = {'conjunction': 8, 'opposition': 8, 'square': 6,
                'trine': 6, 'sextile': 4}
EPHE_FILES = ('sepl_18.se1', 'semo_18.se1')
CHIRON_FILE = 'seas_18.se1'
# Astrodienst's public main-asteroid file, 1800–2399 CE, pinned at
# github.com/aloistr/swisseph commit 94621aba9f3ff9c32cb721eac0380c30dbb153fe.
CHIRON_SHA256 = 'a2cd8fc33807c78ca9a700c91c2e042258b12fc4796519e00781440b5ad8b2e2'
EPHE_DIRECTORY = Path(__file__).resolve().parents[1] / '.local/ephe'
METHOD_VERSION = 'natal-tropical-v1'


def checked_natal_settings(settings):
    if (not isinstance(settings, dict) or set(settings) !=
            ({'chart_kind', 'zodiac', 'house_system', 'node_type', 'aspects', 'orbs'} |
             ({'include_chiron'} if settings.get('include_chiron') is True else set()) |
             ({'include_lilith'} if settings.get('include_lilith') in ('mean', 'osculating') else set())) or
            settings['chart_kind'] != 'natal' or settings['zodiac'] != 'tropical' or
            not isinstance(settings['house_system'], str) or
            settings['house_system'] not in HOUSE_CODES or
            settings['node_type'] not in ('true', 'mean') or
            not isinstance(settings['aspects'], list) or not settings['aspects'] or
            any(not isinstance(item, str) or item not in ASPECTS for item in settings['aspects']) or
            len(settings['aspects']) != len(set(settings['aspects'])) or
            not isinstance(settings['orbs'], dict) or
            set(settings['orbs']) != set(settings['aspects']) or
            any(type(orb) not in (int, float) or not 0 < orb <= 10
                for orb in settings['orbs'].values())):
        raise ValueError('Unsupported natal calculation profile')
    return settings


def _ephemeris(*, include_chiron=False):
    directory = EPHE_DIRECTORY.resolve()
    # Fail before calculation if the declared data files are missing. calc_ut's
    # returned flag is checked too: Swiss can otherwise fall back to Moshier.
    digests = {}
    for name in EPHE_FILES + ((CHIRON_FILE,) if include_chiron else ()):
        try:
            digests[name] = sha256((directory / name).read_bytes()).hexdigest()
        except FileNotFoundError as exc:
            if name == CHIRON_FILE:
                raise ValueError('chiron_data_missing_or_unverified') from exc
            raise RuntimeError(f'Required Swiss data file {name} is unavailable') from exc
        if name == CHIRON_FILE and digests[name] != CHIRON_SHA256:
            raise ValueError('chiron_data_missing_or_unverified')
    swe.set_ephe_path(str(directory))
    return digests


def _position(body_id, jd):
    values, flags = swe.calc_ut(jd, body_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    if not flags & swe.FLG_SWIEPH or not flags & swe.FLG_SPEED:
        raise RuntimeError('Swiss ephemeris or speed unavailable; no fallback permitted')
    return values


def _house_facts(jd, latitude, longitude, settings, positions):
    system = settings['house_system']
    if latitude is None or longitude is None:
        return {'status': 'unsupported_missing_coordinates', 'system': system, 'cusps': [], 'angles': []}
    if abs(latitude) >= 89.9:
        return {'status': 'unsupported_polar_location', 'system': system, 'cusps': [], 'angles': []}
    try:
        cusps, ascmc = swe.houses_ex(jd, latitude, longitude, HOUSE_CODES[system])
    except swe.Error:
        # swe.houses_ex raises on ERR rather than returning Porphyry's substitute.
        # The same failure can occur just below the polar circle.
        return {'status': 'unsupported_house_calculation', 'system': system, 'cusps': [], 'angles': []}
    angles = [
        {'id': name, 'longitude_degrees': angle, 'sign': int(angle // 30)}
        for name, angle in (('ascendant', ascmc[0]), ('midheaven', ascmc[1]))
    ]
    if system == 'placidus':
        # Conventional displayed chart house: project the body's longitude
        # onto the ecliptic (latitude zero), matching published cusp-based
        # house tables. True 3D house position can differ near a cusp (notably
        # for the Moon); never silently present it as this chart's convention.
        obliquity = _position(swe.ECL_NUT, jd)[0]
        try:
            placements = [swe.house_pos(ascmc[2], latitude, obliquity,
                                        (item['longitude_degrees'], 0.0), b'P')
                          for item in positions]
        except swe.Error:
            placements = []
        if len(placements) != len(positions) or any(not 1 <= point < 13 for point in placements):
            return {'status': 'unsupported_house_calculation', 'system': system,
                    'cusps': [], 'angles': []}
        for item, point in zip(positions, placements):
            item['house'] = floor(point)
    else:
        # Whole-sign house membership follows the ascendant sign (the house
        # boundary is a sign boundary, not the ascendant's degree).
        first_sign = int(ascmc[0] // 30)
        for item in positions:
            item['house'] = (item['sign'] - first_sign) % 12 + 1
    return {'status': 'supported', 'system': system,
            'cusps': [{'number': number, 'longitude_degrees': degree}
                      for number, degree in enumerate(cusps, 1)],
            'angles': angles}


def _aspects(points, settings):
    found = []
    for index, first in enumerate(points):
        for second in points[index + 1:]:
            for kind in settings['aspects']:
                orb = aspect_separation(first['longitude_degrees'], second['longitude_degrees'], kind)
                if orb <= settings['orbs'][kind]:
                    found.append({'first': first['id'], 'second': second['id'], 'kind': kind,
                                  'orb_degrees': orb, 'exact_degrees': ASPECTS[kind]})
    return sorted(found, key=lambda item: (item['orb_degrees'], item['first'], item['second'], item['kind']))


def calculate_natal(instant, latitude, longitude, settings):
    """Compute exact-time facts, with explicit partial status when houses fail."""
    checked_natal_settings(settings)
    if instant.tzinfo is None:
        raise ValueError('Aware birth instant required')
    utc = instant.astimezone(timezone.utc)
    if not START_YEAR <= utc.year <= END_YEAR:
        raise ValueError('Unsupported date outside declared 1900–2099 range')
    digests = _ephemeris(include_chiron=settings.get('include_chiron', False))
    _, jd = swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour,
                          utc.minute, utc.second + utc.microsecond / 1e6, swe.GREG_CAL)
    bodies = dict(BODY_IDS)
    if settings.get('include_chiron'):
        bodies['chiron'] = swe.CHIRON
    bodies['north_node'] = swe.TRUE_NODE if settings['node_type'] == 'true' else swe.MEAN_NODE
    positions = []
    for name, body_id in bodies.items():
        values = _position(body_id, jd)
        positions.append({'id': name, 'longitude_degrees': values[0],
                          'latitude_degrees': values[1], 'speed_degrees_per_day': values[3],
                          'sign': int(values[0] // 30), 'retrograde': values[3] < 0,
                          'house': None})
    north = positions[-1]
    south_longitude = (north['longitude_degrees'] + 180) % 360
    positions.append({'id': 'south_node', 'longitude_degrees': south_longitude,
                      'latitude_degrees': -north['latitude_degrees'],
                      'speed_degrees_per_day': north['speed_degrees_per_day'],
                      'sign': int(south_longitude // 30),
                      'retrograde': north['retrograde'], 'house': None,
                      'derived_from': 'selected_north_node_antipode'})
    if settings.get('include_lilith'):
        lilith_id = LILITH_IDS[settings['include_lilith']]
        values = _position(LILITH_BODY_IDS[lilith_id], jd)
        positions.append({'id': lilith_id, 'longitude_degrees': values[0],
                          'latitude_degrees': values[1], 'speed_degrees_per_day': values[3],
                          'sign': int(values[0] // 30), 'retrograde': values[3] < 0,
                          'house': None})
    houses = _house_facts(jd, latitude, longitude, settings, positions)
    # The antipode is displayed but excluded from aspect pairings: including
    # both nodes would duplicate mirrored aspects and add a tautological 180°.
    aspects = _aspects([item for item in positions if item['id'] != 'south_node'] + houses['angles'], settings)
    return {'status': 'complete' if houses['status'] == 'supported' else 'partial_unsupported_houses',
            'instant_utc': utc.isoformat(), 'positions': positions, 'houses': houses,
            'aspects': aspects, 'ephemeris_sha256': digests, 'method_version': METHOD_VERSION,
            **({'lilith_convention': settings['include_lilith'],
                'lilith_method': 'Swiss mean lunar apogee' if settings['include_lilith'] == 'mean'
                else 'Swiss osculating lunar apogee (traditionally true); neither ranks accuracy'}
               if settings.get('include_lilith') else {}),
            'aspect_participants': ('ten planets, ' + ('selected Chiron, ' if settings.get('include_chiron') else '') +
                                    ('selected lunar apogee, ' if settings.get('include_lilith') else '') +
                                    'selected north node, and angles only when supported; south node is a derived antipode')}
