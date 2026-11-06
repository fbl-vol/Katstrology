"""Read-only pattern projection of saved natal facts, never canonical evidence."""

from itertools import combinations
from math import isfinite


RULE_VERSION = 'natal-patterns-v1'
MEMBERS = frozenset(('sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter',
                     'saturn', 'uranus', 'neptune', 'pluto'))


def edge_id(first, second, kind):
    return ':'.join((kind, *sorted((first, second))))


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def explore_chart(chart):
    """Use only the stored qualified graph and its own saved settings.

    A missing edge stays missing. House failure does not invalidate planet
    aspects. Identities are independent of aspect ordering and pair direction.
    """
    result = {'chart_id': chart['id'], 'rule_version': RULE_VERSION,
              'source_status': chart['source_status'], 'status': 'unavailable',
              'reason': None, 'patterns': []}
    if chart['source_status'] != 'current':
        return {**result, 'reason': 'historical_source'}
    saved = chart['result']
    natal = saved.get('natal')
    if not natal:
        return {**result, 'reason': 'legacy_chart'}
    if natal.get('status') not in ('complete', 'partial_unsupported_houses'):
        return {**result, 'reason': natal.get('status', 'unusable_facts')}
    settings = saved.get('profile', {}).get('settings', {})
    positions = natal.get('positions', [])
    aspects = natal.get('aspects')
    present = {p['id'] for p in positions if _number(p.get('longitude_degrees'))
               and 0 <= p['longitude_degrees'] < 360}
    if (not MEMBERS <= present or not isinstance(aspects, list)
            or not isinstance(settings.get('orbs'), dict)
            or not isinstance(settings.get('aspects'), list)):
        return {**result, 'reason': 'unusable_facts'}
    edges = set()
    for aspect in aspects:
        first, second, kind = (aspect.get(key) for key in ('first', 'second', 'kind'))
        if first not in MEMBERS or second not in MEMBERS or first == second:
            continue
        orb, limit = aspect.get('orb_degrees'), settings['orbs'].get(kind)
        if (kind in settings['aspects'] and _number(orb) and _number(limit)
                and 0 <= orb <= limit):
            edges.add(edge_id(first, second, kind))

    patterns = []

    def add(kind, members, required, apex=None):
        if not set(required) <= edges:
            return
        identity = '|'.join((chart['id'], RULE_VERSION, kind, *sorted(required)))
        patterns.append({'id': identity, 'kind': kind, 'members': sorted(members),
                         'edges': sorted(required), 'apex': apex, 'contained_by': []})

    for triple in combinations(sorted(MEMBERS), 3):
        add('grand_trine', triple, [edge_id(a, b, 'trine') for a, b in combinations(triple, 2)])
        for apex in triple:
            a, b = [body for body in triple if body != apex]
            add('t_square', triple, [edge_id(a, b, 'opposition'),
                                    edge_id(a, apex, 'square'), edge_id(b, apex, 'square')], apex)
    for quartet in combinations(sorted(MEMBERS), 4):
        first, *others = quartet
        for opposite in others:
            a, b = [body for body in others if body != opposite]
            add('grand_cross', quartet, [edge_id(first, opposite, 'opposition'),
                edge_id(a, b, 'opposition'), *[edge_id(x, y, 'square')
                    for x in (first, opposite) for y in (a, b)]])
    crosses = [pattern for pattern in patterns if pattern['kind'] == 'grand_cross']
    for pattern in patterns:
        if pattern['kind'] == 't_square':
            pattern['contained_by'] = sorted(parent['id'] for parent in crosses
                if set(pattern['members']) <= set(parent['members'])
                and set(pattern['edges']) <= set(parent['edges']))
    return {**result, 'status': 'supported', 'patterns': sorted(patterns, key=lambda p: p['id'])}
