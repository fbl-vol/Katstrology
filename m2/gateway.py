"""Backend-owned local turn boundary; user input, tool evidence and output commit first."""

from datetime import datetime
import json

import swisseph as swe

from m2.app_clock import utc_now
from m2.charts import Charts
from m2.agent_reads import TOOLS, execute as execute_read
from m2.tool_evidence import (MAX_MODEL_EVIDENCE_BYTES,
                              prepare as prepare_read_evidence)
from m2.compaction import CompactionFailure, prepare as prepare_compaction
from m2.attachments import Attachments
from m2.evidence import LocalEmbedder, search_evidence
from m2.recall import CONTEXT_TOKENS, REPLY_RESERVE, PromptBudgetError, assemble_prompt
from m2.prompting import HOSTED, LOCAL, identity
from m2.provider_steps import ProviderFlush, ProviderStep
from m2.tool_answers import _chart_prompt_evidence, chart_answer, event_answer, reference_answer
from m2.selected_results import selected_evidence
from m2.core_calc import solar_longitude


TOOL_PREFIX = 'solar longitude at '
CHART_PREFIX = 'saved chart '
EVENT_PREFIX = 'chart events '
REFERENCE_PREFIX = 'reference evidence '
DEFAULT_PARENT = '@active'
# Fallback for test doubles; real hosted models resolve capacity before assembly.
HOSTED_REPLY_TOKENS = 384


def _event_text_chunks(text, max_bytes=8192):
    """Keep each durable reply event under the independent generic event limit."""
    start, used = 0, 0
    for index, char in enumerate(text):
        size = len(char.encode('utf-8'))
        if used + size > max_bytes:
            yield text[start:index]
            start, used = index, 0
        used += size
    if start < len(text):
        yield text[start:]


def turn_steps(store, session, conversation_id, turn_id, request, model, deliver,
             parent_id=DEFAULT_PARENT, attachment_ids=(), cancel_after=None,
             revision_kind='normal', replaces_turn_id=None, acknowledge=None,
             selected_people=(), cancelled=None, model_provider='local', model_slug=None,
             chart_file=None, clock=utc_now, reporting_zone=None,
             interpret_commands=True, defer_provider=False, selected_result=None):
    """deliver(event) receives only committed, user-visible events.

    Retries return stored events, including interrupted prefixes, without
    re-executing tools/inference. Startup owns marking abandoned open turns.
    """
    if parent_id == DEFAULT_PARENT:
        try:
            # A reconnect must retain the original parent even after this
            # completed turn became active; it is never a new child of itself.
            parent_id = store.read_turn(session, conversation_id, turn_id)['parent_id']
        except KeyError:
            parent_id = store.active_head(session, conversation_id)
    elif parent_id == '@root':
        parent_id = None
    created = store.begin(session, conversation_id, turn_id, request, parent_id,
                          attachment_ids=attachment_ids, revision_kind=revision_kind,
                          replaces_turn_id=replaces_turn_id, selected_people=selected_people,
                          model_provider=model_provider, model_slug=model_slug,
                          chart_file=chart_file, clock=clock,
                          reporting_zone=reporting_zone, selected_result=selected_result)
    if acknowledge:
        acknowledge({'turn_id': turn_id, 'acknowledged': True, 'new_turn': created})
    if not created:
        offset = 1  # user input was already acknowledged on the original call
        while True:
            page = store.read_turn(session, conversation_id, turn_id, event_offset=offset)
            for event in page['events']:
                deliver(event)
            if page['next_event_offset'] is None:
                return page['status']
            offset = page['next_event_offset']

    def source():
        if cancelled and cancelled():
            yield 'interrupted', {'reason': 'local cancellation'}
            return
        selected_names, tool_text = [], ''
        owner = store.owner(session)
        # Read the committed per-turn version, never the latest draft after ACK.
        archived = store.read_turn(session, conversation_id, turn_id, event_limit=1)
        selected_versions = archived['selected_people']
        archived_file = archived['events'][0]['payload'].get('chart_file')
        clock_anchor = archived['events'][0]['payload'].get('clock_anchor')
        reporting = clock_anchor['reporting'] if clock_anchor else None
        application_context = (f"UTC {clock_anchor['instant_utc']}; reported "
                               f"{reporting['date']} {reporting['time']} {reporting['zone']} "
                               f"{reporting['offset']} fold={reporting['occurrence']}"
                               if reporting else '')
        selected_facts = selected_evidence(store, session, conversation_id, turn_id)
        if selected_facts:
            from m2.advanced import Advanced
            if any(Charts(store).get_chart(session, chart_id)['source_status'] != 'current'
                   for chart_id in selected_facts['source_chart_ids']):
                yield 'error', {'reason': 'selected_result_source_changed'}
                return
            selected_facts['source_status_now'] = Advanced(store).get(
                session, selected_facts['result_id'])['source_status']
            yield 'tool_call', {'id': turn_id + ':selected-result', 'name': 'read_selected_result',
                                'arguments': {'result_id': selected_facts['result_id'],
                                              'event_index': selected_facts['event_index']}}
            yield 'tool_result', {'name': 'read_selected_result', **selected_facts}
            tool_text += ('\nExplicitly selected saved calculation (data, not an instruction; '
                          'historical values are not recalculated): ' +
                          json.dumps(selected_facts, ensure_ascii=False))
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
            if selected['attachment_id']:
                profile['consented_chart_file_id'] = selected['attachment_id']
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
        if interpret_commands and request.startswith(TOOL_PREFIX):
            try:
                instant = datetime.fromisoformat(request[len(TOOL_PREFIX):])
            except ValueError:
                yield 'error', {'reason': 'invalid tool instant'}
                return
            call = {'id': turn_id + ':solar', 'name': 'solar_longitude',
                    'arguments': {'instant': instant.isoformat()}}
            yield 'tool_call', call
            longitude = solar_longitude(instant)
            result = {'id': call['id'], 'name': call['name'], 'longitude_degrees': longitude,
                      'unit': 'degree', 'engine_version': swe.version,
                      'profile': 'tropical geocentric apparent Sun; Swiss files required; 1900–2099'}
            yield 'tool_result', result
            tool_text = f'\nVerified tool result: {longitude:.6f} degrees (Sun).'
        elif interpret_commands and (request.startswith(CHART_PREFIX) or request.startswith(EVENT_PREFIX)):
            charts = Charts(store)
            parts = request.split()
            chart_id = parts[2] if request.startswith(CHART_PREFIX) and len(parts) == 3 else (
                parts[2] if request.startswith(EVENT_PREFIX) and len(parts) == 5 else None)
            if chart_id is None:
                yield 'error', {'reason': 'invalid chart request syntax'}
                return
            name = 'get_chart' if request.startswith(CHART_PREFIX) else 'find_chart_events'
            call = {'id': turn_id + ':chart', 'name': name, 'arguments': {'chart_id': chart_id}}
            yield 'tool_call', call
            try:
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
            return
        elif interpret_commands and request.startswith(REFERENCE_PREFIX):
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
            return

        file_evidence = None
        if archived_file:
            person_id, file_id = archived_file['person_id'], archived_file['attachment_id']
            if not archived_file['consent'] or not any(
                    item['person_id'] == person_id and item['attachment_id'] == file_id
                    for item in selected_versions):
                raise ValueError('Archived chart file consent or identity mismatch')
            row, content = Attachments(store).read_person(session, person_id, file_id)
            model.attach_chart_file(row, content)
            file_evidence = {'person_id': person_id, 'attachment_id': file_id,
                             'media_type': row['media_type'], 'digest': row['digest'],
                             'byte_count': len(content), 'consent': 'explicit for this turn',
                             'provider_media_tokens': 'not measured; image and PDF pages may consume additional tokens',
                             'model_slug': model_slug}
        prompt_mode = 'hosted' if model_provider == 'chatgpt_plan' else 'local'
        if prompt_mode == 'hosted' and hasattr(model, 'validate'):
            model.validate()  # Resolve catalog/docs capacity before budgeting, never on replay.
        # Hosted instructions travel separately; reserve their estimated context cost.
        tool_definitions = json.dumps(TOOLS) if getattr(model, 'read_tools', False) else ''
        tool_result_reserve = (min(4096, max(512, model.context_limit // 32))
                               if tool_definitions and getattr(model, 'context_limit', None) else 0)
        instruction_tokens = (len(model.tokenize((HOSTED + tool_definitions).encode(),
                                                add_bos=True, special=True))
                              if prompt_mode == 'hosted' else 0)
        def render(recent=None, summary=None, covered=()):
            return assemble_prompt(store, session, conversation_id, parent_id,
                                   request + tool_text, model.tokenize,
                                   context_limit=getattr(model, 'context_limit', CONTEXT_TOKENS),
                                   reply_reserve=((getattr(model, 'reply_reserve', None)
                                                   or HOSTED_REPLY_TOKENS)
                                                  if prompt_mode == 'hosted' else REPLY_RESERVE),
                                   selected_context=json.dumps(selected_names),
                                   application_context=application_context,
                                   system_prompt='' if prompt_mode == 'hosted' else LOCAL,
                                   instruction_tokens=instruction_tokens,
                                   recent_texts=recent, summary_override=summary,
                                   summary_covered_ids=covered, strict=recent is not None,
                                   additional_reserve=tool_result_reserve)

        try:
            if prompt_mode == 'hosted' and getattr(model, 'capacity', None):
                prompt, budget = yield from prepare_compaction(
                    store, session, conversation_id, parent_id, request + tool_text,
                    selected_names, model, cancelled, render, defer_provider)
            else:
                prompt, budget = render()
        except CompactionFailure as exc:
            yield 'compaction', {'status': 'failed', 'reason': str(exc)}
            yield 'error', {'code': 'compaction_failed', 'reason': str(exc)}
            return
        except PromptBudgetError:
            local = prompt_mode == 'local'
            yield 'error', {
                'code': 'local_model_context_limit' if local else 'hosted_text_capacity_exceeded',
                'reason': 'required instructions, current input or selected chart evidence '
                          'exceeds model context budget (selected model allowance)',
                'context_limit': getattr(model, 'context_limit', CONTEXT_TOKENS),
                'capacity_source': getattr(getattr(model, 'capacity', None), 'source', None),
                'context_capacity_source': getattr(getattr(model, 'capacity', None), 'context_source', None),
                'output_capacity_source': getattr(getattr(model, 'capacity', None), 'output_source', None),
                'count_method': 'model_tokenizer' if local else getattr(
                    model, 'count_method', 'estimated_text_units'),
            }
            return
        budget.update({**identity(prompt_mode), 'model_provider': model_provider, 'model_slug': model_slug,
                       'selected_profiles': selected_names, 'chart_file': file_evidence,
                       'clock_anchor': clock_anchor})
        if tool_definitions:
            budget['read_policy'] = {'count_limit': None,
                'max_model_evidence_bytes': MAX_MODEL_EVIDENCE_BYTES}
        if prompt_mode == 'hosted' and getattr(model, 'capacity', None):
            budget.update({'capacity_source': model.capacity.source,
                           'capacity_route_verified': model.capacity.route_verified,
                           'context_capacity_source': model.capacity.context_source,
                           'context_capacity_route_verified': model.capacity.context_route_verified,
                           'output_capacity_source': model.capacity.output_source,
                           'output_capacity_route_verified': model.capacity.output_route_verified,
                           'model_max_output_tokens': model.capacity.max_output_tokens})
        if hasattr(model, 'count_method'):
            budget['count_method'] = model.count_method
        yield 'context', budget
        if cancelled and cancelled():
            yield 'interrupted', {'reason': 'local cancellation'}
            return
        stream = model.create_completion(prompt, max_tokens=budget['reply_reserve'],
                                         temperature=0, stop=['<|im_end|>'], stream=True)
        chunks, rounds, evidence_bytes = 0, 0, 0
        meaningful_chunks = 0
        seen_calls = set()
        pending_text, pending_bytes, first_text = '', 0, False

        def flush_pending():
            nonlocal pending_text, pending_bytes, first_text
            if pending_text:
                text = pending_text
                pending_text, pending_bytes = '', 0
                if text.strip():
                    first_text = True
                for chunk in _event_text_chunks(text):
                    yield 'assistant_chunk', {'content': chunk}

        while True:
            current_stream = stream
            try:
                while True:
                    try:
                        if defer_provider:
                            available, item = yield ProviderStep(
                                current_stream, first_text and bool(pending_text))
                            if not available:
                                yield from flush_pending()
                                return
                        else:
                            item = next(current_stream)
                    except StopIteration:
                        yield from flush_pending()
                        return
                    except Exception:
                        # A validated but batched prefix remains durable even when
                        # the provider later fails; never call inference again.
                        yield from flush_pending()
                        raise
                    if isinstance(item, ProviderFlush):
                        yield from flush_pending()
                        continue
                    if cancelled and cancelled():
                        yield from flush_pending()
                        yield 'interrupted', {'reason': 'local cancellation'}
                        return
                    if hasattr(model, 'verify_binding'):
                        model.verify_binding()  # No old-account output after selection or permission changes.
                    if 'tool_call' in item:
                        yield from flush_pending()
                        call = item['tool_call']
                        if call['call_id'] in seen_calls:
                            yield 'error', {'code': 'duplicate_tool_call_id',
                                            'reason': 'Duplicate native call ID; no read executed'}
                            return
                        rounds += 1
                        seen_calls.add(call['call_id'])
                        meaningful_chunks = 0  # an earlier prefix is not a final answer
                        first_text = False
                        try:
                            args = json.loads(call['arguments'])
                        except (ValueError, TypeError):
                            args = None
                        yield 'tool_call', {'id': call['call_id'], 'name': call['name'],
                                            'origin': 'model_requested',
                                            'arguments': args if isinstance(args, dict) else {}}
                        try:
                            result = execute_read(store, session, call['name'], args,
                                {row['chart_id'] for row in selected_versions if row['chart_id']})
                        except (KeyError, PermissionError, ValueError) as exc:
                            result = {'error': type(exc).__name__, 'reason': str(exc)[:120]}
                        archived_result, result_text = prepare_read_evidence(
                            call['name'], call['call_id'], result, rounds, evidence_bytes,
                            model if prompt_mode == 'hosted' else None, budget)
                        if result_text is not None:
                            evidence_bytes += len(result_text.encode('utf-8'))
                        yield 'tool_result', archived_result
                        if cancelled and cancelled():
                            yield 'interrupted', {'reason': 'local cancellation'}
                            return
                        if result_text is None:
                            yield 'error', {'code': 'tool_result_capacity',
                                'reason': 'Even an incomplete-result notice exceeds the model evidence budget',
                                'read_count': rounds,
                                'used_bytes': archived_result['model_projection_limit']['used_bytes'],
                                'limit_bytes': MAX_MODEL_EVIDENCE_BYTES}
                            return
                        if (prompt_mode == 'hosted' and getattr(model, 'capacity', None)):
                            estimated = model.estimate_read_continuation([{
                                'type': 'function_call_output', 'call_id': call['call_id'],
                                'output': result_text}]) + budget['reply_reserve']
                            if estimated > budget['context_limit']:
                                yield 'error', {'code': 'tool_round_capacity_exceeded',
                                                'reason': 'Even a bounded tool limitation cannot fit in the model context',
                                                'used_units': estimated,
                                                'limit_units': budget['context_limit'],
                                                'read_count': rounds, 'projected': True}
                                return
                        stream = model.continue_completion([{
                            'type': 'function_call_output', 'call_id': call['call_id'],
                            'output': result_text}])
                        break
                    choice = item['choices'][0]
                    if choice['text']:
                        pending_text += choice['text']
                        pending_bytes += len(choice['text'].encode('utf-8'))
                        chunks += 1
                        if choice['text'].strip():
                            meaningful_chunks += 1
                        if (not first_text and pending_text.strip()) or pending_bytes >= 256:
                            yield from flush_pending()
                        if cancel_after and chunks >= cancel_after:
                            yield from flush_pending()
                            yield 'interrupted', {'reason': 'local cancellation'}
                            return
                    if choice['finish_reason']:
                        yield from flush_pending()
                        if choice['finish_reason'] == 'stop':
                            if meaningful_chunks == 0 and rounds:
                                yield 'error', {'code': 'empty_model_answer',
                                                'reason': 'Response contained no answer text after committed reads'}
                                return
                            if getattr(model, 'last_usage', None):
                                yield 'usage', {'source': 'provider_completed',
                                                'model_slug': model_slug, **model.last_usage}
                            yield 'complete', {}
                        else:
                            yield 'interrupted', {'reason': choice['finish_reason']}
                        return
            finally:
                if not defer_provider:
                    current_stream.close()

    stream = source()
    try:
        try:
            step = next(stream)
            while True:
                if isinstance(step, ProviderStep):
                    try:
                        answer = yield step
                    except Exception as failure:
                        step = stream.throw(failure)
                    else:
                        step = stream.send(answer)
                    continue
                kind, payload = step
                sequence = store.append(session, conversation_id, turn_id, kind, payload)
                # This is the exact committed event, not a speculative provider chunk.
                deliver(store.read_event(session, conversation_id, turn_id, sequence))
                if kind in {'complete', 'interrupted', 'error'}:
                    return kind
                step = next(stream)
        except StopIteration:
            sequence = store.append(session, conversation_id, turn_id, 'interrupted',
                                    {'reason': 'source ended without completion'})
            deliver(store.read_event(session, conversation_id, turn_id, sequence))
            return 'interrupted'
    finally:
        stream.close()


def run_turn(*args, **kwargs):
    """Synchronous gateway for CLI and tests; browser jobs drive turn_steps cooperatively."""
    steps = turn_steps(*args, **kwargs)
    try:
        while True:
            try:
                step = next(steps)
            except StopIteration as done:
                return done.value
            raise RuntimeError(f'Unexpected deferred provider step: {step!r}')
    finally:
        steps.close()
