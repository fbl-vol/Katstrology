"""Read immutable saved timing shapes without changing their original calculations.

The existing integer event_index is a stable locator: ordinary events retain their
original index; lunations use 0–499 and global eclipse maxima 500–999. The latter
are different physical instants and must never masquerade as syzygy events.
"""

from datetime import datetime

LUNATION = 'actual_lunations_eclipses'
ECLIPSE_OFFSET = 500


def source_event(technique, result, index):
    """Return (kind, original event) or reject an invalid immutable locator."""
    if index is None:
        return 'effective', result
    if type(index) is not int or not 0 <= index < 1000:
        raise ValueError('Invalid selected event index')
    if technique == LUNATION:
        kind, events, original_index = ('eclipse', result.get('eclipses', []), index - ECLIPSE_OFFSET) if index >= ECLIPSE_OFFSET else (
            'lunation', result.get('lunations', []), index)
    else:
        kind, events, original_index = 'event', result.get('events', []), index
    if not 0 <= original_index < len(events):
        raise ValueError('Selected point is not in the saved result')
    return kind, events[original_index]


def dated_points(technique, result):
    """One source-qualified point per supported effective date/crossing/maximum."""
    if technique == LUNATION:
        if len(result.get('lunations', [])) >= ECLIPSE_OFFSET or len(result.get('eclipses', [])) > ECLIPSE_OFFSET:
            raise ValueError('Saved lunation indices exceed locator capacity')
        locators = list(range(len(result.get('lunations', [])))) + [
            ECLIPSE_OFFSET + i for i in range(len(result.get('eclipses', [])))]
    elif 'events' in result:
        if len(result['events']) >= 1000:
            raise ValueError('Saved event indices exceed locator capacity')
        locators = list(range(len(result['events'])))
    else:
        locators = [None] if result.get('effective_utc') else []
    points = []
    for index in locators:
        kind, event = source_event(technique, result, index)
        instant = (event.get('maximum_utc') if kind == 'eclipse' else
                   event.get('instant_utc') or event.get('effective_utc'))
        if not instant:
            raise ValueError('Saved timing point is missing its effective instant')
        point = {'index': index, 'kind': kind, 'instant_utc': instant}
        for key in ('phase', 'family', 'eclipse_type', 'pass_direction', 'body', 'aspect',
                    'natal_target', 'branch', 'linked_syzygy_utc'):
            value = event.get(key, result.get(key))
            if isinstance(value, str):
                point[key] = value
        points.append(point)
    return sorted(points, key=lambda point: (point['instant_utc'], point['kind'], point['index'] or -1))


def points_in_period(technique, result, start, end):
    return [point for point in dated_points(technique, result)
            if start <= datetime.fromisoformat(point['instant_utc']) < end]
