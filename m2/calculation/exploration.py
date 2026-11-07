"""Owner-scoped read projection of immutable natal facts, never canonical evidence."""
from itertools import combinations
from math import isfinite

from .aspect_patterns import aspect_patterns
from .pattern_catalogue import (ANGLES, MEMBERS, MINOR_ORBS, RULE_VERSION,
                                catalogue, edge_id, separation)
from .position_patterns import position_patterns


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _qualified_edges(natal, settings, positions):
    evidence = {}
    aspects, orbs = settings.get('aspects'), settings.get('orbs')
    major_available = isinstance(aspects, list) and isinstance(orbs, dict) and isinstance(natal.get('aspects'), list)
    enabled = set()
    if major_available:
        enabled = {kind for kind in aspects if _number(orbs.get(kind)) and orbs[kind] >= 0}
        for aspect in natal['aspects']:
            first, second, kind = (aspect.get(key) for key in ('first', 'second', 'kind'))
            if first not in MEMBERS or second not in MEMBERS or first == second or kind in MINOR_ORBS:
                continue
            orb, limit = aspect.get('orb_degrees'), orbs.get(kind)
            if kind in enabled and _number(orb) and 0 <= orb <= limit:
                identity = edge_id(first, second, kind)
                # Saved duplicate/reversed rows collapse deterministically.
                candidate = {'id': identity, 'first': min(first, second), 'second': max(first, second),
                             'kind': kind, 'orb_degrees': orb, 'limit_degrees': limit,
                             'exact_degrees': next((angle for angle, name in ANGLES.items() if name == kind), None),
                             'origin': 'saved'}
                if identity not in evidence or orb < evidence[identity]['orb_degrees']:
                    evidence[identity] = candidate
    for first, second in combinations(sorted(positions), 2):
        distance = separation(positions[first]['longitude_degrees'], positions[second]['longitude_degrees'])
        for angle, kind in ANGLES.items():
            if kind not in MINOR_ORBS:
                continue
            orb = abs(distance - angle)
            if orb <= MINOR_ORBS[kind]:
                identity = edge_id(first, second, kind)
                evidence[identity] = {'id': identity, 'first': first, 'second': second, 'kind': kind,
                                      'orb_degrees': orb, 'limit_degrees': MINOR_ORBS[kind],
                                      'exact_degrees': angle, 'origin': 'derived'}
    return evidence, enabled, major_available


def explore_chart(chart):
    """Never recalculate a chart, consult current preferences or write saved facts."""
    rules = catalogue()
    result = {'chart_id': chart['id'], 'rule_version': RULE_VERSION,
              'source_status': chart['source_status'], 'status': 'unavailable',
              'reason': None, 'patterns': [], 'catalogue': rules, 'evidence': [],
              'distribution': None}
    for rule in rules:
        rule.update(status='unavailable', reason='unusable_facts', matches=0)
    if chart['source_status'] != 'current':
        return {**result, 'reason': 'historical_source'}
    saved = chart['result']
    natal = saved.get('natal')
    if not natal:
        return {**result, 'reason': 'legacy_chart'}
    if natal.get('status') not in ('complete', 'partial_unsupported_houses'):
        return {**result, 'reason': natal.get('status', 'unusable_facts')}
    positions = {}
    for position in natal.get('positions', []):
        body = position.get('id')
        if body not in MEMBERS:
            continue
        degree = position.get('longitude_degrees')
        if body in positions or not _number(degree) or not 0 <= degree < 360:
            return {**result, 'reason': 'unusable_facts'}
        positions[body] = position
    if set(positions) != MEMBERS:
        return {**result, 'reason': 'unusable_facts'}

    settings = saved.get('profile', {}).get('settings', {})
    evidence, enabled, major_available = _qualified_edges(natal, settings, positions)
    houses = natal.get('houses', {})
    cusps = houses.get('cusps', [])
    houses_available = (natal['status'] == 'complete' and houses.get('status') == 'supported' and len(cusps) == 12
                        and {c.get('number') for c in cusps} == set(range(1, 13))
                        and all(_number(c.get('longitude_degrees')) and 0 <= c['longitude_degrees'] < 360 for c in cusps)
                        and all(type(p.get('house')) is int and 1 <= p['house'] <= 12
                                for p in positions.values()))
    for rule in rules:
        missing = set(rule['required_aspects']) - MINOR_ORBS.keys() - enabled
        status, reason = 'evaluated', None
        if missing:
            excluded = major_available and not missing.intersection(settings['aspects'])
            status = 'excluded' if excluded else 'unavailable'
            reason = 'saved_aspect_settings' if excluded else 'missing_saved_aspects'
        if rule['kind'] == 'house_stellium' and not houses_available:
            status, reason = 'unavailable', 'unavailable_houses'
        rule.update(status=status, reason=reason)
    by_kind = {rule['kind']: rule for rule in rules}
    patterns = []

    def add(kind, members, edges=(), apex=None, facts=None, geometry='aspects', house=None):
        members, edges = sorted(members), sorted(edges)
        if by_kind[kind]['status'] != 'evaluated':
            return
        identity = '|'.join((chart['id'], RULE_VERSION, kind, *(edges or members)))
        patterns.append({'id': identity, 'kind': kind, 'name': by_kind[kind]['name'],
                         'definition': by_kind[kind]['definition'], 'aliases': by_kind[kind]['aliases'], 'members': members,
                         'edges': edges, 'apex': apex, 'contained_by': [],
                         'facts': facts or {}, 'geometry': geometry, 'house': house})
        by_kind[kind]['matches'] += 1

    aspect_patterns(evidence, add)
    distribution = position_patterns(positions, houses_available, add)
    for pattern in patterns:
        if not pattern['edges']:
            continue
        required = set(pattern['edges'])
        pattern['contained_by'] = sorted(parent['id'] for parent in patterns
                                         if required < set(parent['edges']))
    return {**result, 'status': 'supported', 'patterns': sorted(patterns, key=lambda p: p['id']),
            'evidence': [evidence[key] for key in sorted(evidence)], 'distribution': distribution}
