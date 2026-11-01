"""Single-owner local conversation/tool experiment; not a client or production archive.

The gateway interprets one explicit synthetic calculation command. The model is
not trusted to choose tools; this tests real tool execution and capture plumbing.
"""

from datetime import datetime

import swisseph as swe

from capture_probe import run_turn
from core_calc import solar_longitude


SYSTEM = 'Use the supplied tool result only. Give a short answer; do not invent numbers.'
TOOL_PREFIX = 'solar longitude at '


def format_messages(messages):
    return ''.join(f'<|im_start|>{role}\n{text}<|im_end|>\n'
                   for role, text in messages) + '<|im_start|>assistant\n'


def bounded_prompt(archive, parent_id, request, tokenize, context_limit=1024,
                   reply_reserve=128):
    """Select a suffix of complete ancestors using measured model tokens.

    Originals stay in SQLite; dropping context never erases history. No summary
    stands in for abandoned branches. The current request is always retained.
    """
    history = []
    for turn_id in archive.ancestry(parent_id):
        events = archive.replay(turn_id)
        history.append([('user', events[0]['content']),
                        ('assistant', ''.join(e['content'] for e in events
                                             if e['kind'] == 'assistant_chunk'))])

    def build(pairs):
        messages = [('system', SYSTEM)]
        for pair in pairs:
            messages.extend(pair)
        messages.append(('user', request))
        text = format_messages(messages)
        return text, len(tokenize(text.encode(), add_bos=True, special=True))

    while True:
        prompt, tokens = build(history)
        if tokens + reply_reserve <= context_limit:
            return prompt, {'prompt_tokens': tokens, 'reply_reserve': reply_reserve,
                            'context_limit': context_limit, 'included_turns': len(history),
                            'excluded_turns': len(archive.ancestry(parent_id)) - len(history)}
        if not history:
            raise ValueError('Current request exceeds context budget')
        history.pop(0)


def run_calculation_turn(archive, turn_id, parent_id, request, model, deliver,
                         context_limit=1024, reply_reserve=128, interrupt_after=None):
    """Persist user before inference, tool calls/results and chunks before delivery.

    The fixed command is the only supported tool dispatch. Failure keeps the turn
    open for exclusive-owner recovery; retry replays, never reruns inference/tool.
    """
    def source():
        if not request.startswith(TOOL_PREFIX):
            yield {'kind': 'error', 'reason': 'unsupported tool request'}
            return
        instant = datetime.fromisoformat(request[len(TOOL_PREFIX):])
        call = {'kind': 'tool_call', 'id': f'{turn_id}:solar', 'name': 'solar_longitude',
                'arguments': {'instant': instant.isoformat()}}
        yield call
        longitude = solar_longitude(instant)
        result = {'kind': 'tool_result', 'id': call['id'], 'name': call['name'], 'result': {
            'longitude_degrees': longitude, 'profile': 'Swiss tropical apparent geocentric Sun',
            'range': '1900–2099', 'unit': 'degree', 'engine_version': swe.version}}
        yield result
        tool_text = f'Tool result: {longitude:.6f} degrees (Swiss apparent geocentric Sun).'
        prompt, budget = bounded_prompt(archive, parent_id, request + '\n' + tool_text,
                                        model.tokenize, context_limit, reply_reserve)
        # Budget is measured against the actual assembled prompt, including tool result.
        yield {'kind': 'context', 'budget': budget}
        stream = model.create_completion(prompt, max_tokens=reply_reserve, temperature=0,
                                         stop=['<|im_end|>'], stream=True)
        count = 0
        try:
            for chunk in stream:
                choice = chunk['choices'][0]
                if choice['text']:
                    yield {'kind': 'assistant_chunk', 'content': choice['text']}
                    count += 1
                    if interrupt_after and count >= interrupt_after:
                        yield {'kind': 'interrupted', 'reason': 'local cancellation probe'}
                        return
                if choice['finish_reason']:
                    if choice['finish_reason'] == 'stop':
                        yield {'kind': 'complete'}
                    else:
                        yield {'kind': 'interrupted', 'reason': choice['finish_reason']}
                    return
        finally:
            stream.close()

    run_turn(archive, turn_id, request, source, deliver, parent_id=parent_id)
