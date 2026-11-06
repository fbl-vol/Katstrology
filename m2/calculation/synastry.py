"""Bounded two-version ecliptic inter-chart aspects, not compatibility verdicts."""

from datetime import datetime
from math import floor

import swisseph as swe

from m2.calculation.charts import Charts
from m2.calculation.ephemeris import (BODY_IDS, EPHE_FILES,
                                      ephemeris as _ephemeris, position as _position)
from m2.calculation.core_calc import ASPECTS, aspect_separation

MAX_ASPECTS = 2048  # above the finite selected-body pair geometry
OVERLAY_METHOD = 'synastry-recipient-ecliptic-house-v1'


def recipient_overlay(donor, recipient):
    """Project the donor's saved tropical longitudes onto recipient houses only."""
    houses = recipient['result']['natal']['houses']
    if houses['status'] != 'supported':
        return {'status': houses['status'], 'recipient_house_system': houses['system'], 'placements': []}
    system = houses['system']
    if system not in ('placidus', 'whole_sign'):
        return {'status': 'unsupported_house_system', 'recipient_house_system': system, 'placements': []}
    if system == 'placidus':
        birth = recipient['result']['birth']
        when = datetime.fromisoformat(recipient['result']['natal']['instant_utc'])
        _, jd = swe.utc_to_jd(when.year, when.month, when.day, when.hour, when.minute,
                              when.second + when.microsecond / 1e6, swe.GREG_CAL)
        _ephemeris(include_chiron=recipient['result']['profile']['settings'].get('include_chiron', False))
        try:
            cusps, ascmc = swe.houses_ex(jd, birth['latitude'], birth['longitude'], b'P')
            obliquity = _position(swe.ECL_NUT, jd)[0]
        except swe.Error:
            return {'status': 'unsupported_house_projection', 'recipient_house_system': system,
                    'placements': []}
        if len(cusps) != 12 or len(houses['cusps']) != 12 or any(
                abs((current - saved['longitude_degrees'] + 180) % 360 - 180) > 1e-6
                for current, saved in zip(cusps, houses['cusps'])):
            raise ValueError('Recipient house source differs from its saved natal cusps')
    else:
        first_sign = floor(houses['angles'][0]['longitude_degrees'] / 30)

    placements = []
    for point in donor['result']['natal']['positions']:
        if point['id'] not in BODY_IDS and point['id'] != 'chiron':
            continue
        longitude = point['longitude_degrees']
        if system == 'whole_sign':
            house = (floor(longitude / 30) - first_sign) % 12 + 1
        else:
            try:
                placement = swe.house_pos(ascmc[2], birth['latitude'], obliquity,
                                          (longitude, 0.0), b'P')
            except swe.Error:
                return {'status': 'unsupported_house_projection', 'recipient_house_system': system,
                        'placements': []}
            if not 1 <= placement < 13:
                return {'status': 'unsupported_house_projection', 'recipient_house_system': system,
                        'placements': []}
            house = floor(placement)
            # An exact ecliptic cusp belongs to the house starting at that cusp.
            for cusp in houses['cusps']:
                if abs((longitude - cusp['longitude_degrees'] + 180) % 360 - 180) < 1e-8:
                    house = cusp['number']
                    break
        placements.append({'body_id': point['id'], 'longitude_degrees': longitude,
                           'recipient_house': house})
    return {'status': 'supported', 'recipient_house_system': system, 'placements': placements}


def pair_aspects(first, second, settings):
    """Deterministic circular geometry; input points are already qualified."""
    matches = []
    for a in first:
        for b in second:
            for kind in settings['aspects']:
                orb = aspect_separation(a['longitude_degrees'], b['longitude_degrees'], kind)
                if orb <= settings['orbs'][kind]:
                    matches.append({'a_body_id': a['id'], 'b_body_id': b['id'],
                                    'aspect': kind, 'orb_degrees': round(orb, 6),
                                    'exact_degrees': ASPECTS[kind]})
    return sorted(matches, key=lambda item: (item['orb_degrees'], item['a_body_id'],
                                              item['b_body_id'], item['aspect']))


class Synastry:
    def __init__(self, store):
        self.charts = Charts(store)

    def view(self, session, chart_a_id, chart_b_id):
        result = self.compare(session, chart_a_id, chart_b_id, {chart_a_id, chart_b_id})
        if result['status'] == 'supported':
            for suffix, chart_id in (('a', chart_a_id), ('b', chart_b_id)):
                natal = self.charts.get_chart(session, chart_id)['result']['natal']
                points = [item for item in natal['positions'] if item['id'] in BODY_IDS or item['id'] == 'chiron']
                if natal['houses']['status'] == 'supported':
                    points += natal['houses']['angles']
                result[f'positions_{suffix}'] = [
                    {'id': item['id'], 'longitude_degrees': item['longitude_degrees']}
                    for item in points]
        return result

    def compare(self, session, chart_a_id, chart_b_id, selected_charts):
        if chart_a_id == chart_b_id or {chart_a_id, chart_b_id} - set(selected_charts):
            raise ValueError('Select two distinct chart versions for this turn')
        a = self.charts.get_chart(session, chart_a_id)
        b = self.charts.get_chart(session, chart_b_id)
        if a['person_id'] == b['person_id']:
            raise ValueError('Synastry requires two distinct selected people')
        result = {'chart_a_id': a['id'], 'person_a_id': a['person_id'],
                  'chart_b_id': b['id'], 'person_b_id': b['person_id'],
                  'profile_a_id': a['profile_id'], 'profile_a_revision': a['profile_revision'],
                  'profile_b_id': b['profile_id'], 'profile_b_revision': b['profile_revision'],
                  'engine_a_version': a['engine_version'], 'engine_b_version': b['engine_version'],
                  'house_overlays': {'status': 'not_calculated'}, 'composite_chart': 'unsupported',
                  'method': 'geocentric tropical ecliptic-longitude inter-chart aspects; no score'}
        if a['source_status'] != 'current' or b['source_status'] != 'current':
            return {**result, 'status': 'unsupported_stale_birth_source',
                    'source_a_status': a['source_status'], 'source_b_status': b['source_status']}
        natal_a, natal_b = a['result'].get('natal'), b['result'].get('natal')
        if (not natal_a or not natal_b or
                natal_a['status'] not in ('complete', 'partial_unsupported_houses') or
                natal_b['status'] not in ('complete', 'partial_unsupported_houses')):
            return {**result, 'status': 'unsupported_uncertain_birth_time_or_non_natal_chart',
                    'reason': 'Inter-chart degrees require two exact supplied birth instants; no reference-time substitute'}
        settings_a, settings_b = (chart['result']['profile']['settings'] for chart in (a, b))
        if (settings_a['zodiac'] != settings_b['zodiac'] or
                settings_a['zodiac'] != 'tropical' or
                settings_a['aspects'] != settings_b['aspects'] or
                settings_a['orbs'] != settings_b['orbs']):
            return {**result, 'status': 'unsupported_incompatible_aspect_profiles',
                    'reason': 'Both charts must use the same zodiac, aspects and orbs'}
        if a['engine_version'] != b['engine_version'] or any(
                natal_a['ephemeris_sha256'].get(name) != natal_b['ephemeris_sha256'].get(name)
                for name in EPHE_FILES) or (
                'seas_18.se1' in natal_a['ephemeris_sha256'] and
                'seas_18.se1' in natal_b['ephemeris_sha256'] and
                natal_a['ephemeris_sha256']['seas_18.se1'] != natal_b['ephemeris_sha256']['seas_18.se1']):
            return {**result, 'status': 'unsupported_different_engine_data_versions'}
        def participants(natal):
            points = [item for item in natal['positions'] if item['id'] in BODY_IDS or item['id'] == 'chiron']
            if natal['houses']['status'] == 'supported':
                points += natal['houses']['angles']
            return points
        aspects = pair_aspects(participants(natal_a), participants(natal_b), settings_a)
        a_in_b, b_in_a = recipient_overlay(a, b), recipient_overlay(b, a)
        overlays = {'status': ('supported' if a_in_b['status'] == b_in_a['status'] == 'supported'
                               else 'partial_unavailable_houses'),
                    'method_version': OVERLAY_METHOD,
                    'placement_rule': 'donor saved ecliptic longitude projected at zero latitude into recipient saved house convention; exact cusp starts that house',
                    'a_in_b': a_in_b, 'b_in_a': b_in_a}
        return {**result, 'status': 'supported', 'house_overlays': overlays, 'zodiac': 'tropical',
                'unit': 'ecliptic_degree', 'orb_policy': settings_a['orbs'],
                'a_house_system': settings_a['house_system'],
                'b_house_system': settings_b['house_system'],
                'a_angles': natal_a['houses']['status'] == 'supported',
                'b_angles': natal_b['houses']['status'] == 'supported',
                'ephemeris_a_sha256': natal_a['ephemeris_sha256'],
                'ephemeris_b_sha256': natal_b['ephemeris_sha256'],
                'ephemeris_sha256': natal_a['ephemeris_sha256'],
                'a_birth_time': 'exact_supplied_not_verified',
                'b_birth_time': 'exact_supplied_not_verified',
                'aspects': aspects[:MAX_ASPECTS], 'total_aspects': len(aspects),
                'truncated': len(aspects) > MAX_ASPECTS,
                'ordering': 'smallest orb first; remaining results omitted, not absent'}
