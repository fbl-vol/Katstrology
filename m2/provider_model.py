"""Supported direct Responses HTTP/SSE adapter; no hosted MCP or provider history."""

import json
import math
from m2.agent_reads import TOOLS
from m2.model_capacity import resolve_capacity
from m2.prompting import HOSTED
from m2.provider_media import VISION_MODELS, chart_content
from m2.siwc import ProviderFailure

MAX_RESPONSE_TEXT_BYTES = 512 * 1024
MAX_RESPONSE_FOOTER_BYTES = 2 * 1024 * 1024


class _OutputItems:
    """Hold only bounded completed native SSE items until a successful terminal response."""

    def __init__(self):
        self.items = {}
        self.conflict = False
        self.unsupported = False

    @property
    def calls(self):
        return [state for state in self.items.values() if state['type'] == 'function_call']

    @property
    def completed_count(self):
        return sum(state['done'] is not None for state in self.items.values())

    def observe(self, event, request_id):
        kind = event.get('type')
        if kind not in ('response.output_item.added', 'response.output_item.done',
                        'response.function_call_arguments.delta',
                        'response.function_call_arguments.done'):
            return
        item = event.get('item')
        if kind.startswith('response.output_item') and not isinstance(item, dict):
            self.conflict = True
            return
        index = event.get('output_index')
        if index is not None and (type(index) is not int or not 0 <= index < 8):
            self.conflict = True
            return
        item_id = item.get('id') if isinstance(item, dict) else event.get('item_id')
        key = (('index', index) if index is not None else
               ('id', item_id) if isinstance(item_id, str) and item_id else None)
        if key is None or (len(self.items) >= 8 and key not in self.items):
            self.conflict = True
            return
        state = self.items.get(key)
        if state is None:
            if not kind.startswith('response.output_item'):
                self.conflict = True  # Argument events cannot create a tool identity.
                return
            state = {'type': item.get('type'), 'id': None, 'call_id': None, 'name': None,
                     'delta': '', 'saw_delta': False, 'arguments_done': None, 'done': None}
            self.items[key] = state
        if isinstance(item_id, str) and item_id:
            if state['id'] is not None and state['id'] != item_id:
                self.conflict = True
            state['id'] = item_id
        elif item_id is not None:
            self.conflict = True
        if kind.startswith('response.output_item'):
            if state['type'] != item.get('type') or state['done'] is not None:
                self.conflict = True
            if state['type'] not in ('message', 'reasoning', 'function_call'):
                self.unsupported = True
            for field in ('call_id', 'name') if state['type'] == 'function_call' else ():
                value = item.get(field)
                if value is not None:
                    if not isinstance(value, str) or not value or (
                            state[field] is not None and state[field] != value):
                        self.conflict = True
                    else:
                        state[field] = value
            if kind == 'response.output_item.done':
                if item.get('status') not in (None, 'completed'):
                    self.conflict = True
                if len(json.dumps(item).encode('utf-8')) > MAX_RESPONSE_FOOTER_BYTES:
                    raise ProviderFailure('invalid_provider_output', request_id=request_id)
                if state['type'] == 'function_call':
                    arguments = item.get('arguments')
                    if arguments is None:
                        arguments = state['arguments_done']
                        item = {**item, 'arguments': arguments}
                    if not isinstance(arguments, str) or len(arguments.encode('utf-8')) > 2048 or (
                            state['arguments_done'] is not None and
                            arguments != state['arguments_done']) or (
                            state['saw_delta'] and not arguments.startswith(state['delta'])):
                        self.conflict = True
                state['done'] = item  # Never archive this, especially reasoning.encrypted_content.
            return

        if state['type'] != 'function_call' or state['done'] is not None:
            self.conflict = True
            return
        arguments = event.get('delta') if kind.endswith('.delta') else event.get('arguments')
        if not isinstance(arguments, str) or len(arguments.encode('utf-8')) > 2048:
            self.conflict = True
            return
        if kind.endswith('.delta'):
            state['delta'] += arguments
            state['saw_delta'] = True
            if len(state['delta'].encode('utf-8')) > 2048:
                self.conflict = True
        else:
            if ((state['arguments_done'] is not None and
                 state['arguments_done'] != arguments) or
                    (state['saw_delta'] and not arguments.startswith(state['delta']))):
                self.conflict = True
            state['arguments_done'] = arguments

    def assemble(self, final):
        """Return (ordered authoritative items, rejection category); never promote added-only items."""
        if self.unsupported:
            return None, 'unsupported_item'
        if self.conflict:
            return None, 'identifier_mismatch'
        ids = [state['id'] for state in self.items.values() if state['id'] is not None]
        if len(ids) != len(set(ids)) or any(
                state['done'] is not None and not state['id'] for state in self.items.values()):
            return None, 'identifier_mismatch'
        if final:
            merged = list(final)
            for (key_type, key_value), state in self.items.items():
                if key_type == 'index':
                    candidates = [final[key_value]] if key_value < len(final) else []
                else:
                    candidates = [entry for entry in final if isinstance(entry, dict) and
                                  entry.get('id') == key_value]
                if len(candidates) != 1 or not isinstance(candidates[0], dict):
                    return None, 'identifier_mismatch'
                item = candidates[0]
                if (item.get('type') != state['type'] or
                        (state['id'] is not None and item.get('id') != state['id']) or
                        (state['call_id'] is not None and item.get('call_id') != state['call_id']) or
                        (state['name'] is not None and item.get('name') != state['name'])):
                    return None, 'identifier_mismatch'
                done = state['done']
                for field in ('arguments', 'content', 'encrypted_content', 'summary'):
                    if (done is not None and field in done and field in item and
                            done[field] != item[field]):
                        return None, 'identifier_mismatch'
                if state['arguments_done'] is not None and item.get('arguments') != state['arguments_done']:
                    return None, 'identifier_mismatch'
                if state['saw_delta'] and (
                        not isinstance(item.get('arguments'), str) or
                        not item['arguments'].startswith(state['delta'])):
                    return None, 'identifier_mismatch'
                if done is not None:
                    position = key_value if key_type == 'index' else next(
                        index for index, entry in enumerate(final) if entry is item)
                    merged[position] = {**item, **done}  # Retain completed opaque reasoning if footer is slim.
            return merged, None
        if any(state['done'] is None for state in self.items.values()):
            return None, 'incomplete_item'
        if len(self.items) > 1 and any(key[0] != 'index' for key in self.items):
            return None, 'identifier_mismatch'  # Cannot order several ID-only items.
        return [state['done'] for _, state in sorted(self.items.items())], None


def _valid_read_arguments(name, serialized):
    """Check the advertised closed JSON schema before a reconstructed call is archived."""
    schema = next((tool['parameters'] for tool in TOOLS if tool['name'] == name), None)
    if schema is None:
        return False
    try:
        arguments = json.loads(serialized)
    except (TypeError, ValueError):
        return False
    if not isinstance(arguments, dict) or set(arguments) != set(schema['required']):
        return False
    for key, value in arguments.items():
        field = schema['properties'][key]
        allowed = field['type'] if isinstance(field['type'], list) else [field['type']]
        if not ((isinstance(value, str) and 'string' in allowed) or
                (type(value) is int and 'integer' in allowed and
                 field.get('minimum', value) <= value <= field.get('maximum', value)) or
                ((type(value) is int or (type(value) is float and math.isfinite(value)))
                 and 'number' in allowed and
                 field.get('minimum', value) <= value <= field.get('maximum', value)) or
                (value is None and 'null' in allowed)):
            return False
        if isinstance(value, str) and (
                len(value) > field.get('maxLength', 2048) or
                ('enum' in field and value not in field['enum'])):
            return False
    return True


class ResponsesModel:
    count_method = 'conservative_utf8_byte_estimate'
    read_tools = True

    def __init__(self, bridge, owner, slug, admission=None):
        if admission and (admission.owner != owner or admission.slug != slug):
            raise ValueError('Catalog admission belongs to another owner or model')
        self.bridge, self.owner, self.slug = bridge, owner, slug
        self.binding = admission.binding if admission else None
        self.context_limit = None
        self.reply_reserve = None
        self.capacity = admission.capacity if admission else None
        self.chart_file = None
        self.last_usage = None
        self._continuation_input = None
        self._instructions = None

    def attach_chart_file(self, row, content):
        if self.slug not in VISION_MODELS:
            raise ProviderFailure('chart_file_model_capability_unestablished')
        self.chart_file = chart_content(row, content)

    def tokenize(self, text, **_kwargs):
        # Provider-specific tokenizers are not exposed. Charge roughly one
        # estimated unit per two UTF-8 bytes, not actual provider tokens.
        data = text if isinstance(text, bytes) else text.encode('utf-8')
        return range((len(data) + 1) // 2)

    def validate(self):
        if self.context_limit is not None:
            return
        if self.capacity is None:
            catalog = self.bridge.models(self.owner)
            selected = next((item for item in catalog if item['slug'] == self.slug), None)
            if selected is None:
                raise ProviderFailure('model_not_available_for_selected_account')
            self.capacity = resolve_capacity(selected)
        self.context_limit = self.capacity.context_window
        # App planning headroom, not an output-token request. The maximum
        # model output is a ceiling, not a desired answer length.
        self.reply_reserve = min(16_384, self.capacity.max_output_tokens,
                                 max(1, self.context_limit // 4))

    def _token(self):
        if self.binding is None:
            return self.bridge.access(self.owner)
        token, self.binding = self.bridge.access_bound(self.owner, self.binding)
        return token

    def verify_binding(self):
        if self.binding is not None and self.bridge.binding(self.owner) != self.binding:
            raise ProviderFailure('selected_account_changed')

    def create_completion(self, prompt, *, instructions=HOSTED, summary=False,
                          max_output_tokens=None, **_kwargs):
        self.validate()
        self.last_usage = None
        token = self._token()
        content = [{'type': 'input_text', 'text': prompt}]
        if self.chart_file and not summary:
            content.append(self.chart_file)
        body = {'model': self.slug, 'instructions': instructions,
                'input': [{'role': 'user', 'content': content}],
                'store': False, 'stream': True}
        if summary:
            body['max_output_tokens'] = max_output_tokens
        if not summary:
            body['tools'] = TOOLS
            body['parallel_tool_calls'] = False
            self._continuation_input = list(body['input'])
            self._instructions = instructions
        yield from self._events(token, body, summary)

    def estimate_read_continuation(self, outputs):
        """Conservative serialized-input estimate, not a provider token count."""
        if self._continuation_input is None:
            raise ValueError('No pending response to continue')
        serialized = json.dumps(self._continuation_input + outputs,
                                ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return (len(self.tokenize(serialized)) +
                len(self.tokenize((self._instructions + json.dumps(TOOLS)).encode())))

    def continue_completion(self, outputs):
        """Stateless provider continuation; outputs must already be durably archived."""
        if self._continuation_input is None or not outputs:
            raise ValueError('No pending function-call round')
        self._continuation_input.extend(outputs)
        body = {'model': self.slug, 'instructions': self._instructions,
                'input': self._continuation_input, 'tools': TOOLS,
                'parallel_tool_calls': False, 'store': False, 'stream': True}
        yield from self._events(self._token(), body, False)

    def _events(self, token, body, summary):
        self.last_usage = None  # last *response* input matters to the next compaction
        completed = False
        count = 0
        streamed_parts = []
        announced = _OutputItems()
        for item, request_id in self.bridge.transport.response_events(token, body):
            if not isinstance(item, dict):
                raise ProviderFailure('invalid_provider_stream', request_id=request_id)
            event_type = item.get('type')
            if event_type in ('response.output_item.added', 'response.output_item.done'):
                observed = item.get('item')
                if summary and isinstance(observed, dict) and observed.get('type') not in (
                        None, 'message', 'reasoning'):
                    raise ProviderFailure('summary_attempted_tool_call', request_id=request_id)
            if not summary:
                announced.observe(item, request_id)
            if event_type == 'response.output_text.delta':
                delta = item.get('delta', '')
                if not isinstance(delta, str):
                    raise ProviderFailure('invalid_provider_delta', request_id=request_id)
                count += len(delta.encode('utf-8'))
                streamed_parts.append(delta)
                if count > MAX_RESPONSE_TEXT_BYTES:
                    raise ProviderFailure('provider_output_exceeds_local_bound',
                                          request_id=request_id)
                if delta:
                    yield {'choices': [{'text': delta, 'finish_reason': None}]}
            elif event_type == 'response.completed':
                response = item.get('response') or {}
                if response.get('status') not in (None, 'completed'):
                    raise ProviderFailure('provider_incomplete', request_id=request_id)
                if summary and any(output.get('type') not in ('message', 'reasoning') for output in
                                   response.get('output', []) if isinstance(output, dict)):
                    raise ProviderFailure('summary_attempted_tool_call', request_id=request_id)
                usage = response.get('usage')
                if isinstance(usage, dict) and all(isinstance(usage.get(field), int) and
                        not isinstance(usage[field], bool) and usage[field] >= 0 for field in
                        ('input_tokens', 'output_tokens', 'total_tokens')) and usage['total_tokens'] > 0:
                    self.last_usage = {field: usage[field] for field in
                                       ('input_tokens', 'output_tokens', 'total_tokens')}
                if not summary:
                    final_output = response.get('output', [])
                    if (not isinstance(final_output, list) or len(final_output) > 8 or
                            len(json.dumps(final_output).encode()) > MAX_RESPONSE_FOOTER_BYTES):
                        raise ProviderFailure('invalid_provider_output', request_id=request_id)
                    output, output_error = announced.assemble(final_output)
                    diagnostic_output = final_output if output is None else output
                    calls = [entry for entry in diagnostic_output if isinstance(entry, dict) and
                             entry.get('type') == 'function_call']
                    kinds = [entry.get('type') if isinstance(entry, dict) else None
                             for entry in diagnostic_output]
                    kinds = [kind if kind in ('function_call', 'message', 'reasoning') else 'other'
                             for kind in kinds]

                    def reject(category):
                        call_ids = [entry.get('call_id') for entry in calls]
                        raise ProviderFailure('unsupported_provider_output', request_id=request_id,
                            diagnostic={'phase': 'completed_output', 'category': category,
                                        'output_kinds': kinds, 'output_items': len(diagnostic_output),
                                        'completed_calls': len(calls),
                                        'announced_calls': len(announced.calls),
                                        'streamed_completed_items': announced.completed_count,
                                        'footer_output_present': 'output' in response,
                                        'missing_call_id': any(not call_id for call_id in call_ids),
                                        'duplicate_call_id': len(set(map(str, call_ids))) < len(call_ids),
                                        'identifier_conflict': category == 'identifier_mismatch'})

                    if output_error:
                        reject(output_error)
                    if len(calls) > 1:
                        reject('multiple_calls')
                    if 'other' in kinds:
                        reject('unsupported_item')
                    ids = [entry.get('id') for entry in output if isinstance(entry.get('id'), str)]
                    if len(ids) != len(set(ids)):
                        reject('identifier_mismatch')
                    if len(json.dumps(output).encode('utf-8')) > MAX_RESPONSE_FOOTER_BYTES:
                        raise ProviderFailure('invalid_provider_output', request_id=request_id)
                    if any(entry.get('type') == 'message' and 'content' in entry and (
                           not isinstance(entry['content'], list) or
                           any(not isinstance(part, dict) or part.get('type') != 'output_text' or
                               not isinstance(part.get('text', ''), str)
                               for part in entry['content'])) for entry in output):
                        reject('unsupported_content_part')
                    completed_text = ''.join(part.get('text', '') for entry in output
                        if entry.get('type') == 'message' for part in entry.get('content', []))
                    streamed_text = ''.join(streamed_parts)
                    if not isinstance(completed_text, str) or (
                            completed_text and not completed_text.startswith(streamed_text)):
                        reject('text_mismatch')
                    if not calls and not (streamed_text or completed_text):
                        raise ProviderFailure('invalid_provider_output', request_id=request_id)
                    suffix = completed_text[len(streamed_text):] if completed_text else ''
                    if count + len(suffix.encode('utf-8')) > MAX_RESPONSE_TEXT_BYTES:
                        raise ProviderFailure('provider_output_exceeds_local_bound',
                                              request_id=request_id)
                    if suffix:
                        yield {'choices': [{'text': suffix, 'finish_reason': None}]}
                    if calls:
                        call = calls[0]
                        if (not isinstance(call.get('call_id'), str) or
                                not 1 <= len(call['call_id']) <= 80 or
                                not isinstance(call.get('name'), str) or
                                not isinstance(call.get('arguments'), str) or
                                len(call['arguments'].encode()) > 2048 or
                                not isinstance(call.get('id'), str) or
                                not all(c.isascii() and c.isprintable() for c in
                                        (call['call_id'], call['id'])) or
                                (not final_output and not _valid_read_arguments(
                                    call['name'], call['arguments']))):
                            raise ProviderFailure('invalid_provider_tool_call', request_id=request_id)
                        # Reasoning may be required for stateless continuation. Keep it
                        # transient: never put provider-internal content in archive events.
                        self._continuation_input.extend(output)
                        yield {'tool_call': {'call_id': call['call_id'], 'name': call['name'],
                                             'arguments': call['arguments']}}
                        completed = True
                        break
                completed = True
                break
            elif event_type in ('response.failed', 'response.incomplete', 'error'):
                error = (item.get('response') or {}).get('error') or item.get('error') or {}
                reason = error.get('code') if isinstance(error, dict) else None
                raise ProviderFailure(reason or event_type.replace('.', '_'),
                                      request_id=request_id)
        if not completed:
            raise ProviderFailure('provider_stream_ended_without_completion')
        if not summary and calls:
            return
        yield {'choices': [{'text': '', 'finish_reason': 'stop'}]}

    def close(self):
        pass  # Bridge owns the fixed HTTPS transport and its selected account.
