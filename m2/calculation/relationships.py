"""Two-source symbolic relationship geometries; neither creates a person's natal."""

from datetime import datetime

import swisseph as swe

from m2.calculation.ephemeris import BODY_IDS
from m2.calculation.natal import _aspects, calculate_natal
from m2.calculation.synastry import Synastry
from m2.calculation.chart_source import NatalChartSource
from m2.calculation.time import signed_angle as _angle

COMPOSITE_METHOD = 'midpoint-composite-shortest-ecliptic-v1'
DAVISON_METHOD = 'davison-uncorrected-algebraic-geography-v1'


def circular_midpoint(first, second):
    """None if antipodal longitudes admit two equally short midpoint arcs."""
    low, high = sorted((first % 360, second % 360))
    difference = _angle(high - low)
    if abs(abs(difference) - 180) < 1e-8:
        return None
    return (low + difference / 2) % 360


class Relationships:
    def __init__(self, store):
        self.synastry = Synastry(store)
        self.chart_source = NatalChartSource(store)

    def calculate(self, session, chart_a_id, chart_b_id, technique):
        if technique not in ('midpoint_composite', 'uncorrected_davison'):
            raise ValueError('Choose a supported two-source technique')
        checked = self.synastry.compare(session, chart_a_id, chart_b_id,
                                        {chart_a_id, chart_b_id})
        if checked['status'] != 'supported':
            return {key: checked[key] for key in ('status', 'chart_a_id', 'chart_b_id',
                                                   'person_a_id', 'person_b_id')}
        first, natal_a, missing_a = self.chart_source.selected_natal(session, chart_a_id)
        second, natal_b, missing_b = self.chart_source.selected_natal(session, chart_b_id)
        if missing_a or missing_b:
            return {'status': missing_a or missing_b, 'chart_a_id': chart_a_id,
                    'chart_b_id': chart_b_id}
        settings_a = first['result']['profile']['settings']
        settings_b = second['result']['profile']['settings']
        if technique == 'uncorrected_davison' and (
                settings_a['house_system'] != settings_b['house_system'] or
                settings_a['node_type'] != settings_b['node_type']):
            return {'status': 'unsupported_incompatible_house_or_node_profiles',
                    'chart_a_id': chart_a_id, 'chart_b_id': chart_b_id}
        included_chiron = bool(settings_a.get('include_chiron') and settings_b.get('include_chiron'))
        base = {'status': 'supported', 'technique': technique,
                'method_version': (COMPOSITE_METHOD if technique == 'midpoint_composite'
                                   else DAVISON_METHOD),
                'chart_a_id': chart_a_id, 'chart_b_id': chart_b_id,
                'person_a_id': first['person_id'], 'person_b_id': second['person_id'],
                'source_a_birth_id': first['birth_id'], 'source_b_birth_id': second['birth_id'],
                'profile_a_id': first['profile_id'], 'profile_a_revision': first['profile_revision'],
                'profile_b_id': second['profile_id'], 'profile_b_revision': second['profile_revision'],
                'engine_a_version': first['engine_version'],
                'engine_b_version': second['engine_version'],
                'ephemeris_a_sha256': natal_a['ephemeris_sha256'],
                'ephemeris_b_sha256': natal_b['ephemeris_sha256'],
                'source_a_status': first['source_status'], 'source_b_status': second['source_status'],
                'source_a_birth': first['result']['birth'],
                'source_b_birth': second['result']['birth'],
                'source_settings': settings_a,
                'included_chiron': included_chiron,
                'chiron_policy': 'Only present when both saved sources explicitly include Chiron; otherwise omitted.',
                'birth_time_policy': 'two exact supplied times, neither independently verified',
                'interpretation_policy': 'symbolic relationship geometry; no event, compatibility score or diagnosis'}
        if technique == 'midpoint_composite':
            a = {point['id']: point for point in natal_a['positions']}
            b = {point['id']: point for point in natal_b['positions']}
            ids = list(BODY_IDS) + (['chiron'] if included_chiron else [])
            positions = []
            for body in ids:
                longitude = circular_midpoint(a[body]['longitude_degrees'],
                                              b[body]['longitude_degrees'])
                positions.append({'id': body, 'longitude_degrees': longitude,
                    'status': 'supported' if longitude is not None else 'ambiguous_antipodal_midpoint',
                    'source_a_degrees': a[body]['longitude_degrees'],
                    'source_b_degrees': b[body]['longitude_degrees']})
            available = [point for point in positions if point['longitude_degrees'] is not None]
            aspects = _aspects(available, settings_a)
            return {**base, 'positions': positions,
                'position_status': 'partial_ambiguous_midpoints' if len(available) != len(ids)
                                   else 'supported',
                'aspects': aspects, 'aspects_total': len(aspects),
                'aspects_truncated': False,
                'frame': 'shortest circular ecliptic longitude, except exactly opposite points',
                'houses': 'not_defined', 'angles': 'not_defined',
                'physical_instant': None, 'speed': 'not_defined'}
        utc_a = datetime.fromisoformat(natal_a['instant_utc'])
        utc_b = datetime.fromisoformat(natal_b['instant_utc'])
        effective = utc_a + (utc_b - utc_a) / 2
        birth_a, birth_b = first['result']['birth'], second['result']['birth']
        if any(birth.get(key) is None for birth in (birth_a, birth_b)
               for key in ('latitude', 'longitude')):
            return {**base, 'status': 'unsupported_missing_source_coordinates'}
        latitude = (birth_a['latitude'] + birth_b['latitude']) / 2
        longitude = (birth_a['longitude'] + birth_b['longitude']) / 2
        # Keep the declared profile's house/node convention but never promote
        # the resulting chart to a person's active natal or invent provenance.
        derived_settings = {**settings_a}
        if not included_chiron:
            derived_settings.pop('include_chiron', None)
        derived = calculate_natal(effective, latitude, longitude, derived_settings)
        return {**base, 'derived_instant_utc': effective.isoformat(),
                'derived_latitude': latitude, 'derived_longitude': longitude,
                'geography_policy': ('arithmetic signed latitude and signed longitude means; '
                                     'not spherical/great-circle or corrected Davison'),
                'derived_status': derived['status'], 'derived_natal': derived,
                'derived_settings': derived_settings,
                'engine_version': swe.version}
