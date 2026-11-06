"""Coordinate the existing chart/event/reference command evidence links.

The gateway remains the only archive writer: every yielded call, result and
answer is committed and delivered in order. This module neither invokes a model
nor changes the external event envelope or source-qualification policy.
"""

from datetime import datetime

from m2.charts import Charts
from m2.evidence import LocalEmbedder, search_evidence
from m2.tool_answers import chart_answer, event_answer, reference_answer

CHART_PREFIX = 'saved chart '
EVENT_PREFIX = 'chart events '
REFERENCE_PREFIX = 'reference evidence '

# Existing model-read envelopes duplicate link identities outside `result` so the
# archive can index them without interpreting provider-specific result bodies.
SINGLE_CHART_READS = frozenset({
    'get_chart', 'get_transit_view', 'get_transit_snapshot',
    'find_transit_events', 'find_sky_events', 'get_solar_return',
    'get_lunar_returns', 'find_natal_mc_transits',
    'get_secondary_progression', 'find_progressed_mc_contacts',
    'get_true_solar_arc', 'find_progressed_lunar_phases',
    'find_actual_lunations_eclipses', 'get_planetary_returns',
})
PAIR_CHART_READS = frozenset({'get_midpoint_composite', 'get_uncorrected_davison'})


def project_read_links(name, result):
    """Preserve the historical top-level link envelope of a model-directed read."""
    if name in SINGLE_CHART_READS and result.get('chart_id'):
        return {'chart_id': result['chart_id']}
    if name in PAIR_CHART_READS and result.get('chart_a_id'):
        return {'chart_id': result['chart_a_id'], 'chart_b_id': result['chart_b_id']}
    if name == 'search_references':
        return {'results': result.get('results', [])}
    if name == 'get_reference_passage' and 'passage_id' in result:
        return {'results': [{'kind': 'reference_passage',
                            'source_id': result['source_id'], 'passage_id': result['passage_id']}]}
    return {}


def archived_links(payload):
    """Extract link identities from both original command and model-read envelopes.

    Store validates IDs/ownership and writes the returned links on its own
    connection inside the same event transaction. Do not infer links from
    arbitrary assistant text or from unsuccessful model-read arguments.
    """
    if not isinstance(payload, dict):
        return (), ()
    charts = []
    if 'chart_id' in payload:
        charts.append(payload['chart_id'])
    if payload.get('name') in PAIR_CHART_READS and 'chart_b_id' in payload:
        charts.append(payload['chart_b_id'])
    if (payload.get('name') == 'compare_selected_charts' and
            isinstance(payload.get('result'), dict) and
            'chart_a_id' in payload['result'] and 'chart_b_id' in payload['result']):
        charts.extend((payload['result']['chart_a_id'], payload['result']['chart_b_id']))
    passages = [(item['source_id'], item['passage_id'])
                for item in payload.get('results', [])
                if item.get('kind') == 'reference_passage']
    # One index entry per chart/passage per archived event, even when both the
    # historical nested comparison and its top-level link name the same chart.
    return tuple(dict.fromkeys(charts)), tuple(dict.fromkeys(passages))


def read_command_evidence(store, session, turn_id, request):
    """Yield historical command events; caller commits them before delivery."""
    if request.startswith((CHART_PREFIX, EVENT_PREFIX)):
        parts = request.split()
        chart_id = parts[2] if request.startswith(CHART_PREFIX) and len(parts) == 3 else (
            parts[2] if request.startswith(EVENT_PREFIX) and len(parts) == 5 else None)
        if chart_id is None:
            yield 'error', {'reason': 'invalid chart request syntax'}
            return
        name = 'get_chart' if request.startswith(CHART_PREFIX) else 'find_chart_events'
        yield 'tool_call', {'id': turn_id + ':chart', 'name': name,
                            'arguments': {'chart_id': chart_id}}
        try:
            charts = Charts(store)
            if name == 'get_chart':
                chart = charts.get_chart(session, chart_id)
                result = {'chart_id': chart_id, 'name': name,
                          'source_status': chart['source_status'],
                          'result': chart['result'] if chart['source_status'] == 'current'
                          else {'status': 'unsupported_stale_birth_source'}}
            else:
                result = charts.find_events(session, chart_id,
                                            datetime.fromisoformat(parts[3]),
                                            datetime.fromisoformat(parts[4]))
                result.update({'chart_id': chart_id, 'name': name})
        except (KeyError, ValueError) as exc:
            yield 'error', {'reason': type(exc).__name__, 'tool': name}
            return
        yield 'tool_result', result
        yield 'assistant_chunk', {'content': chart_answer(result) if name == 'get_chart'
                                  else event_answer(result)}
        yield 'complete', {}
    elif request.startswith(REFERENCE_PREFIX):
        query = request[len(REFERENCE_PREFIX):]
        if not 1 <= len(query) <= 256:
            yield 'error', {'reason': 'invalid bounded reference query'}
            return
        name = 'search_reference_and_history'
        yield 'tool_call', {'id': turn_id + ':reference', 'name': name,
                            'arguments': {'query': query, 'limit': 4}}
        result = search_evidence(store, session, query, LocalEmbedder(),
                                 limit=4, include_history=False)
        result['name'] = name
        yield 'tool_result', result
        yield 'assistant_chunk', {'content': reference_answer(result)}
        yield 'complete', {}
