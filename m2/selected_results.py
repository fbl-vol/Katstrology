"""Owner-fenced, small immutable saved-result evidence for a selected message.

The archive keeps the exact source identity and crossing. Large wheel/point arrays
stay in their original saved result, never silently dumped into model context.
"""

import json


FIELDS = ('instant_utc', 'effective_utc', 'phase', 'pass_direction', 'body',
          'branch', 'aspect', 'transit_body', 'natal_target', 'longitude_degrees',
          'natal_longitude_degrees', 'angular_residual_degrees')


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
    result = row['result']
    index = row['event_index']
    event = result.get('events', [])[index] if index is not None else result
    facts = {key: event[key] for key in FIELDS if key in event and
             isinstance(event[key], (str, int, float))}
    selected = {'result_id': row['result_id'], 'event_index': index,
                'technique': row['technique'], 'method_version': row['method_version'],
                'source_chart_ids': [item for item in (row['chart_a_id'], row['chart_b_id']) if item],
                'source_status_at_ack': row['source_status_at_ack'],
                'window_utc': result.get('window_utc'), 'status': result.get('status'),
                'facts': facts}
    # Bounded model evidence, not a claim that the assistant's interpretation
    # follows from these facts. Source text is lower trust than instructions.
    if len(json.dumps(selected, ensure_ascii=False).encode('utf-8')) > 4096:
        raise ValueError('Selected saved result evidence exceeds bounded context')
    return selected
