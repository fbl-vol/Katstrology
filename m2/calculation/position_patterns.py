"""Concentrations and whole-chart distributions are not aspect polygons."""
from collections import defaultdict


def position_patterns(positions, houses_available, add):
    for kind, field in (('sign_stellium', 'sign'), ('house_stellium', 'house')):
        if field == 'house' and not houses_available:
            continue
        groups = defaultdict(list)
        for body, position in positions.items():
            group = int(position['longitude_degrees'] // 30) if field == 'sign' else position['house']
            groups[group].append(body)
        for group, members in sorted(groups.items()):
            if len(members) >= 3:
                add(kind, members, facts={field: group, 'count': len(members)},
                    geometry='members', house=group if field == 'house' else None)

    ordered = sorted(positions, key=lambda body: (positions[body]['longitude_degrees'], body))
    degrees = [positions[body]['longitude_degrees'] for body in ordered]
    gaps = [degrees[i + 1] - degrees[i] for i in range(9)] + [degrees[0] + 360 - degrees[-1]]
    span = 360 - max(gaps)
    cuts = [i for i, gap in enumerate(gaps) if gap >= 60]
    groups = []
    for start, end in zip(cuts, cuts[1:] + cuts[:1]):
        size = (end - start) % 10 or 10
        groups.append([ordered[(start + step) % 10] for step in range(1, size + 1)])
    facts = {'occupied_arc_degrees': span,
             'gaps': [{'first': ordered[i], 'second': ordered[(i + 1) % 10], 'degrees': gap}
                      for i, gap in enumerate(gaps)],
             'groups': groups}
    kind, handle = None, None
    if span <= 120:
        kind = 'bundle'
    elif span <= 180:
        kind = 'bowl'
    else:
        for i, body in enumerate(ordered):
            before, after = gaps[(i - 1) % 10], gaps[i]
            if before >= 60 and after >= 60 and 360 - before - after <= 180:
                kind, handle = 'bucket', body
                break
        if kind is None:
            if len(groups) == 2 and min(map(len, groups)) >= 2:
                kind = 'seesaw'
            elif len(cuts) == 1 and 105 <= max(gaps) <= 135:
                kind = 'locomotive'
            elif len(groups) == 3 and min(map(len, groups)) >= 2:
                kind = 'splay'
            elif not cuts:
                kind = 'splash'
    if kind:
        add(kind, ordered, facts={**facts, 'handle': handle}, geometry='distribution')
    return {'status': 'matched' if kind else 'mixed', 'kind': kind, **facts}
