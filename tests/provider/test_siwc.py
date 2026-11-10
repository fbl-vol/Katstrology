"""Synthetic signed OIDC, grant, browser callback and Responses-only fixtures."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from starlette.testclient import TestClient

from m2.provider.responses import ResponsesModel
from m2.provider.siwc import (AUTHORIZE, ISSUER, RESOURCE, SCOPES, CredentialFiles,
                     ProviderBridge, ProviderFailure)
from tests.support.database import DatabaseCase, synthetic_web_dist
from m2.http_boundary.app import create_app


class FakeOpenAI:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.calls = []
        self.nonce = None
        self.permission = True
        self.subject = 'synthetic-openai-subject'
        self.audience = None
        self.events = [({'type': 'response.output_text.delta', 'delta': 'Synthetic provider response'}, 'req-fixture'),
                       ({'type': 'response.completed'}, 'req-fixture')]
        self.title_events = None
        self.title_gate = None
        self.title_started = Event()

    def jwks(self):
        public = self.key.public_key().public_numbers()
        from base64 import urlsafe_b64encode
        def b64(number):
            return urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, 'big')).rstrip(b'=').decode()
        return {'keys': [{'kid': 'fixture-key', 'kty': 'RSA', 'n': b64(public.n),
                          'e': b64(public.e), 'alg': 'RS256'}]}

    def token(self, data):
        self.calls.append(('token', data))
        if data['grant_type'] == 'refresh_token':
            return {'access_token': 'synthetic-access-rotated', 'token_type': 'Bearer',
                    'refresh_token': 'synthetic-refresh-rotated',
                    'expires_in': 3600, 'scope': SCOPES}
        claims = {'iss': ISSUER, 'aud': self.audience or data['client_id'], 'sub': self.subject,
                  'nonce': self.nonce, 'email': 'synthetic@example.invalid',
                  'iat': int(datetime.now(timezone.utc).timestamp()),
                  'exp': int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}
        identity = jwt.encode(claims, self.key, algorithm='RS256',
                              headers={'kid': 'fixture-key'})
        return {'id_token': identity, 'access_token': 'synthetic-access',
                'token_type': 'Bearer',
                'refresh_token': 'synthetic-refresh', 'expires_in': 3600,
                'scope': SCOPES if self.permission else 'openid profile email'}

    def models(self, token):
        self.calls.append(('models', token))
        return {'models': [{'slug': 'synthetic-response-model', 'display_name': 'Synthetic fixture',
                            'visibility': 'list', 'context_window': 500000,
                            'max_output_tokens': 128000}, {'slug': 'gpt-6.1-sol',
                            'display_name': 'Synthetic vision-capable Sol fixture',
                            'visibility': 'list'}, {'slug': 'gpt-6-luna',
                            'display_name': 'Synthetic Luna fixture',
                            'visibility': 'list'}, {'slug': 'hidden-model',
                            'display_name': 'Hidden', 'visibility': 'hidden'}]}

    def response_events(self, token, body):
        self.calls.append(('responses', token, body))
        if body.get('max_output_tokens') == 80:
            self.title_started.set()
            if self.title_gate is not None:
                self.title_gate.wait(timeout=5)
        yield from (self.title_events if body.get('max_output_tokens') == 80 and
                    self.title_events is not None else self.events)

    def revoke(self, refresh, client_id):
        self.calls.append(('revoke', refresh, client_id))

    def close(self):
        pass


class SiwcUnitTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='kat-siwc-synthetic-')
        self.transport = FakeOpenAI()
        self.bridge = ProviderBridge(Path(self.directory.name) / 'credentials', self.transport)
        self.callback = 'http://127.0.0.1:8765/auth/chatgpt/callback'

    def tearDown(self):
        self.bridge.close()
        self.directory.cleanup()

    def connect(self, owner='alice', client_id=None):
        state, url = self.bridge.begin(owner, 'synthetic-session-digest', self.callback, client_id)
        params = parse_qs(urlparse(url).query)
        self.transport.nonce = params['nonce'][0]
        result = self.bridge.complete(state, state, {'state': state, 'code': 'synthetic-code',
                    'client_id': 'oaiapp_synthetic'}, lambda _owner, _digest: True)
        return state, params, result

    def test_background_access_never_refreshes_or_waits_for_foreground_credentials(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        self.connect()
        binding = self.bridge.binding('alice')
        self.assertEqual(self.bridge.background_access('alice', binding), 'synthetic-access')
        entered, release = Event(), Event()

        def foreground_refresh():
            with self.bridge._owner_lock('alice'):
                entered.set()
                release.wait(5)

        with ThreadPoolExecutor(max_workers=1) as executor:
            held = executor.submit(foreground_refresh)
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(ProviderFailure) as unavailable:
                    self.bridge.background_access('alice', binding)
                self.assertEqual(unavailable.exception.reason, 'background_capacity_unavailable')
                self.assertFalse(held.done())
            finally:
                release.set()
        record = self.bridge.credentials.load('alice')
        record['accounts']['oaiapp_synthetic']['expires_at'] = 0
        self.bridge.credentials.save('alice', record)
        before = len(self.transport.calls)
        with self.assertRaises(ProviderFailure):
            self.bridge.background_access('alice', binding)
        self.assertEqual(len(self.transport.calls), before)

    def test_pkce_host_client_identity_scopes_refresh_and_account_isolation(self):
        first, params, result = self.connect()
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(params['resource'], [RESOURCE])
        self.assertEqual(params['client_id'], ['dynamic_agent_client'])
        self.assertIn('chatgpt.tokens.use.direct', params['scope'][0])
        self.assertTrue(params['ext_agent_host_id'][0].startswith('urn:uuid:'))
        self.assertEqual(self.transport.calls[0][1]['client_id'], 'oaiapp_synthetic')
        self.assertEqual(self.transport.calls[0][1]['redirect_uri'], self.callback)
        self.assertEqual(self.bridge.status('bob')['accounts'], [])
        self.assertEqual(self.bridge.models('alice'), [{'slug': 'synthetic-response-model',
                                                       'display_name': 'Synthetic fixture',
                                                       'context_window': 500000,
                                                       'max_output_tokens': 128000},
                                                      {'slug': 'gpt-6.1-sol',
                                                       'display_name': 'Synthetic vision-capable Sol fixture'},
                                                      {'slug': 'gpt-6-luna',
                                                       'display_name': 'Synthetic Luna fixture'}])
        record = self.bridge.credentials.load('alice')
        record['accounts']['oaiapp_synthetic']['expires_at'] = 0
        self.bridge.credentials.save('alice', record)
        self.assertEqual(self.bridge.access('alice'), 'synthetic-access-rotated')
        self.assertEqual(self.bridge.credentials.load('alice')['accounts']['oaiapp_synthetic']
                         ['refresh_token'], 'synthetic-refresh-rotated')
        _, returning, result = self.connect(client_id='oaiapp_synthetic')
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(returning['client_id'], ['oaiapp_synthetic'])
        self.assertNotIn('agent_name_hint', returning)
        self.assertEqual(returning['ext_agent_host_id'], params['ext_agent_host_id'])
        self.assertEqual(self.bridge.revoke('alice')['remote'], 'revoked')
        self.assertFalse(self.bridge.status('alice')['connected'])

    def test_connection_callback_cannot_overwrite_a_later_account_choice(self):
        self.connect()
        record = self.bridge.credentials.load('alice')
        record['accounts']['other-client'] = {**record['accounts']['oaiapp_synthetic'],
            'client_id': 'other-client', 'access_token': 'other-synthetic-access'}
        self.bridge.credentials.save('alice', record)
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
        entered, release = Event(), Event()
        original = self.transport.token

        def gated(data):
            if data['grant_type'] == 'authorization_code':
                entered.set()
                if not release.wait(timeout=15):
                    raise RuntimeError('Synthetic callback gate exceeded its watchdog')
            return original(data)

        self.transport.token = gated
        with ThreadPoolExecutor(max_workers=1) as callbacks:
            completion = callbacks.submit(self.bridge.complete, state, state,
                {'code': 'synthetic-code', 'client_id': 'oaiapp_synthetic'}, lambda *_: True)
            try:
                self.assertTrue(entered.wait(timeout=10))
                self.bridge.choose('alice', 'other-client')
            finally:
                release.set()
            with self.assertRaisesRegex(ValueError, 'Selected account changed'):
                completion.result(timeout=10)
        self.assertEqual(self.bridge.status('alice')['selected'], 'other-client')

    def test_simultaneous_access_refreshes_one_selected_account_once(self):
        self.connect()
        record = self.bridge.credentials.load('alice')
        record['accounts']['oaiapp_synthetic']['expires_at'] = 0
        self.bridge.credentials.save('alice', record)
        entered, release = Event(), Event()
        original = self.transport.token

        def gated(data):
            if data['grant_type'] == 'refresh_token':
                entered.set()
                if not release.wait(timeout=15):
                    raise RuntimeError('Synthetic refresh gate exceeded its watchdog')
            return original(data)

        self.transport.token = gated
        with ThreadPoolExecutor(max_workers=2) as requests:
            first = requests.submit(self.bridge.access, 'alice')
            try:
                self.assertTrue(entered.wait(timeout=10))
                second = requests.submit(self.bridge.access, 'alice')
            finally:
                release.set()
            self.assertEqual((first.result(timeout=10), second.result(timeout=10)),
                             ('synthetic-access-rotated', 'synthetic-access-rotated'))
        self.assertEqual(len([call for call in self.transport.calls if call[0] == 'token' and
                              call[1]['grant_type'] == 'refresh_token']), 1)

    def test_callback_replay_wrong_session_nonce_subject_and_declined_plan_fail_closed(self):
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
        with self.assertRaises(ValueError):
            self.bridge.complete(state, 'wrong-cookie', {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: True)
        with self.assertRaises(ValueError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: True)
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
        with self.assertRaises(ValueError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: False)
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = 'wrong-nonce'
        with self.assertRaises(ValueError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: True)
        self.assertEqual(self.bridge.status('alice')['accounts'], [])
        self.transport.permission = False
        _, _, result = self.connect()
        self.assertEqual(result['status'], 'identity_only')
        self.assertFalse(self.bridge.status('alice')['connected'])
        with self.assertRaises(ProviderFailure):
            self.bridge.access('alice')

    def test_signature_audience_and_returning_client_are_verified(self):
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
        honest_jwks = self.transport.jwks
        self.transport.jwks = FakeOpenAI().jwks
        with self.assertRaises(jwt.InvalidSignatureError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: True)
        self.transport.jwks = honest_jwks
        state, url = self.bridge.begin('alice', 'digest', self.callback)
        self.transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
        self.transport.audience = 'oaiapp_wrong_audience'
        with self.assertRaises(jwt.InvalidAudienceError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_synthetic'},
                                 lambda *_: True)
        self.transport.audience = None
        self.connect()
        state, url = self.bridge.begin('alice', 'digest', self.callback, 'oaiapp_synthetic')
        before = len(self.transport.calls)
        with self.assertRaises(ValueError):
            self.bridge.complete(state, state, {'code': 'test', 'client_id': 'oaiapp_other'},
                                 lambda *_: True)
        self.assertEqual(len(self.transport.calls), before)

    def test_responses_adapter_sends_supported_body_and_requires_terminal_completion(self):
        self.connect()
        model = ResponsesModel(self.bridge, 'alice', 'synthetic-response-model')
        self.assertEqual([event['choices'][0]['text'] for event in
                          model.create_completion('Synthetic bounded input')],
                         ['Synthetic provider response', ''])
        body = next(call[2] for call in self.transport.calls if call[0] == 'responses')
        self.assertEqual(body['model'], 'synthetic-response-model')
        self.assertEqual(body['store'], False)
        self.assertEqual(body['stream'], True)
        self.assertEqual(body['input'][0]['content'][0]['text'], 'Synthetic bounded input')
        self.assertFalse({'temperature', 'prompt', 'previous_response_id',
                          'max_output_tokens'} & body.keys())
        self.assertEqual(body['parallel_tool_calls'], False)
        self.assertEqual({tool['name'] for tool in body['tools']},
                         {'search_conversations', 'get_conversation_messages', 'get_conversation_message_page', 'get_chart',
                          'list_reference_sources', 'search_references', 'get_reference_passage',
                          'get_transit_view', 'get_transit_snapshot', 'find_transit_events',
                          'find_sky_events', 'compare_selected_charts',
                          'get_solar_return', 'get_lunar_returns', 'find_natal_mc_transits',
                          'get_secondary_progression', 'find_progressed_mc_contacts',
                          'get_midpoint_composite', 'get_uncorrected_davison',
                          'get_true_solar_arc', 'find_progressed_lunar_phases',
                          'find_actual_lunations_eclipses', 'get_planetary_returns',
                          'web_search', 'fetch_web_page', 'read_web_content'})
        self.transport.events = [({'type': 'response.output_text.delta', 'delta': 'Prefix'}, 'req-fixture')]
        with self.assertRaisesRegex(ProviderFailure, 'provider_stream_ended_without_completion'):
            list(model.create_completion('synthetic'))
        self.transport.events = [({'type': 'response.failed', 'response': {
            'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}}, 'req-fixture')]
        with self.assertRaisesRegex(ProviderFailure, 'subscription_sharing_usage_limit_exceeded'):
            list(model.create_completion('synthetic'))


class SiwcHttpTests(DatabaseCase):
    def test_browser_first_substantive_title_is_separate_and_manual_rename_wins(self):
        self.store.close()
        with TemporaryDirectory(prefix='kat-title-web-') as directory:
            transport = FakeOpenAI()
            transport.title_events = [({'type': 'response.output_text.delta',
                                        'delta': 'Natal chart questions'}, 'title-request'),
                                      ({'type': 'response.completed'}, 'title-request')]
            bridge = ProviderBridge(Path(directory) / 'private', transport)
            state, url = bridge.begin('alice', 'synthetic-session',
                                      'http://127.0.0.1:8765/auth/chatgpt/callback')
            transport.nonce = parse_qs(urlparse(url).query)['nonce'][0]
            bridge.complete(state, state, {'state': state, 'code': 'synthetic-code',
                                           'client_id': 'oaiapp_synthetic'}, lambda *_: True)
            dist = Path(directory) / 'isolated-dist'
            dist.mkdir()
            (dist / 'index.html').write_text('<!doctype html><title>synthetic fixture</title>')
            app = create_app(self.dsn, Path(directory) / 'files', Path(directory) / 'ledger',
                             dist, siwc_factory=lambda _: bridge)
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                origin = {'Origin': 'http://127.0.0.1:8765'}
                login = client.post('/api/login', json={'username': 'alice',
                                    'password': 'synthetic-password-alice'}, headers=origin)
                headers = {**origin, 'X-Kat-CSRF': login.json()['csrf']}
                created = client.post('/api/conversations', json={
                    'id': 'titles', 'title': 'New conversation', 'people': []}, headers=headers)
                self.assertEqual(created.status_code, 201)
                def send(turn, text):
                    result = client.post('/api/conversations/titles/turns', json={
                        'id': turn, 'text': text, 'selected_people': [], 'parent': '@active',
                        'revision_kind': 'normal', 'replaces_turn_id': None}, headers=headers)
                    self.assertEqual(result.status_code, 202, result.text)
                    complete = client.get(f'/api/conversations/titles/turns/{turn}/events')
                    self.assertIn('"kind": "complete"', complete.text)
                send('hello', 'Hello!')
                self.assertFalse(transport.title_started.is_set())
                send('question', 'How do I understand the natal chart?')
                self.assertTrue(transport.title_started.wait(timeout=3))
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    thread = client.get('/api/conversations/titles').json()
                    if thread['title_status'] == 'generated':
                        break
                    time.sleep(0.05)
                self.assertEqual(thread['title'], 'Natal chart questions')
                title_calls = [item[2] for item in transport.calls if item[0] == 'responses' and
                               item[2].get('max_output_tokens') == 80]
                self.assertEqual(len(title_calls), 1)
                self.assertEqual(title_calls[0]['model'], 'gpt-6-luna')
                self.assertEqual(title_calls[0]['store'], False)
                self.assertNotIn('tools', title_calls[0])
                self.assertNotIn('Hello!', str(title_calls[0]['input']))
                self.assertEqual(client.patch('/api/conversations/titles', json={
                    'title': 'Chosen by the reader'}, headers=headers).status_code, 200)
                self.assertEqual(client.get('/api/conversations/titles').json()['title_origin'], 'manual')

                transport.title_started.clear()
                transport.title_gate = Event()
                client.post('/api/conversations', json={
                    'id': 'race', 'title': 'New conversation', 'people': []}, headers=headers)
                answer = client.post('/api/conversations/race/turns', json={
                    'id': 'question', 'text': 'Can we compare planetary positions?',
                    'selected_people': [], 'parent': '@active', 'revision_kind': 'normal',
                    'replaces_turn_id': None}, headers=headers)
                self.assertEqual(answer.status_code, 202)
                self.assertIn('"kind": "complete"',
                              client.get('/api/conversations/race/turns/question/events').text)
                self.assertTrue(transport.title_started.wait(timeout=3))
                renamed = client.patch('/api/conversations/race', json={
                    'title': 'My deliberate title'}, headers=headers)
                self.assertEqual(renamed.status_code, 200)
                transport.title_gate.set()
                self.assertEqual(client.get('/api/conversations/race').json()['title'],
                                 'My deliberate title')
            bridge.close()

    def test_local_session_bound_callback_and_fixture_only_provider_archive(self):
        self.store.close()
        with TemporaryDirectory(prefix='kat-siwc-web-') as directory:
            transport = FakeOpenAI()
            app = create_app(self.dsn, Path(directory) / 'files', Path(directory) / 'ledger',
                             synthetic_web_dist(directory),
                             siwc_factory=lambda root: ProviderBridge(root, transport),
                             siwc_root=Path(directory) / 'private')
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                login = client.post('/api/login', json={'username': 'alice',
                    'password': 'synthetic-password-alice'},
                    headers={'Origin': 'http://127.0.0.1:8765'})
                csrf = login.json()['csrf']
                self.assertEqual(client.get('/').headers['referrer-policy'], 'same-origin')
                self.assertEqual(client.get('/index.html').headers['referrer-policy'], 'same-origin')
                self.assertEqual(client.get('/api/siwc/status').headers['referrer-policy'], 'no-referrer')
                landing = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                           'Sec-Fetch-Dest': 'document'}
                self.assertEqual(client.get('/', headers=landing).status_code, 200)
                self.assertEqual(client.get('/?connection=connected', headers=landing).status_code, 200)
                self.assertEqual(client.get('/', headers={**landing,
                    'Host': 'localhost:8765'}).status_code, 403)
                self.assertEqual(client.get('/index.html', headers=landing).status_code, 403)
                self.assertEqual(client.get('/api/siwc/status', headers=landing).status_code, 403)
                self.assertEqual(client.get('/', headers={**landing,
                    'Sec-Fetch-Dest': 'empty'}).status_code, 403)
                self.assertEqual(client.get('/', headers={**landing,
                    'Origin': 'null'}).status_code, 403)
                self.assertEqual(client.post('/api/siwc/select', json={'client_id': 'bogus'},
                    headers={**landing, 'Origin': 'null', 'X-Kat-CSRF': csrf}).status_code, 403)
                form = {'csrf': csrf, 'client_id': ''}
                for headers in ({'Origin': 'null'}, {'Origin': 'http://127.0.0.1:8766'}, {}):
                    denied = client.post('/auth/chatgpt/start', data=form, headers=headers,
                                         follow_redirects=False)
                    self.assertEqual(denied.status_code, 403)
                    self.assertEqual(denied.json(), {'error': 'local_origin_required'})
                self.assertEqual(client.post('/auth/chatgpt/start', data=form,
                    headers={'Origin': 'http://127.0.0.1:8765', 'Host': 'localhost:8765'},
                    follow_redirects=False).status_code, 403)
                self.assertEqual(client.post('/auth/chatgpt/start', data={'csrf': 'wrong', 'client_id': ''},
                    headers={'Origin': 'http://127.0.0.1:8765'},
                    follow_redirects=False).status_code, 403)
                started = client.post('/auth/chatgpt/start', data=form,
                    headers={'Origin': 'http://127.0.0.1:8765'}, follow_redirects=False)
                self.assertEqual(started.status_code, 303)
                self.assertEqual(started.headers['referrer-policy'], 'no-referrer')
                self.assertTrue(started.headers['location'].startswith(AUTHORIZE))
                params = parse_qs(urlparse(started.headers['location']).query)
                state = params['state'][0]
                transport.nonce = params['nonce'][0]
                blocked = client.get('/auth/chatgpt/callback', params={'state': state,
                    'code': 'synthetic-code', 'client_id': 'oaiapp_synthetic'},
                    headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'cors',
                             'Sec-Fetch-Dest': 'empty'}, follow_redirects=False)
                self.assertEqual(blocked.status_code, 403)
                callback = client.get('/auth/chatgpt/callback', params={'state': state,
                    'code': 'synthetic-code', 'client_id': 'oaiapp_synthetic'},
                    headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                             'Sec-Fetch-Dest': 'document'}, follow_redirects=False)
                self.assertEqual(callback.headers['location'], '/?connection=connected')
                self.assertEqual(callback.headers['referrer-policy'], 'no-referrer')
                self.assertTrue(client.get('/api/siwc/status').json()['connected'])
                self.assertEqual(client.get('/api/siwc/models').json()['models'][0]['slug'],
                                 'synthetic-response-model')
                archive = client.post('/api/conversations', json={
                    'id': 'synthetic-thread', 'title': 'Synthetic', 'people': []},
                    headers={'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': csrf})
                self.assertEqual(archive.status_code, 201)
                sent = client.post('/api/conversations/synthetic-thread/turns', json={
                    'id': 'synthetic-turn', 'text': 'Synthetic provider request',
                    'selected_people': [], 'parent': '@active', 'revision_kind': 'normal',
                    'replaces_turn_id': None}, headers={
                    'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': csrf})
                self.assertEqual(sent.status_code, 202, sent.text)
                events = client.get('/api/conversations/synthetic-thread/turns/synthetic-turn/events')
                self.assertIn('Synthetic provider response', events.text)
                self.assertIn('"model_provider": "chatgpt_plan"', events.text)
                transport.events = [({'type': 'response.output_text.delta',
                                      'delta': 'Committed provider prefix'}, 'req-fixture'),
                                    ({'type': 'response.failed', 'response': {'error': {
                                      'code': 'subscription_sharing_usage_limit_exceeded'}}},
                                     'req-fixture')]
                failed = client.post('/api/conversations/synthetic-thread/turns', json={
                    'id': 'limit-turn', 'text': 'Synthetic quota fixture',
                    'selected_people': [], 'parent': '@active', 'revision_kind': 'normal',
                    'replaces_turn_id': None}, headers={
                    'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': csrf})
                self.assertEqual(failed.status_code, 202)
                failure_events = client.get('/api/conversations/synthetic-thread/turns/limit-turn/events')
                self.assertIn('Committed provider prefix', failure_events.text)
                self.assertIn('subscription_sharing_usage_limit_exceeded', failure_events.text)
                self.assertIn('"request_id": "req-fixture"', failure_events.text)
                self.assertEqual(client.post('/api/siwc/disconnect', headers={
                    'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': csrf}).json()['status'],
                    'disconnected')
                self.assertEqual(client.get('/api/siwc/status').json()['connected'], False)


if __name__ == '__main__':
    unittest.main()
