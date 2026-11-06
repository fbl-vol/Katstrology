"""Worked saved-graph examples; no ephemeris or inferred missing edges."""

from copy import deepcopy
import unittest

from m2.calculation.exploration import MEMBERS, explore_chart
from m2.calculation.natal import _aspects
from tests.calculation.test_natal import SETTINGS


def saved_chart(degrees, settings=None):
    settings = deepcopy(settings or SETTINGS)
    points = [{'id': name, 'longitude_degrees': degree} for name, degree in degrees.items()]
    # Remaining members have established positions but intentionally no edges.
    positions = points + [{'id': name, 'longitude_degrees': 17}
                          for name in sorted(MEMBERS - degrees.keys())]
    return {'id': 'saved', 'source_status': 'current', 'result': {
        'profile': {'settings': settings}, 'natal': {
            'status': 'complete', 'positions': positions, 'aspects': _aspects(points, settings)}}}


class PatternTests(unittest.TestCase):
    def test_cross_has_four_children_and_stable_typed_identities(self):
        chart = saved_chart({'sun': 0, 'moon': 90, 'mars': 180, 'saturn': 270})
        before = deepcopy(chart)
        result = explore_chart(chart)
        cross, = [p for p in result['patterns'] if p['kind'] == 'grand_cross']
        children = [p for p in result['patterns'] if p['kind'] == 't_square']
        self.assertEqual(len(result['patterns']), 5)
        self.assertEqual({p['apex'] for p in children}, {'sun', 'moon', 'mars', 'saturn'})
        self.assertTrue(all(p['contained_by'] == [cross['id']] for p in children))
        self.assertEqual(chart, before)
        aspects = chart['result']['natal']['aspects']
        chart['result']['natal']['aspects'] = [
            {**a, 'first': a['second'], 'second': a['first']} for a in reversed(aspects)] + aspects
        self.assertEqual(explore_chart(chart), result)
        chart['result']['natal']['aspects'] = [a for a in aspects if not (
            a['kind'] == 'opposition' and {a['first'], a['second']} == {'sun', 'mars'})]
        self.assertEqual([p['kind'] for p in explore_chart(chart)['patterns']], ['t_square', 't_square'])

    def test_shared_child_keeps_every_parent(self):
        chart = saved_chart({'sun': 0, 'moon': 90, 'mars': 180, 'saturn': 270, 'jupiter': 271})
        patterns = explore_chart(chart)['patterns']
        child, = [p for p in patterns if p['kind'] == 't_square'
                  and set(p['members']) == {'sun', 'moon', 'mars'}]
        self.assertEqual(len(child['contained_by']), 2)
        self.assertEqual(len([p for p in patterns if p['kind'] == 'grand_cross']), 2)

    def test_wrap_out_of_sign_and_saved_orb_boundary(self):
        # 359/119/239 is exact; 359/121/239 crosses sign/element boundaries.
        for moon, orb, expected in ((119, 1, 1), (121, 2.001, 1), (121, 1.999, 0)):
            settings = {**SETTINGS, 'aspects': ['trine'], 'orbs': {'trine': orb}}
            chart = saved_chart({'sun': 359, 'moon': moon, 'mars': 239}, settings)
            self.assertEqual(len(explore_chart(chart)['patterns']), expected)
        chart = saved_chart({'sun': 0, 'moon': 120, 'mars': 240})
        chart['result']['profile']['settings']['aspects'].remove('trine')
        self.assertEqual(explore_chart(chart)['patterns'], [])
        chart = saved_chart({'sun': 0, 'moon': 90.1, 'mars': 180})
        pattern, = explore_chart(chart)['patterns']
        self.assertEqual((pattern['kind'], pattern['apex']), ('t_square', 'moon'))

    def test_optional_points_cannot_manufacture_patterns(self):
        for point in ('north_node', 'south_node', 'chiron', 'lilith_mean', 'ascendant', 'midheaven'):
            chart = saved_chart({'sun': 0, 'moon': 120, point: 240})
            self.assertEqual(explore_chart(chart)['patterns'], [])

    def test_partial_zero_and_unavailable_are_distinct(self):
        chart = saved_chart({'sun': 0, 'moon': 120, 'mars': 240})
        chart['result']['natal']['status'] = 'partial_unsupported_houses'
        self.assertEqual(len(explore_chart(chart)['patterns']), 1)
        for status in ('superseded', 'abandoned_branch'):
            chart['source_status'] = status
            self.assertEqual(explore_chart(chart)['reason'], 'historical_source')
        chart['source_status'] = 'current'
        chart['result']['natal']['positions'] = []
        self.assertEqual(explore_chart(chart)['reason'], 'unusable_facts')
        chart['result']['natal']['status'] = 'unsupported_uncertain_birth_time'
        self.assertEqual(explore_chart(chart)['status'], 'unavailable')
        del chart['result']['natal']
        self.assertEqual(explore_chart(chart)['reason'], 'legacy_chart')
        self.assertEqual(explore_chart(saved_chart({}))['status'], 'supported')
