"""Explicit natal-pattern read policy, separate from canonical calculation settings.

Definitions: astro.com/astrowiki/en/Aspect_Figure; evolvingdoorastro.com/glossary/
terms/aspect-patterns/cradle; astrologyking.com/minor-grand-trine/;
augurine.com/learn/aspect-patterns/boomerang; roseglyph.com/tools/golden-yod/.
Distribution and concentration conventions: astrologist.com/learn/birth-charts/
chart-shapes-in-astrology and what-is-a-stellium. Numerical shape thresholds below
are Kat's strict operational variant, not universal astrological cutoffs.
"""
from itertools import combinations

RULE_VERSION = 'natal-patterns-v2'
MEMBERS = frozenset(('sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter',
                     'saturn', 'uranus', 'neptune', 'pluto'))
ANGLES = {0: 'conjunction', 60: 'sextile', 90: 'square', 120: 'trine',
          180: 'opposition', 150: 'quincunx', 135: 'sesquiquadrate',
          72: 'quintile', 144: 'biquintile'}
MINOR_ORBS = {kind: 2.0 for kind in ('quincunx', 'sesquiquadrate', 'quintile', 'biquintile')}


def edge_id(first, second, kind):
    return ':'.join((kind, *sorted((first, second))))


def separation(a, b):
    return abs((a - b + 180) % 360 - 180)


# Each ideal layout specifies every required pair, not merely an edge-count bag.
# Apex is a role index; only the Boomerang requires a non-complete graph.
ASPECT_RULES = (
    ('grand_trine', 'Grand Trine', (0, 120, 240), None,
     'Three trines connect three planets.', ()),
    ('t_square', 'T-square', (0, 90, 180), 1,
     'An opposition and two squares meet at the apex.', ()),
    ('grand_cross', 'Grand Cross', (0, 90, 180, 270), None,
     'Four squares and two oppositions connect four planets.', ('Grand Square',)),
    ('minor_grand_trine', 'Minor Grand Trine', (0, 60, 120), 1,
     'Two sextiles meet at the apex, with a trine across the base.', ('Small Talent Triangle',)),
    ('wedge', 'Wedge', (0, 60, 180), 1,
     'A third planet joins an opposition through a sextile and a trine.', ('Easy Opposition',)),
    ('kite', 'Kite', (0, 60, 120, 240), 1,
     'A Grand Trine with a fourth planet opposite one vertex and sextile the other two.', ()),
    ('mystic_rectangle', 'Mystic Rectangle', (0, 60, 180, 240), None,
     'Two oppositions, two trines and two sextiles connect four planets.', ()),
    ('cradle', 'Cradle', (0, 60, 120, 180), None,
     'Three sextiles, two trines and an opposition form two interlocking Wedges.', ()),
    ('grand_sextile', 'Grand Sextile', (0, 60, 120, 180, 240, 300), None,
     'Six sextiles, six trines and three oppositions connect six planets.', ('Star of David',)),
    ('yod', 'Yod', (0, 60, 210), 2,
     'A sextile base joins the apex through two quincunxes.', ('Finger of God',)),
    ('boomerang_yod', 'Boomerang Yod', (0, 60, 210, 30), 2,
     'A Yod with a fourth planet opposite its apex; semisextiles are not required.', ()),
    ('thors_hammer', "Thor’s Hammer", (0, 90, 225), 2,
     'A square base joins the apex through two sesquiquadrates.', ('Fist of God',)),
    ('golden_yod', 'Golden Yod', (0, 72, 216), 2,
     'A quintile base joins the apex through two biquintiles.', ()),
    ('quintile_triangle', 'Quintile Triangle', (0, 72, 144), 1,
     'Two quintiles and one biquintile, distinct from a Golden Yod.', ()),
    ('grand_quintile', 'Grand Quintile', (0, 72, 144, 216, 288), None,
     'Five quintiles and five biquintiles connect five planets.', ('Pentagram',)),
)


def required_edges(kind, degrees):
    pairs = ((0, 1), (0, 2), (1, 2), (2, 3)) if kind == 'boomerang_yod' else combinations(range(len(degrees)), 2)
    return tuple((a, b, ANGLES[separation(degrees[a], degrees[b])]) for a, b in pairs)


POSITION_RULES = (
    ('sign_stellium', 'Sign Stellium', 'Three or more of the ten planets and luminaries in one sign; no conjunction required.'),
    ('house_stellium', 'House Stellium', 'Three or more of the ten planets and luminaries in one reliably saved house.'),
    ('conjunction_stellium', 'Conjunction Stellium', 'A maximal connected chain of at least three planets linked by saved conjunctions; not necessarily all mutually conjunct.'),
    ('bundle', 'Bundle', 'All ten planets fit within an arc of 120° or less.'),
    ('bowl', 'Bowl', 'All ten planets span more than 120° and at most 180°.'),
    ('bucket', 'Bucket', 'Nine planets span at most 180°; a lone handle has gaps of at least 60° on both sides. Bundle and Bowl take precedence.'),
    ('seesaw', 'Seesaw', 'Exactly two gaps of at least 60° separate two groups, each with at least two planets; earlier concentrated shapes take precedence.'),
    ('locomotive', 'Locomotive', 'Exactly one gap is at least 60°, and that gap is 105° to 135°. Earlier shapes take precedence.'),
    ('splay', 'Splay', 'Strict tripod variant: three gaps of at least 60° separate three unequal-sized groups, each with at least two planets. Earlier shapes take precedence.'),
    ('splash', 'Splash', 'All ten planets are spread around the circle with every adjacent gap less than 60°.'),
)
SHAPES = frozenset(kind for kind, _, _ in POSITION_RULES[3:])


def catalogue():
    rules = [{'kind': kind, 'name': name, 'definition': definition, 'aliases': list(aliases),
              'family': 'aspects', 'required_aspects': sorted({edge[2] for edge in required_edges(kind, degrees)})}
             for kind, name, degrees, _, definition, aliases in ASPECT_RULES]
    rules += [{'kind': kind, 'name': name, 'definition': definition, 'aliases': [],
               'family': 'distribution' if kind in SHAPES else 'concentration',
               'required_aspects': ['conjunction'] if kind == 'conjunction_stellium' else []}
              for kind, name, definition in POSITION_RULES]
    return rules
