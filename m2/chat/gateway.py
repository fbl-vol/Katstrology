"""Backend-owned local turn boundary; user input, tool evidence and output commit first."""

from datetime import datetime
import json

import swisseph as swe

from m2.operations.app_clock import utc_now
from m2.chat.context import read_committed_context
from m2.chat.evidence_links import (CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX,
                               read_command_evidence)
from m2.chat.agent_reads import TOOLS as READ_TOOLS, execute as execute_read
from m2.chat.personal_context import UPDATE_TOOL, stage as stage_context
TOOLS = [*READ_TOOLS, UPDATE_TOOL]
from m2.chat.tool_evidence import (MAX_MODEL_EVIDENCE_BYTES,
                              prepare as prepare_read_evidence)
from m2.chat.compaction import CompactionFailure, prepare as prepare_compaction
from m2.chat.recall import CONTEXT_TOKENS, REPLY_RESERVE, PromptBudgetError, assemble_prompt
from m2.chat.prompting import LOCAL, identity
from m2.chat.tone_profiles import archived_instructions
from m2.references.references import References
from m2.provider.steps import ProviderFlush, ProviderStep
from m2.chat.web_tools import EXTERNAL as WEB_EXTERNAL, NAMES as WEB_NAMES
from m2.chat.web_evidence import external_result, validate_page_sources, WEB_MODEL_BYTES
from m2.archive.store import MAX_EVENT_BYTES
from m2.calculation.core_calc import solar_longitude


TOOL_PREFIX = 'solar longitude at '
DEFAULT_PARENT = '@active'
# Fallback for test doubles; real hosted models resolve capacity before assembly.
HOSTED_REPLY_TOKENS = 384


def _event_text_chunks(text):
    """Bound both Store.append's payload guard and the escaped JSON payload."""
    start = 0
    while start < len(text):
        # A code point is at least one byte. Limit the candidate to one event's
        # worth of characters, rather than repeatedly measuring the whole reply.
        low, high = start + 1, min(len(text), start + MAX_EVENT_BYTES)
        while low < high:
            middle = (low + high + 1) // 2
            payload = {'content': text[start:middle]}
            if (len(str(payload).encode('utf-8')) <= MAX_EVENT_BYTES and
                    len(json.dumps(payload).encode('utf-8')) <= MAX_EVENT_BYTES):
                low = middle
            else:
                high = middle - 1
        yield text[start:low]
        start = low


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
        context = yield from read_committed_context(store, session, conversation_id, turn_id)
        if context is None:  # The reader already yielded the source-change error.
            return
        selected_names, tool_text, application_context, clock_anchor, selected_versions, payload = context
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
        elif interpret_commands and request.startswith((CHART_PREFIX, EVENT_PREFIX, REFERENCE_PREFIX)):
            yield from read_command_evidence(store, session, turn_id, request)
            return

        prompt_mode = 'hosted' if model_provider == 'chatgpt_plan' else 'local'
        instructions, prompt_id = (archived_instructions(payload.get('tone'))
                                   if prompt_mode == 'hosted' else (LOCAL, identity('local')))
        if prompt_mode == 'hosted' and hasattr(model, 'validate'):
            model.validate()  # Resolve catalog/docs capacity before budgeting, never on replay.
        # Hosted instructions travel separately; reserve their estimated context cost.
        updates_enabled = bool(payload.get('personal_context', {}).get('consent', {}).get('enabled'))
        if hasattr(model, 'context_updates_enabled'):
            model.context_updates_enabled = updates_enabled
        tool_definitions = (json.dumps(TOOLS if updates_enabled else READ_TOOLS,
                                      ensure_ascii=False, separators=(',', ':'))
                            if getattr(model, 'read_tools', False) else '')
        tool_result_reserve = (min(4096, max(512, model.context_limit // 32))
                               if tool_definitions and getattr(model, 'context_limit', None) else 0)
        # Metadata discovery is not a passage read or an interpretation. Keep it
        # in the measured untrusted context, including every compaction render.
        library = (References(store).selected_library(session)
                   if prompt_mode == 'hosted' and tool_definitions else None)
        reference_context = json.dumps(library, ensure_ascii=False) if library is not None else ''
        instruction_tokens = (len(model.tokenize((instructions + tool_definitions).encode(),
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
                                   additional_reserve=tool_result_reserve,
                                   reference_context=reference_context)

        try:
            if prompt_mode == 'hosted' and getattr(model, 'capacity', None):
                prompt, budget = yield from prepare_compaction(
                    store, session, conversation_id, parent_id, request + tool_text,
                    selected_names, model, cancelled, render, defer_provider,
                    prompt_id=prompt_id)
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
        budget.update({**prompt_id, 'model_provider': model_provider, 'model_slug': model_slug,
                       'selected_profiles': selected_names, 'clock_anchor': clock_anchor})
        if library is not None:
            # Archive bounded discovery identity, not duplicate untrusted titles
            # alongside potentially large selected chart/profile metadata.
            budget['selected_library'] = {'source_ids': [row['source_id'] for row in library['sources']],
                                          'next_after': library['next_after'], 'metadata_only': True}
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
                                         temperature=0, stop=['<|im_end|>'], stream=True,
                                         **({'instructions': instructions} if prompt_mode == 'hosted' else {}))
        chunks, rounds, evidence_bytes, web_bytes = 0, 0, 0, 0
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
                            if call['name'] == 'stage_personal_context':
                                result = stage_context(store, session, conversation_id, turn_id, args)
                            elif call['name'] in WEB_EXTERNAL:
                                if call['name'] == 'fetch_web_page':
                                    validate_page_sources(store, session, conversation_id, args)
                                if web_bytes >= WEB_MODEL_BYTES - 512:
                                    result = {'status': 'unavailable', 'reason': 'web_evidence_allowance_exhausted'}
                                else:
                                    work = external_result(model, call['name'], args,
                                                           cancelled or (lambda: False))
                                    try:
                                        if defer_provider:
                                            available, result = yield ProviderStep(work)
                                            if not available:
                                                raise ValueError('Web work ended without a result')
                                        else:
                                            result = next(work)
                                    finally:
                                        if not defer_provider:
                                            work.close()
                                if cancelled and cancelled():
                                    yield 'interrupted', {'reason': 'local cancellation'}
                                    return
                                if hasattr(model, 'verify_binding'):
                                    model.verify_binding()
                                result.update({'conversation_id': conversation_id, 'turn_id': turn_id})
                            else:
                                # Discovery must survive history compaction without a model-
                                # remembered handle. Keep the archived native call unchanged.
                                read_args = args
                                if (call['name'] == 'read_web_content' and isinstance(args, dict)
                                        and args.get('conversation_id') == ''):
                                    read_args = {**args, 'conversation_id': conversation_id}
                                result = execute_read(store, session, call['name'], read_args,
                                    {row['chart_id'] for row in selected_versions if row['chart_id']},
                                    current_turn=(conversation_id, turn_id))
                        except (KeyError, PermissionError, ValueError) as exc:
                            result = {'error': type(exc).__name__, 'reason': str(exc)[:120]}
                        archived_result, result_text = prepare_read_evidence(
                            call['name'], call['call_id'], result, rounds, evidence_bytes,
                            model if prompt_mode == 'hosted' else None, budget, web_bytes)
                        if result_text is not None:
                            evidence_bytes += len(result_text.encode('utf-8'))
                            if call['name'] in WEB_NAMES:
                                web_bytes += len(result_text.encode('utf-8'))
                        yield 'tool_result', archived_result
                        if cancelled and cancelled():
                            yield 'interrupted', {'reason': 'local cancellation'}
                            return
                        if result_text is None:
                            yield 'error', {'code': 'tool_result_capacity',
                                'reason': 'Even an incomplete-result notice exceeds the model evidence budget',
                                'read_count': rounds,
                                'used_bytes': archived_result['model_projection_limit']['used_bytes'],
                                'limit_bytes': archived_result['model_projection_limit']['limit_bytes']}
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
