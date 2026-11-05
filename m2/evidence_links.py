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
