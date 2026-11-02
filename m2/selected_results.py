"""Owner-fenced bounded facts for one explicitly selected immutable saved result."""

import json

from m2.saved_timing import source_event

ROOT_FACTS = ('body', 'transit_body_id', 'natal_body_id', 'branch', 'branch_description', 'aspect',
              'natal_target', 'natal_target_degrees', 'natal_longitude_degrees',
              'natal_mc_longitude_degrees', 'target_source_degrees', 'effective_utc',
              'mapped_ephemeris_utc', 'arc_degrees', 'natal_sun_degrees',
              'progressed_sun_degrees', 'age_completed_years', 'mc_status',
              'axis_status', 'phase_policy', 'arc_policy', 'pass_policy',
              'syzygy_policy', 'eclipse_policy')
EVENT_FACTS = ('instant_utc', 'maximum_utc', 'effective_utc', 'linked_syzygy_utc',
               'phase', 'family', 'eclipse_type', 'visibility', 'pass_direction',
               'longitude_degrees', 'target_degrees', 'angular_residual_degrees',
               'separation_degrees', 'sun_degrees', 'moon_degrees',
               'sun_degrees_at_maximum', 'moon_degrees_at_maximum',
               'mapped_ephemeris_utc', 'progressed_sun_degrees',
               'progressed_moon_degrees', 'natal_target', 'aspect', 'body')
PARAMETERS = ('body', 'branch', 'aspect', 'transit_body', 'natal_target',
              'latitude', 'longitude', 'reference_place_id')
POSITION_FACTS = ('id', 'longitude_degrees', 'source_longitude_degrees',
                  'speed_degrees_per_day', 'speed_degrees_per_symbolic_day')
CONTACT_FACTS = ('sky_body', 'longitude_degrees', 'natal_target',
                 'natal_longitude_degrees', 'aspect', 'orb_degrees', 'in_orb')


def _scalars(source, fields):
    return {key: source[key] for key in fields if isinstance(source.get(key), (str, int, float, bool))}


def selected_evidence(store, session, conversation_id, turn_id):
    owner = store.owner(session)
    store._conversation(owner, store._id(conversation_id))
    store._id(turn_id)
    row = store.db.execute('''
        SELECT s.result_id,s.event_index,s.chart_a_id,s.chart_b_id,
               s.source_status_at_ack,r.technique,r.method_version,r.parameters,r.result
        FROM turn_selected_results s JOIN advanced_results r
          ON r.owner_id=s.owner_id AND r.id=s.result_id
        WHERE s.owner_id=%s AND s.conversation_id=%s AND s.turn_id=%s
    ''', (owner, conversation_id, turn_id)).fetchone()
    if not row:
        return None

    result, index = row['result'], row['event_index']
    kind, event = source_event(row['technique'], result, index)
    facts = {**_scalars(result, ROOT_FACTS), **_scalars(event, EVENT_FACTS)}
    selected = {'result_id': row['result_id'], 'event_index': index,
                'point_kind': kind, 'technique': row['technique'],
                'method_version': row['method_version'],
                'source_chart_ids': [item for item in (row['chart_a_id'], row['chart_b_id']) if item],
                'source_status_at_ack': row['source_status_at_ack'],
                'window_utc': result.get('window_utc'), 'status': result.get('status'),
                'parameters': _scalars(row['parameters'], PARAMETERS), 'facts': facts}
    place = result.get('reference_place')
    if isinstance(place, dict):
        selected['reference_place'] = _scalars(place, ('latitude', 'longitude'))
    place_source = result.get('reference_place_source')
    if isinstance(place_source, dict):
        selected['reference_place_source'] = _scalars(place_source, ('kind', 'label'))
    for name in ('contacts', 'contacts_at_maximum'):
        if isinstance(event.get(name), list):
            selected[name] = [_scalars(item, CONTACT_FACTS) for item in event[name]]
    positions = event.get('chart', result) if isinstance(event.get('chart'), dict) else result
    if isinstance(positions.get('positions'), list):
        selected['positions_total'] = len(positions['positions'])
        selected['positions'] = [_scalars(item, POSITION_FACTS)
                                 for item in positions['positions']]
        selected['positions_complete'] = True

    # Reuse the existing bounded tool/text budget; never drop defining facts to fit.
    if len(json.dumps(selected, ensure_ascii=False).encode('utf-8')) > 64 * 1024:
        raise ValueError('Selected saved result evidence exceeds bounded context')
    return selected
