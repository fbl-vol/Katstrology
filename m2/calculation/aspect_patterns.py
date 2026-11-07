"""Match explicitly qualified aspect graphs without reinterpreting missing edges."""
from .pattern_catalogue import ASPECT_RULES, MEMBERS, edge_id, required_edges


def aspect_patterns(evidence, add):
    edges = set(evidence)
    for kind, _, degrees, apex, _, _ in ASPECT_RULES:
        required = required_edges(kind, degrees)
        assigned = []
        seen = set()

        def visit():
            index = len(assigned)
            if index == len(degrees):
                ids = tuple(sorted(edge_id(assigned[a], assigned[b], relation) for a, b, relation in required))
                if ids not in seen:
                    seen.add(ids)
                    add(kind, assigned, ids, apex=assigned[apex] if apex is not None else None)
                return
            for body in sorted(MEMBERS - set(assigned)):
                # Prune as soon as a required edge to an earlier role is missing.
                if all(edge_id(assigned[a], body, relation) in edges
                       for a, b, relation in required if b == index):
                    assigned.append(body)
                    visit()
                    assigned.pop()

        visit()

    remaining = set(MEMBERS)
    while remaining:
        component, pending = set(), [min(remaining)]
        while pending:
            body = pending.pop()
            if body in component:
                continue
            component.add(body)
            pending.extend(other for other in MEMBERS - component
                           if edge_id(body, other, 'conjunction') in edges)
        remaining -= component
        if len(component) >= 3:
            ids = [edge for edge in edges if edge.startswith('conjunction:')
                   and set(edge.split(':')[1:]) <= component]
            add('conjunction_stellium', component, ids, geometry='members')
