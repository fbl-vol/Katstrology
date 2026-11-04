"""Owner-scoped, append-only conversation checkpoints for bounded hosted prompts.

Original turns/tool evidence remain authoritative. This derived model-written text
is lower-trust continuity, never a chart calculation, file permission or search.
"""

from hashlib import sha256
import json

import psycopg

from m2.prompting import SUMMARY, identity, summary_identity
from m2.recall import PromptBudgetError, dialogue_projection
from m2.siwc import ProviderFailure
from m2.provider_steps import ProviderStep


SUMMARY_CHARS = 4096
TOOL_CHARS = 2000


class CompactionFailure(ValueError):
    """A checkpoint was not published; the newly archived input stays terminal."""


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             default=str).encode('utf-8')).hexdigest()


def turn_text(store, session, conv_id, turn_id, chains, resolved, turn=None):
    """A single complete turn keeps its user, call/result pairs and reply together."""
    projected = dialogue_projection(store, session, conv_id, turn_id, chains, resolved, turn=turn)
    if projected is None:
        return None
    current = projected['text']
    if not projected['full_evidence']:
        return current  # Historical user intent and refreshed interpretation, never old tools.
    turn = turn if turn is not None else next(store.read_complete_turns(session, conv_id, [turn_id]))
    if turn['corrections']:
        return current  # Never summarize superseded assistant/tool content.
    events = turn['events']
    lines = [f"[turn {turn_id} user report] {events[0]['payload']['content']}"]
    for event in events[1:]:
        if event['kind'] in ('tool_call', 'tool_result'):
            value = json.dumps(event['payload'], ensure_ascii=False, sort_keys=True, default=str)
            if len(value) > TOOL_CHARS:
                value = value[:TOOL_CHARS] + f' [tool record excerpt; {len(value) - TOOL_CHARS} characters omitted]'
            lines.append(f"[{event['kind']} #{event['sequence']} of {turn_id}] {value}")
    reply = ''.join(event['payload']['content'] for event in events
                    if event['kind'] == 'assistant_chunk')
    if reply:
        lines.append(f'[turn {turn_id} assistant interpretation, not evidence] {reply}')
    return '\n'.join(lines)


def _history(store, session, conv_id, chain):
    chains, resolved = {conv_id: set(chain)}, {}
    history = []
    for start in range(0, len(chain), 20):
        for turn in store.read_complete_turns(session, conv_id, chain[start:start + 20]):
            text = turn_text(store, session, conv_id, turn['id'], chains, resolved, turn=turn)
            if text is not None:
                history.append((turn['id'], text))
    return history


def model_policy(model):
    return digest([model.slug, model.context_limit, model.capacity.max_output_tokens,
                   model.capacity.source, model.reply_reserve, model.count_method])


def _checkpoint(store, owner, conv_id, history, revision, model, selected_sha, prompt_id=None):
    prompt_id = prompt_id or identity('hosted')
    rows = store.db.execute('''
        SELECT * FROM compaction_checkpoints WHERE owner_id=%s AND conversation_id=%s
          AND compaction_revision=%s AND model_provider='chatgpt_plan' AND model_slug=%s
          AND prompt_version=%s AND prompt_sha256=%s AND selected_sha256=%s
          AND model_policy_sha256=%s
        ORDER BY id DESC LIMIT 8
    ''', (owner, conv_id, revision, model.slug, prompt_id['prompt_version'],
          prompt_id['prompt_sha256'], selected_sha, model_policy(model))).fetchall()
    ids = [turn_id for turn_id, _ in history]
    for row in rows:
        covered = row['covered_ids']
        if (ids[:len(covered)] == covered and len(ids) > len(covered) and
                ids[len(covered)] == row['first_kept_id'] and
                digest(history[:len(covered)]) == row['source_sha256'] and
                row['summary_sha256'] == summary_identity()['summary_sha256']):
            return row
    return None


def _estimate(model, text):
    return len(model.tokenize(text.encode('utf-8'), add_bos=True, special=True))


def _summary(model, previous, retired, cancelled, defer_provider=False):
    source = json.dumps({'previous_checkpoint': previous or None,
                         'newly_retired_eligible_turns': retired},
                        ensure_ascii=False, sort_keys=True)
    input_units = _estimate(model, source) + _estimate(model, SUMMARY)
    max_output = min(8192, model.capacity.max_output_tokens,
                     model.context_limit - input_units - 1024)
    if max_output < 256:
        raise CompactionFailure('summary_input_exceeds_model_window')
    if cancelled and cancelled():
        raise CompactionFailure('summary_cancelled')
    stream = model.create_completion(source, instructions=SUMMARY, summary=True,
                                     max_output_tokens=max_output, stream=True)
    parts = []
    char_count = 0
    stopped = False
    try:
        while True:
            if defer_provider:
                available, item = yield ProviderStep(stream)
                if not available:
                    break
            else:
                try:
                    item = next(stream)
                except StopIteration:
                    break
            if cancelled and cancelled():
                raise CompactionFailure('summary_cancelled')
            if hasattr(model, 'verify_binding'):
                model.verify_binding()
            choice = item['choices'][0]
            if choice['text']:
                parts.append(choice['text'])
                char_count += len(choice['text'])
                if char_count > SUMMARY_CHARS:
                    raise CompactionFailure('summary_exceeds_bound')
            if choice['finish_reason']:
                if choice['finish_reason'] != 'stop':
                    raise CompactionFailure('summary_incomplete')
                stopped = True
    except ProviderFailure as exc:
        if exc.reason == 'selected_account_changed':
            raise
        raise CompactionFailure(exc.reason) from exc
    except (CompactionFailure, PromptBudgetError):
        raise
    except Exception as exc:
        raise CompactionFailure('summary_transport_failed') from exc
    finally:
        if not defer_provider:
            stream.close()
    text = ''.join(parts).strip()
    if not stopped:
        raise CompactionFailure('summary_incomplete')
    if not text:
        raise CompactionFailure('summary_empty')
    headings = ('## Attributed user reports and preferences',
                '## Prior assistant interpretations (not evidence)',
                '## Chart/person/version and other source references',
                '## Uncertainty, corrections and open questions')
    if any(text.count(heading) != 1 for heading in headings):
        raise CompactionFailure('summary_format_invalid')
    return text, input_units, _estimate(model, text), model.last_usage


def _last_usage(store, session, conv_id, head_id, model, selected_sha, revision, checkpoint_id, prompt_id=None):
    prompt_id = prompt_id or identity('hosted')
    if not head_id:
        return None
    events = store.db.execute('''
        SELECT kind,payload FROM events WHERE owner_id=%s AND conversation_id=%s
          AND turn_id=%s AND kind IN ('context', 'usage') ORDER BY sequence
    ''', (store.owner(session), conv_id, head_id)).fetchall()
    context = next((event['payload'] for event in events if event['kind'] == 'context'), None)
    usage = next((event['payload'] for event in events if event['kind'] == 'usage'), None)
    tokens = usage.get('input_tokens') if usage else None
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
        return None
    if not context or any((
            context.get('model_provider') != 'chatgpt_plan',
            context.get('model_slug') != model.slug,
            context.get('prompt_sha256') != prompt_id['prompt_sha256'],
            context.get('selected_sha256') != selected_sha,
            context.get('model_policy_sha256') != model_policy(model),
            context.get('compaction_revision') != revision,
            context.get('compaction_checkpoint_id') != checkpoint_id,
            usage.get('source') != 'provider_completed')):
        return None
    return tokens


def prepare(store, session, conv_id, head_id, request, selected_context,
            model, cancelled, render, defer_provider=False, prompt_id=None):
    """Yield progress for one bounded pre-dispatch compaction, then a strict prompt.

    render(recent_texts, summary, covered_ids) returns a measured prompt/budget
    or raises PromptBudgetError. No failed or repeated archived turn is resent.
    """
    owner = store.owner(session)
    prompt_id = prompt_id or identity('hosted')
    snapshot = store._conversation(owner, conv_id)
    chain = store.ancestry(session, conv_id, head_id)
    history = _history(store, session, conv_id, chain)
    selected_sha = digest(selected_context)
    revision = snapshot['compaction_revision']
    checkpoint = _checkpoint(store, owner, conv_id, history, revision, model, selected_sha, prompt_id)
    covered = checkpoint['covered_ids'] if checkpoint else []
    summary = checkpoint['summary'] if checkpoint else None
    remaining = history[len(covered):]
    checkpoint_id = checkpoint['id'] if checkpoint else None

    def project(tail, digest_text, source_ids):
        return render([text for _, text in tail], digest_text, source_ids)

    # No amount of compaction can make required chart facts and the new question
    # fit a genuinely undersized model; avoid a paid summary attempt first.
    project([], None, [])

    # The output reserve accounts for *planned* reply headroom. Additional
    # compaction headroom triggers early but is never a second hard model cap.
    threshold = model.context_limit - model.reply_reserve - min(16_384, model.context_limit // 10)
    try:
        prompt, budget = project(remaining, summary, covered)
        projected = budget['prompt_tokens'] + budget['instruction_tokens'] + budget['reply_reserve']
    except PromptBudgetError:
        prompt = budget = None
        projected = model.context_limit + 1
    anchor = _last_usage(store, session, conv_id, head_id, model, selected_sha,
                         revision, checkpoint_id, prompt_id)
    if anchor:
        # Measured provider input plus new input/answer estimate is a *trigger*
        # signal only; units differ and strict assembled fit is always rechecked.
        trailing = _estimate(model, request)
        if remaining:
            trailing += _estimate(model, remaining[-1][1])
        projected = max(projected, anchor + trailing + model.reply_reserve)
    if prompt is not None and projected <= threshold:
        budget.update({'compaction_checkpoint_id': checkpoint_id, 'compaction_revision': revision,
                       'selected_sha256': selected_sha, 'model_policy_sha256': model_policy(model),
                       'projection_source': 'provider_usage_plus_estimated_tail' if anchor else 'text_estimate'})
        return prompt, budget

    keep_goal = min(20_000, max(1024, model.context_limit // 4))
    retained, retained_units = [], 0
    for item in reversed(remaining):
        units = _estimate(model, item[1])
        if retained and retained_units + units > keep_goal:
            break
        retained.insert(0, item)
        retained_units += units
    retired = remaining[:len(remaining) - len(retained)]
    if not retired:
        if prompt is None:
            raise PromptBudgetError('Mandatory input or retained turn exceeds context allowance')
        budget.update({'compaction_checkpoint_id': checkpoint_id, 'compaction_revision': revision,
                       'selected_sha256': selected_sha, 'model_policy_sha256': model_policy(model),
                       'projection_source': 'text_estimate'})
        return prompt, budget

    yield 'compaction', {'status': 'starting', 'retired_turns': len(retired),
                         'retained_turns': len(retained), 'count_method': model.count_method}
    try:
        new_summary, input_units, output_units, usage = yield from _summary(
            model, summary, retired, cancelled, defer_provider)
        new_covered = covered + [turn_id for turn_id, _ in retired]
        # Check mandatory facts and retained turns *before* committing a boundary.
        next_prompt, next_budget = project(retained, new_summary, new_covered)
        if cancelled and cancelled():
            raise CompactionFailure('summary_cancelled')
        if hasattr(model, 'verify_binding'):
            model.verify_binding()
        with store.db.transaction():
            latest = store._conversation(owner, conv_id, lock=True)
            if cancelled and cancelled():
                raise CompactionFailure('summary_cancelled')
            if (latest['epoch'] != snapshot['epoch'] or latest['active_head'] != snapshot['active_head']
                    or latest['compaction_revision'] != revision or
                    store.ancestry(session, conv_id, head_id) != chain or
                    digest(_history(store, session, conv_id, chain)[:len(new_covered)]) !=
                    digest(history[:len(new_covered)])):
                raise CompactionFailure('summary_source_changed')
            row = store.db.execute('''
                INSERT INTO compaction_checkpoints (
                    owner_id,conversation_id,source_head,compaction_revision,model_provider,
                    model_slug,prompt_version,prompt_sha256,summary_version,summary_sha256,
                    selected_sha256,model_policy_sha256,covered_ids,first_kept_id,source_sha256,
                    summary,count_method,input_estimate,output_estimate,usage)
                VALUES (%s,%s,%s,%s,'chatgpt_plan',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            ''', (owner, conv_id, head_id, revision, model.slug,
                  prompt_id['prompt_version'], prompt_id['prompt_sha256'],
                  summary_identity()['summary_version'], summary_identity()['summary_sha256'],
                  selected_sha, model_policy(model), psycopg.types.json.Jsonb(new_covered), retained[0][0],
                  digest(history[:len(new_covered)]), new_summary,
                  model.count_method, input_units, output_units,
                  psycopg.types.json.Jsonb(usage) if usage else None)).fetchone()
        next_budget.update({'compaction_checkpoint_id': row['id'], 'compaction_revision': revision,
                            'selected_sha256': selected_sha, 'model_policy_sha256': model_policy(model),
                            'projection_source': 'text_estimate',
                            'compaction_summary_usage': usage,
                            'summary_prompt': summary_identity(),
                            'summary_covered_ids': new_covered})
        yield 'compaction', {'status': 'complete', 'checkpoint_id': row['id'],
                             'covered_turns': len(new_covered), 'first_kept_id': retained[0][0],
                             'summary_input_estimate': input_units, 'summary_output_estimate': output_units,
                             'count_method': model.count_method, 'usage': usage}
        return next_prompt, next_budget
    except (CompactionFailure, PromptBudgetError) as exc:
        raise CompactionFailure(str(exc) or 'compaction_failed') from exc
