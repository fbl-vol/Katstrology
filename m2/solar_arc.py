"""True solar-arc directions, derived from the directly sampled secondary Sun."""

from m2.progressions import Progressions
from m2.synastry import pair_aspects
from m2.transits import Transits

METHOD = 'true-progressed-sun-forward-solar-arc-v1'


class SolarArc:
    def __init__(self, store):
        self.progressions = Progressions(store)
        self.transits = Transits(store)

    def calculate(self, session, chart_id, effective):
        progressed = self.progressions.calculate(session, chart_id, effective)
        if progressed['status'] != 'supported':
            return progressed
        chart, natal, missing = self.transits.selected_natal(session, chart_id)
        if missing:
            return {'status': missing, 'chart_id': chart_id}
        natal_sun = next(point['longitude_degrees'] for point in natal['positions']
                         if point['id'] == 'sun')
        progressed_sun = next(point['longitude_degrees'] for point in progressed['positions']
                              if point['id'] == 'sun')
        arc = (progressed_sun - natal_sun) % 360
        settings = chart['result']['profile']['settings']
        include = {point['id'] for point in progressed['positions']}
        original = [point for point in natal['positions'] if point['id'] in include]
        if natal['houses']['status'] == 'supported':
            original += natal['houses']['angles']
        directions = [{'id': point['id'], 'source_longitude_degrees': point['longitude_degrees'],
                       'longitude_degrees': (point['longitude_degrees'] + arc) % 360,
                       'point_kind': ('qualified_natal_axis' if point['id'] in ('ascendant', 'midheaven')
                                      else 'natal_planet')}
                      for point in original]
        natal_aspects = pair_aspects(directions, original, settings)
        return {'status': 'supported', 'technique': 'true_solar_arc', 'method_version': METHOD,
                'chart_id': chart_id, 'person_id': chart['person_id'],
                'source_birth_id': chart['birth_id'], 'source_birth': chart['result']['birth'],
                'source_status': chart['source_status'],
                'profile_id': chart['profile_id'], 'profile_revision': chart['profile_revision'],
                'source_settings': settings, 'engine_version': chart['engine_version'],
                'ephemeris_sha256': natal['ephemeris_sha256'],
                'birth_utc': progressed['birth_utc'], 'effective_utc': progressed['effective_utc'],
                'mapped_ephemeris_utc': progressed['mapped_ephemeris_utc'],
                'anniversary_bracket_utc': progressed['anniversary_bracket_utc'],
                'age_completed_years': progressed['age_completed_years'],
                'anniversary_fraction': progressed['anniversary_fraction'],
                'natal_sun_degrees': natal_sun, 'progressed_sun_degrees': progressed_sun,
                'arc_degrees': arc,
                'arc_lap_policy': 'supported birth/effective range gives fewer than 200 symbolic days and under one solar revolution; modulo retains the full forward arc',
                'arc_policy': ('true forward secondary progressed Sun displacement from saved natal Sun; '
                               'applied uniformly to qualified saved natal points; not fixed 1°/year, '
                               'not mean or converse, not MCp'),
                'axis_status': natal['houses']['status'], 'positions': directions,
                'natal_positions': [{'id': item['id'], 'longitude_degrees': item['longitude_degrees']}
                                    for item in original],
                'directed_natal_aspects': natal_aspects,
                'directed_natal_aspects_total': len(natal_aspects),
                'directed_natal_aspects_truncated': False,
                'physical_sky': 'not_defined', 'speed': 'not_defined',
                'houses': 'not_defined', 'retrograde': 'not_defined'}
