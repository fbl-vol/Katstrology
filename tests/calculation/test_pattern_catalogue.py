"""Independent worked geometry, compatibility and concentration/distribution cases."""
from copy import deepcopy
import json
import unittest

from m2.calculation.exploration import explore_chart
from tests.calculation.test_exploration import saved_chart

BODIES = ('sun', 'moon', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto', 'mercury', 'venus')
# Worked angle sets and expected edge counts, not imported from the rule table.
FIGURES = {
    'grand_trine': ([0, 120, 240], 3), 't_square': ([0, 90, 180], 3),
    'grand_cross': ([0, 90, 180, 270], 6), 'minor_grand_trine': ([0, 60, 120], 3),
    'wedge': ([0, 60, 180], 3), 'kite': ([0, 60, 120, 240], 6),
    'mystic_rectangle': ([0, 60, 180, 240], 6), 'cradle': ([0, 60, 120, 180], 6),
    'grand_sextile': ([0, 60, 120, 180, 240, 300], 15),
    'yod': ([0, 60, 210], 3), 'boomerang_yod': ([0, 60, 210, 30], 4),
    'thors_hammer': ([0, 90, 225], 3), 'golden_yod': ([0, 72, 216], 3),
    'quintile_triangle': ([0, 72, 144], 3), 'grand_quintile': ([0, 72, 144, 216, 288], 10),
}
SHAPES = {
    'bundle': [0, 10, 20, 30, 40, 50, 60, 70, 80, 120],
    'bowl': [0, 20, 40, 60, 80, 100, 120, 140, 160, 180],
    'bucket': [0, 20, 40, 60, 80, 100, 120, 140, 160, 260],
    'seesaw': [0, 20, 40, 60, 80, 180, 200, 220, 240, 260],
    'locomotive': [0, 27, 54, 81, 108, 135, 162, 189, 216, 240],
    'splay': [0, 10, 20, 120, 130, 140, 240, 250, 260, 270],
    'splash': [0, 36, 72, 108, 144, 180, 216, 252, 288, 324],
}


def figure(degrees):
    return saved_chart(dict(zip(BODIES, degrees)))


def matches(chart, kind, members=None):
    return [p for p in explore_chart(chart)['patterns'] if p['kind'] == kind
            and (members is None or set(p['members']) == set(members))]


class CatalogueTests(unittest.TestCase):
    def test_every_aspect_rule_has_positive_and_broken_required_leg(self):
        for kind, (degrees, count) in FIGURES.items():
            members = BODIES[:len(degrees)]
            with self.subTest(kind=kind):
                chart = figure(degrees)
                pattern, = matches(chart, kind, members)
                self.assertEqual(len(pattern['edges']), count)
                # Move a vertex far beyond either saved major or fixed minor orbs.
                broken = figure([degrees[0] + 19, *degrees[1:]])
                self.assertEqual(matches(broken, kind, members), [])
                rotated = figure([(value + 359) % 360 for value in degrees])
                self.assertEqual(matches(rotated, kind, members)[0]['id'], pattern['id'])

    def test_missing_major_edge_not_recovered_from_longitude(self):
        chart = figure([0, 60, 210])
        chart['result']['natal']['aspects'] = []
        self.assertEqual(matches(chart, 'yod', BODIES[:3]), [])
        self.assertTrue(any(e['kind'] == 'quincunx' for e in explore_chart(chart)['evidence']))

    def test_minor_boundaries_and_separate_provenance(self):
        for kind, base, apex, minor in [('yod', 60, 210, 'quincunx'),
                                       ('golden_yod', 72, 216, 'biquintile'),
                                       ('thors_hammer', 90, 225, 'sesquiquadrate')]:
            for deviation, expected in ((0, True), (2, True), (2.00001, False)):
                chart = figure([0, base, apex + deviation])
                before = json.dumps(chart, sort_keys=True)
                result = explore_chart(chart)
                self.assertEqual(bool(matches(chart, kind, BODIES[:3])), expected)
                self.assertEqual(json.dumps(chart, sort_keys=True), before)
                for edge in result['evidence']:
                    if edge['kind'] == minor:
                        self.assertEqual((edge['origin'], edge['limit_degrees']), ('derived', 2))
                self.assertNotIn(minor, chart['result']['profile']['settings']['aspects'])
        for deviation, expected in ((2, True), (2.00001, False)):
            self.assertEqual(bool(matches(figure([0, 72 + deviation, 144]),
                                          'quintile_triangle', BODIES[:3])), expected)

    def test_order_duplicates_optional_points_and_all_parents(self):
        chart = figure([0, 60, 120, 180, 240, 300])
        original = explore_chart(chart)
        before = deepcopy(chart)
        natal = chart['result']['natal']
        natal['positions'].reverse()
        natal['positions'].append({'id': 'chiron', 'longitude_degrees': 60})
        natal['aspects'] += [{**a, 'first': a['second'], 'second': a['first']}
                            for a in reversed(natal['aspects'])]
        self.assertEqual(explore_chart(chart), original)
        parent, = matches(before, 'grand_sextile', BODIES[:6])
        child, = matches(before, 'minor_grand_trine', BODIES[:3])
        self.assertIn(parent['id'], child['contained_by'])
        self.assertGreater(len(child['contained_by']), 1)
        # Optional point cannot replace the required third planet.
        chart = figure([0, 60, 210])
        for p in chart['result']['natal']['positions']:
            if p['id'] == 'mars':
                p['longitude_degrees'] = 11
        chart['result']['natal']['positions'].append({'id': 'north_node', 'longitude_degrees': 210})
        self.assertFalse(matches(chart, 'yod', BODIES[:3]))

    def test_each_distribution_and_rotation_with_no_false_polygons(self):
        for kind, degrees in SHAPES.items():
            with self.subTest(kind=kind):
                for rotation in (0, 137, 359):
                    chart = figure([(d + rotation) % 360 for d in degrees])
                    result = explore_chart(chart)
                    self.assertEqual(result['distribution']['kind'], kind)
                    pattern, = matches(chart, kind)
                    self.assertEqual(pattern['geometry'], 'distribution')
                    self.assertEqual(pattern['edges'], [])
                    self.assertEqual(len(pattern['facts']['gaps']), 10)
                # A separately worked contrasting layout must not get this label.
                other = SHAPES['splash' if kind != 'splash' else 'bundle']
                self.assertFalse(matches(figure(other), kind))

    def test_distribution_boundaries_and_mixed_not_forced_to_splay(self):
        for last, expected in ((120, 'bundle'), (120.001, 'bowl'), (180, 'bowl'), (180.001, None)):
            interior = [0, 10, 20, 30, 40, 60, 80, 100, 110] if last < 150 else [0, 20, 40, 60, 80, 100, 120, 140, 160]
            result = explore_chart(figure([*interior, last]))
            self.assertEqual(result['distribution']['kind'], expected)
        for last, expected in ((225, 'locomotive'), (224.999, None), (255, 'locomotive'), (255.001, None)):
            result = explore_chart(figure([0, 27, 54, 81, 108, 135, 162, 189, 216, last]))
            self.assertEqual(result['distribution']['kind'], expected)
        # One exactly 60-degree gap excludes strict Splash but is not a locomotive.
        result = explore_chart(figure([0, 60, 94, 128, 162, 196, 230, 264, 298, 332]))
        self.assertEqual(result['distribution']['status'], 'mixed')
        self.assertFalse(any(p['kind'] == 'splay' for p in result['patterns']))

    def test_stelliums_are_distinct_maximal_groups_and_need_reliable_houses(self):
        chart = figure([1, 15, 29, 75, 110, 145, 185, 225, 265, 305])
        sign, = matches(chart, 'sign_stellium')
        self.assertEqual(sign['members'], sorted(BODIES[:3]))
        self.assertFalse(matches(chart, 'conjunction_stellium'))
        self.assertFalse(matches(chart, 'house_stellium'))
        natal = chart['result']['natal']
        natal['houses'] = {'status': 'supported', 'cusps': [
            {'number': i + 1, 'longitude_degrees': i * 30} for i in range(12)]}
        for i, p in enumerate(natal['positions']):
            p['house'] = 1 if i < 3 else i + 1
        house, = matches(chart, 'house_stellium')
        self.assertEqual(house['house'], 1)
        cusp = natal['houses']['cusps'].pop()
        self.assertFalse(matches(chart, 'house_stellium'))
        natal['houses']['cusps'].append(cusp)
        natal['positions'][0]['house'] = None
        self.assertFalse(matches(chart, 'house_stellium'))
        chart = figure([359, 5, 11, 17])
        chart['result']['profile']['settings']['orbs']['conjunction'] = 6
        conjunction, = matches(chart, 'conjunction_stellium')
        self.assertEqual(conjunction['members'], sorted(BODIES[:4]))
        self.assertEqual(len(conjunction['edges']), 3)
        # Two bodies in a sign or conjunction do not meet the threshold.
        self.assertFalse(matches(figure([1, 7, 50, 85, 120, 155, 190, 225, 260, 305]), 'sign_stellium'))
        self.assertFalse(matches(figure([1, 7, 50, 85, 120, 155, 190, 225, 260, 305]), 'conjunction_stellium'))

    def test_concentration_threshold_near_misses(self):
        chart = figure([1, 15, 29, 75, 110, 145, 185, 225, 265, 305])
        self.assertTrue(matches(chart, 'sign_stellium'))
        chart['result']['natal']['positions'][2]['longitude_degrees'] = 30
        self.assertFalse(matches(chart, 'sign_stellium'))
        chart = figure([359, 5, 11, 17])
        chart['result']['profile']['settings']['orbs']['conjunction'] = 6
        self.assertTrue(matches(chart, 'conjunction_stellium'))
        chart['result']['natal']['aspects'] = [a for a in chart['result']['natal']['aspects']
                                             if {a['first'], a['second']} != {'moon', 'mars'}]
        self.assertFalse(matches(chart, 'conjunction_stellium'))
        chart = figure(SHAPES['splash'])
        natal = chart['result']['natal']
        natal['houses'] = {'status': 'supported', 'cusps': [
            {'number': i + 1, 'longitude_degrees': i * 30} for i in range(12)]}
        for i, position in enumerate(natal['positions']):
            position['house'] = 1 if i < 3 else i + 1
        self.assertTrue(matches(chart, 'house_stellium'))
        natal['positions'][2]['house'] = 3
        self.assertFalse(matches(chart, 'house_stellium'))

    def test_distribution_group_threshold_near_misses(self):
        # Moving the handle toward the group removes its 60-degree isolation.
        bucket = [0, 20, 40, 60, 80, 100, 120, 140, 160, 220]
        self.assertEqual(explore_chart(figure(bucket))['distribution']['kind'], 'bucket')
        bucket[-1] = 219.999
        self.assertNotEqual(explore_chart(figure(bucket))['distribution']['kind'], 'bucket')
        seesaw = [0, 20, 40, 60, 100, 160, 180, 200, 220, 240]
        self.assertEqual(explore_chart(figure(seesaw))['distribution']['kind'], 'seesaw')
        seesaw[5] = 159.999
        self.assertNotEqual(explore_chart(figure(seesaw))['distribution']['kind'], 'seesaw')
        splay = [0, 10, 60, 120, 130, 140, 240, 250, 260, 270]
        self.assertEqual(explore_chart(figure(splay))['distribution']['kind'], 'splay')
        splay[3] = 119.999
        self.assertNotEqual(explore_chart(figure(splay))['distribution']['kind'], 'splay')

    def test_family_availability_does_not_lie_about_unchecked_rules(self):
        chart = figure([0, 72, 216])
        chart['result']['profile']['settings'] = {}
        result = explore_chart(chart)
        self.assertEqual(result['status'], 'supported')
        rules = {r['kind']: r for r in result['catalogue']}
        self.assertEqual(rules['grand_trine']['status'], 'unavailable')
        self.assertEqual(rules['house_stellium']['status'], 'unavailable')
        self.assertEqual(rules['golden_yod']['status'], 'evaluated')
        self.assertEqual(rules['golden_yod']['matches'], 1)
        chart = figure([0, 60, 210])
        chart['result']['profile']['settings']['aspects'] = []
        rules = {r['kind']: r for r in explore_chart(chart)['catalogue']}
        self.assertEqual(rules['yod']['status'], 'excluded')
        chart['result']['profile']['settings']['aspects'] = ['sextile']
        del chart['result']['profile']['settings']['orbs']['sextile']
        rules = {r['kind']: r for r in explore_chart(chart)['catalogue']}
        self.assertEqual(rules['yod']['status'], 'unavailable')
        chart['result']['natal']['status'] = 'unsupported_uncertain_birth_time'
        result = explore_chart(chart)
        self.assertEqual(result['status'], 'unavailable')
        self.assertTrue(all(r['status'] == 'unavailable' for r in result['catalogue']))
        chart = figure([0, 60, 210])
        chart['result']['natal']['positions'].append({'id': 'sun', 'longitude_degrees': 20})
        self.assertEqual(explore_chart(chart)['reason'], 'unusable_facts')


if __name__ == '__main__':
    unittest.main()
