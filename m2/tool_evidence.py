"""Finite model evidence and separately bounded authoritative tool-result events.

Model-directed reads have no conversational count ceiling. Distinct byte and
context bounds still apply: 32 KiB of aggregate model evidence, 16 KiB per read,
and a separately bounded authoritative archive. Other archive events retain
their existing 16-KiB ceiling.
"""

import json
from hashlib import sha256

from m2.agent_reads import project_transit_view
from m2.store import MAX_EVENT_BYTES, MAX_TOOL_RESULT_BYTES

MAX_MODEL_RESULT_BYTES = MAX_EVENT_BYTES
# At most two full projections per operation; later reads receive an explicit
# incomplete result when the evidence budget cannot fit their content.
MAX_MODEL_EVIDENCE_BYTES = MAX_MODEL_RESULT_BYTES * 2
MAX_TOOL_ARCHIVE_BYTES = MAX_TOOL_RESULT_BYTES
ARCHIVE_ENVELOPE_RESERVE = 2048  # hashes, pointer links and projection labels
LIMIT_RESPONSE_RESERVE = 512  # one honest limit result must fit after earlier reads


def encoded(value):
    return json.dumps(value, default=str, ensure_ascii=False).encode('utf-8')


def project(name, result, available_bytes=MAX_MODEL_RESULT_BYTES):
    """Preserve identifying qualifications; mark every model-only reduction."""
    if name == 'get_true_solar_arc' and result.get('status') == 'supported':
        projection = {key: value for key, value in result.items() if key not in
                      ('positions', 'natal_positions', 'directed_natal_aspects')}
        projection['positions'] = result['positions']
        projection['natal_positions'] = result['natal_positions']
        projection['directed_natal_aspects'] = result['directed_natal_aspects'][:12]
        projection['directed_natal_aspects_shown'] = len(projection['directed_natal_aspects'])
        projection['model_projection_note'] = 'First 12 aspects and total count; complete saved solar-arc geometry remains archived.'
        return projection, True
    if name == 'get_uncorrected_davison' and result.get('status') == 'supported':
        natal = result['derived_natal']
        projected = {**result, 'derived_natal': {
            'status': natal['status'], 'instant_utc': natal['instant_utc'],
            'positions': [{'id': item['id'], 'longitude_degrees': round(item['longitude_degrees'], 5),
                           'house': item['house']} for item in natal['positions']],
            'houses': natal['houses'], 'aspects': natal['aspects'][:12],
            'aspects_total': len(natal['aspects']), 'aspects_shown': min(12, len(natal['aspects'])),
            'ephemeris_sha256': natal['ephemeris_sha256'],
            'method_version': natal['method_version'],
            **({'lilith_convention': natal['lilith_convention'],
                'lilith_method': natal['lilith_method']} if natal.get('lilith_convention') else {})},
            'model_projection_note': 'Rounded derived positions and first 12 aspects; full qualified synthetic chart is archived.'}
        return projected, True
    if name == 'get_secondary_progression' and result.get('status') == 'supported':
        projected = {key: value for key, value in result.items()
                     if key not in ('positions', 'natal_positions', 'natal_aspects',
                                    'mcp_contacts', 'mcr_contacts')}
        projected['positions'] = [
            {'id': point['id'], 'longitude_degrees': round(point['longitude_degrees'], 5)}
            for point in result['positions']]
        projected['natal_positions'] = result['natal_positions']
        for key in ('natal_aspects', 'mcp_contacts', 'mcr_contacts'):
            projected[key] = result[key][:12]
            projected[f'{key}_shown'] = len(projected[key])
            projected[f'{key}_total'] = (result['natal_aspects_total'] if key == 'natal_aspects'
                                         else len(result[key]))
        projected['model_projection_note'] = 'Positions rounded for model; contact lists capped at 12 per branch with totals. Full qualified result is archived.'
        return projected, True
    if name in ('get_solar_return', 'get_lunar_returns', 'get_planetary_returns') and result.get('status') == 'supported':
        projected = {key: value for key, value in result.items() if key != 'events'}
        projected['events'] = [{
            'instant_utc': event['instant_utc'],
            'angular_residual_degrees': event['angular_residual_degrees'],
            **({'pass_direction': event['pass_direction'],
                'speed_degrees_per_day': event['speed_degrees_per_day']}
               if name == 'get_planetary_returns' else {}),
            'positions': [{'id': point['id'], 'longitude_degrees': round(point['longitude_degrees'], 5)}
                          for point in event['chart']['positions'] if point['id'] != 'south_node'],
            'house_status': event['chart']['houses']['status'],
            'angles': event['chart']['houses']['angles'],
        } for event in result['events'][:4]]
        projected['events_total'] = len(result['events'])
        projected['events_shown'] = len(projected['events'])
        projected['model_projection_note'] = 'Rounded positions and selected angles; at most four passes shown with total. The archived charts retain all bodies and houses; planetary-return aspects are explicitly truncated to eight with a total.'
        return projected, True
    if name == 'get_transit_view' and 'error' not in result:
        projected = project_transit_view(result)
        while len(encoded(projected)) > available_bytes and (
                projected['same_sky_aspects'] or projected['transit_to_natal_aspects']):
            largest = max(('same_sky_aspects', 'transit_to_natal_aspects'),
                          key=lambda key: len(encoded(projected[key])))
            if not projected[largest]:
                largest = ('transit_to_natal_aspects' if largest == 'same_sky_aspects'
                           else 'same_sky_aspects')
            projected[largest].pop()
            projected[largest.replace('aspects', 'shown')] = len(projected[largest])
        return projected, True
    if name == 'get_conversation_messages' and 'turns' in result:
        if len(encoded(result)) <= available_bytes:
            return result, False
        projected = {**result, 'turns': [dict(turn) for turn in result['turns']],
            'model_projection_note': 'Current-branch turn text shortened for model; '
                                     'full bounded read is archived. This is not all history.'}
        while len(encoded(projected)) > available_bytes:
            candidates = [turn for turn in projected['turns'] if len(turn['text']) > 100]
            if not candidates:
                break
            turn = max(candidates, key=lambda item: len(encoded(item['text'])))
            turn['text'] = turn['text'][:-50]
            turn['model_text_shortened'] = True
            turn['model_characters_shown'] = len(turn['text'])
        return projected, True
    if name == 'search_references' and 'results' in result:
        fields = ('kind', 'source_id', 'passage_id', 'conversation_id', 'speaker',
                  'author', 'title', 'edition', 'tradition', 'technique', 'language',
                  'rights_basis', 'approval', 'source_kind', 'keyword_match', 'score',
                  'ordinal', 'page_start', 'page_end', 'printed_page_start',
                  'printed_page_end', 'source_locator_start', 'source_locator_end',
                  'parent_section', 'review_status',
                  'excerpt')
        projected = {**result, 'results': [
            {key: row[key] for key in fields if key in row}
            for row in result['results']]}
        projected['model_projection_note'] = (
            'Source IDs, rights and attribution retained; omitted search metadata '
            'and any shortened fields remain in the archived full result. '
            'Search is bounded and may omit other candidates.')
        if len(encoded(projected)) > available_bytes:
            for row in projected['results']:
                for key in ('author', 'title', 'edition', 'tradition', 'technique'):
                    if isinstance(row.get(key), str) and len(row[key]) > 128:
                        row[key] = row[key][:128]
                        row['model_metadata_shortened'] = True
        while len(encoded(projected)) > available_bytes:
            candidates = [row for row in projected['results'] if len(row.get('excerpt', '')) > 40]
            if not candidates:
                break
            row = max(candidates, key=lambda item: len(encoded(item['excerpt'])))
            row['excerpt'] = row['excerpt'][:-40]
            row['model_excerpt_shortened'] = True
        return projected, True
    if name == 'get_reference_passage' and 'content' in result:
        projected = dict(result)
        if len(encoded(projected)) > available_bytes:
            projected.update({'model_content_shortened': True,
                              'model_projection_note': 'Passage shortened for model; '
                              'resume at next_offset. Full read remains in the turn archive.'})
            while len(encoded(projected)) > available_bytes and projected['content']:
                projected['content'] = projected['content'][:-80]
            if not projected['content'] and result['content']:
                # A zero-progress success would strand the unread remainder.
                # Leave the oversized result for prepare() to refuse honestly.
                return result, False
            projected['model_content_characters_shown'] = len(projected['content'])
            projected['next_offset'] = (result['offset'] + len(projected['content'])
                                        if result['offset'] + len(projected['content']) < result['total_characters']
                                        else None)
            projected['truncated'] = projected['next_offset'] is not None
        return projected, projected != result
    return result, False


def prepare(name, call_id, result, round_count, prior_bytes, model, budget):
    """Return an archived owner result and one bounded, honest provider output."""
    archived = {'id': call_id, 'name': name, 'result': result}
    if name in ('get_chart', 'get_transit_view', 'get_transit_snapshot',
                'find_transit_events', 'find_sky_events', 'get_solar_return',
                'get_lunar_returns', 'find_natal_mc_transits',
                'get_secondary_progression', 'find_progressed_mc_contacts',
                'get_true_solar_arc', 'find_progressed_lunar_phases',
                'find_actual_lunations_eclipses', 'get_planetary_returns') and result.get('chart_id'):
        archived['chart_id'] = result['chart_id']
    if name in ('get_midpoint_composite', 'get_uncorrected_davison') and result.get('chart_a_id'):
        archived['chart_id'] = result['chart_a_id']
        archived['chart_b_id'] = result['chart_b_id']
    if name == 'search_references':
        archived['results'] = result.get('results', [])
    if name == 'get_reference_passage' and 'passage_id' in result:
        archived['results'] = [{'kind': 'reference_passage',
            'source_id': result['source_id'], 'passage_id': result['passage_id']}]
    archive_bytes = len(str(archived).encode('utf-8'))
    scope, used, limit = None, archive_bytes, MAX_TOOL_ARCHIVE_BYTES - ARCHIVE_ENVELOPE_RESERVE
    if archive_bytes > limit:
        scope = 'archive'
        archived = {'id': call_id, 'name': name,
                    'result': limit_result(scope, used, limit, round_count)}

    remaining = MAX_MODEL_EVIDENCE_BYTES - LIMIT_RESPONSE_RESERVE - prior_bytes
    projection, reduced = project(name, archived['result'],
                                  max(0, min(MAX_MODEL_RESULT_BYTES, remaining)))
    projection_bytes = len(encoded(projection))
    if scope is None and projection_bytes > MAX_MODEL_RESULT_BYTES:
        scope, used, limit = 'per_call', projection_bytes, MAX_MODEL_RESULT_BYTES
    if scope is None and projection_bytes > remaining:
        scope, used, limit = ('cumulative', prior_bytes + projection_bytes,
                              MAX_MODEL_EVIDENCE_BYTES - LIMIT_RESPONSE_RESERVE)
    if scope is None and model is not None and getattr(model, 'capacity', None):
        estimated = model.estimate_read_continuation([{
            'type': 'function_call_output', 'call_id': call_id,
            'output': encoded(projection).decode('utf-8')}]) + budget['reply_reserve']
        if estimated > budget['context_limit']:
            scope, used, limit = 'model_context', estimated, budget['context_limit']
    if scope:
        projection = limit_result(scope, used, limit, round_count)
        reduced = True
    output = encoded(projection)
    if prior_bytes + len(output) > MAX_MODEL_EVIDENCE_BYTES:
        # The native result remains authoritative, but even the small refusal
        # cannot fit this operation's model-evidence envelope. Do not send an
        # unmatched call to the provider or mislabel a byte guard as a round cap.
        archived.update({'model_projection_status': 'unavailable',
            'model_projection_limit': {'scope': 'cumulative',
                'used_bytes': prior_bytes + len(output),
                'limit_bytes': MAX_MODEL_EVIDENCE_BYTES,
                'read_count': round_count, 'projected': True}})
        return archived, None
    archived.update({'model_projection_sha256': sha256(output).hexdigest(),
                     'model_projection_bytes': len(output),
                     'model_projection_status': 'limit' if scope else 'bounded' if reduced else 'full'})
    if scope:
        archived['model_projection_limit'] = {'scope': scope, 'used_bytes': used,
            'limit_bytes': limit, 'read_count': round_count, 'projected': reduced}
    return archived, output.decode('utf-8')


def limit_result(scope, used, limit, count):
    """A tool output, not a success-shaped excerpt or a second tool request."""
    return {'error': 'bounded_tool_result_unavailable', 'scope': scope,
            'used_bytes': used, 'limit_bytes': limit, 'read_count': count,
            'complete': False, 'reason': 'Result cannot be presented in this turn; '
            'do not infer absence or claim an exhaustive read. Report this limitation.'}
