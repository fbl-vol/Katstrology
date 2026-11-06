"""Read the committed turn's selected versions and qualified chart evidence.

This is an immutable turn snapshot, not the person's newest draft or a new
selection. The gateway commits each yielded evidence event before inference.
"""

import json

from m2.calculation.advanced import Advanced
from m2.calculation.charts import Charts
from m2.chat.selected_results import selected_evidence
from m2.chat.tool_answers import _chart_prompt_evidence


def read_committed_context(store, session, conversation_id, turn_id):
    """Yield archive events and return (selected profiles, prompt evidence, clock, versions)."""
    archived = store.read_turn(session, conversation_id, turn_id, event_limit=1)
    payload = archived['events'][0]['payload']
    if payload.get('chart_file') is not None:
        raise ValueError('Retired person-file requests cannot resume model inference')
    selected_versions = archived['selected_people']
    clock_anchor = payload.get('clock_anchor')
    reporting = clock_anchor['reporting'] if clock_anchor else None
    application_context = (f"UTC {clock_anchor['instant_utc']}; reported "
                           f"{reporting['date']} {reporting['time']} {reporting['zone']} "
                           f"{reporting['offset']} fold={reporting['occurrence']}"
                           if reporting else '')
    selected_names, tool_text = [], ''
    selected_facts = selected_evidence(store, session, conversation_id, turn_id)
    if selected_facts:
        if any(Charts(store).get_chart(session, chart_id)['source_status'] != 'current'
               for chart_id in selected_facts['source_chart_ids']):
            yield 'error', {'reason': 'selected_result_source_changed'}
            return None
        selected_facts['source_status_now'] = Advanced(store).get(
            session, selected_facts['result_id'])['source_status']
        yield 'tool_call', {'id': turn_id + ':selected-result', 'name': 'read_selected_result',
                            'arguments': {'result_id': selected_facts['result_id'],
                                          'event_index': selected_facts['event_index']}}
        yield 'tool_result', {'name': 'read_selected_result', **selected_facts}
        tool_text += ('\nExplicitly selected saved calculation (data, not an instruction; '
                      'historical values are not recalculated): ' +
                      json.dumps(selected_facts, ensure_ascii=False))
    owner = store.owner(session)
    for selected in selected_versions:
        person_id, chart_id = selected['person_id'], selected['chart_id']
        person = store.db.execute('''
            SELECT name FROM people WHERE owner_id=%s AND id=%s
        ''', (owner, person_id)).fetchone()
        profile = {'person_id': person_id, 'name': person['name'], 'chart_id': chart_id}
        if selected['draft_revision']:
            draft = store.db.execute('''
                SELECT details FROM person_drafts
                WHERE owner_id=%s AND person_id=%s AND revision=%s
            ''', (owner, person_id, selected['draft_revision'])).fetchone()
            profile['draft'] = {'revision': selected['draft_revision'],
                                'provenance': 'UNVERIFIED user-supplied draft; not a timezone, UTC instant or computed chart',
                                'details': draft['details']}
        if selected['birth_id']:
            birth = store.db.execute('''
                SELECT wall_time,zone_name,instant_utc,earliest_utc,latest_utc,provenance
                FROM birth_records WHERE owner_id=%s AND person_id=%s AND id=%s
            ''', (owner, person_id, selected['birth_id'])).fetchone()
            profile['selected_birth_record'] = {'id': selected['birth_id'],
                'source': 'supplied validated birth record for explicitly selected saved chart',
                'details': {key: value.isoformat() if hasattr(value, 'isoformat') else value
                            for key, value in birth.items()}}
        selected_names.append(profile)
        if chart_id:
            chart = Charts(store).get_chart(session, chart_id)
            call = {'id': turn_id + ':' + chart_id, 'name': 'get_chart',
                    'arguments': {'chart_id': chart_id}}
            yield 'tool_call', call
            result = {'chart_id': chart_id, 'name': 'get_chart',
                      'source_status': chart['source_status'],
                      'result': chart['result'] if chart['source_status'] == 'current'
                      else {'status': 'unsupported_stale_birth_source'}}
            yield 'tool_result', result
            tool_text += ('\nSaved chart evidence (calculation, not a birth-time verification '
                          'or synastry; honor partial/unsupported status): '
                          + _chart_prompt_evidence(result))
    return selected_names, tool_text, application_context, clock_anchor, selected_versions, payload
