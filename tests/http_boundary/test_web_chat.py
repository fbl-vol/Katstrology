"""Owned HTTP archive ACK, committed SSE replay and reconnect/cancel boundaries."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import json
import time
import unittest

from starlette.testclient import TestClient

from m2.provider.siwc import ProviderBridge
from tests.provider.test_siwc import FakeOpenAI
from tests.support.database import DatabaseCase, synthetic_web_dist
from m2.http_boundary.app import create_app


class ChatHttpFixture(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.directory_http = TemporaryDirectory(prefix='kat-chat-http-')
        self.transport = FakeOpenAI()
        self.app = create_app(self.dsn, Path(self.directory_http.name) / 'files',
                              Path(self.directory_http.name) / 'ledger.jsonl',
                              synthetic_web_dist(self.directory_http.name),
                              siwc_factory=lambda root: ProviderBridge(root, self.transport))
        self.store.close()
        self.client_context = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.client = self.client_context.__enter__()
        self.login('alice', 'synthetic-password-alice')
        self.app.state.runtime.siwc.credentials.save('alice', {
            'selected': 'oaiapp_synthetic', 'accounts': {'oaiapp_synthetic': {
                'scopes': ['chatgpt.tokens.use.direct'], 'access_token': 'synthetic-access',
                'refresh_token': 'synthetic-refresh', 'expires_at': time.time() + 1800}}})

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory_http.cleanup()
        super().tearDown()

    def login(self, owner, password):
        response = self.client.post('/api/login', json={'username': owner, 'password': password},
                                    headers={'Origin': 'http://127.0.0.1:8765'})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']

    def post(self, path, value=None):
        return self.client.post(path, json=value or {}, headers={
            'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': self.csrf})

    def message(self, turn_id='first', text='Synthetic browser question'):
        return {'id': turn_id, 'text': text, 'selected_people': [],
                'parent': '@active', 'revision_kind': 'normal', 'replaces_turn_id': None}

    def events(self, turn_id='first', after=-1):
        response = self.client.get(f'/api/conversations/thread/turns/{turn_id}/events?after={after}')
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line.removeprefix('data: ')) for line in response.text.splitlines()
                if line.startswith('data: ')]

    def responses(self):
        return [call for call in self.transport.calls if call[0] == 'responses']


class ChatHttpTests(ChatHttpFixture):
    def test_committed_ack_reconnect_cursor_retry_and_owner_scope(self):
        created = self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        self.assertEqual(created.status_code, 201)
        payload = self.message()
        ack = self.post('/api/conversations/thread/turns', payload)
        self.assertEqual(ack.status_code, 202, ack.text)
        self.assertEqual(ack.json()['acknowledged'], True)
        all_events = self.events()
        self.assertEqual([e['kind'] for e in all_events],
                         ['user', 'context', 'assistant_chunk', 'complete'])
        self.assertEqual([e['sequence'] for e in self.events(after=1)], [2, 3])
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        self.assertEqual(len(self.responses()), 1)
        self.assertEqual(len([call for call in self.transport.calls if call[0] == 'models']), 1)
        self.assertEqual(self.post('/api/conversations/thread/turns',
                                   {**payload, 'text': 'Changed'}).status_code, 400)
        archive = self.post('/api/conversations/thread/export')
        self.assertEqual(archive.status_code, 200)
        self.assertIn('Synthetic browser question', archive.text)
        self.login('bob', 'synthetic-password-bob')
        self.assertEqual(self.client.get('/api/conversations/thread/turns/first/events').status_code,
                         404)
        self.assertEqual(self.post('/api/conversations/thread/turns/first/cancel').status_code, 404)
        self.assertEqual(self.post('/api/conversations/thread/export').status_code, 404)

    def test_full_utf8_message_and_correction_fit_escaped_http_envelopes(self):
        self.assertEqual(self.post('/api/conversations', {
            'id': 'thread', 'title': 'Synthetic thread', 'people': []}).status_code, 201)
        text = 'Q' + '\t' * (64 * 1024 - 1)
        payload = self.message('escaped-input', text)
        self.assertEqual(len(text.encode('utf-8')), 64 * 1024)
        self.assertGreater(len(json.dumps(payload).encode('utf-8')), 128 * 1024)
        ack = self.post('/api/conversations/thread/turns', payload)
        self.assertEqual(ack.status_code, 202, ack.text)
        self.assertEqual(self.events('escaped-input')[-1]['kind'], 'complete')
        saved = self.client.get('/api/conversations/thread/turns/escaped-input').json()
        self.assertEqual(saved['events'][0]['payload']['content'], text)
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        self.assertEqual(len(self.responses()), 1)
        self.assertEqual(self.post('/api/conversations/thread/turns',
                                   self.message('too-long', text + '\t')).status_code, 400)
        self.assertEqual(self.client.get('/api/conversations/thread/turns/too-long').status_code, 404)

        replacement = 'R' + '\x01' * (64 * 1024 - 1)
        correction = {'id': 'fix-escaped', 'source_turn': 'escaped-input',
                      'action': 'correct', 'replacement': replacement}
        self.assertGreater(len(json.dumps(correction).encode('utf-8')), 128 * 1024)
        self.assertEqual(self.post('/api/conversations/thread/corrections', correction).status_code, 200)
        saved = self.client.get('/api/conversations/thread/turns/escaped-input').json()
        self.assertEqual(saved['corrections'][-1]['replacement'], replacement)
        self.assertEqual(self.post('/api/conversations/thread/corrections', {
            **correction, 'id': 'too-long-correction', 'replacement': replacement + '\x01'}).status_code, 400)
        self.assertEqual(len(self.client.get('/api/conversations/thread/turns/escaped-input')
                             .json()['corrections']), 1)
        no_csrf = self.client.post('/api/conversations/thread/corrections', json=correction,
                                   headers={'Origin': 'http://127.0.0.1:8765'})
        self.assertEqual(no_csrf.status_code, 403)
        self.login('bob', 'synthetic-password-bob')
        self.assertEqual(self.client.get('/api/conversations/thread/turns/escaped-input').status_code,
                         404)

    def test_invalid_capacity_and_revoked_permission_reject_before_archive(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        original = self.transport.models

        def malformed(token):
            catalog = original(token)
            next(row for row in catalog['models'] if row['slug'] == 'gpt-6-luna')[
                'context_window'] = 'untrusted-large-window'
            return catalog

        self.transport.models = malformed
        response = self.post('/api/conversations/thread/turns', self.message('invalid-capacity'))
        self.assertEqual((response.status_code, response.json()['error']),
                         (409, 'fixed_model_unavailable'))
        record = self.app.state.runtime.siwc.credentials.load('alice')
        record['accounts']['oaiapp_synthetic']['scopes'] = []
        self.app.state.runtime.siwc.credentials.save('alice', record)
        response = self.post('/api/conversations/thread/turns', self.message('revoked'))
        self.assertEqual((response.status_code, response.json()['error']),
                         (409, 'chatgpt_plan_permission_required'))
        self.assertEqual(self.client.get('/api/conversations/thread/turns').json()['turns'], [])
        self.assertEqual(len(self.responses()), 0)

    def test_missing_luna_never_falls_back_to_available_sol(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        original = self.transport.models

        def sol_only(token):
            catalog = original(token)
            catalog['models'] = [row for row in catalog['models'] if row['slug'] != 'gpt-6-luna']
            return catalog

        self.transport.models = sol_only
        response = self.post('/api/conversations/thread/turns', self.message('no-luna'))
        self.assertEqual((response.status_code, response.json()['error']),
                         (409, 'fixed_model_unavailable'))
        self.assertEqual(self.client.get('/api/conversations/thread/turns').json()['turns'], [])
        self.assertEqual(self.responses(), [])

    def test_gated_catalog_does_not_hold_store_or_grant_another_owner(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()
        original = self.transport.models

        def gated(token):
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError('Synthetic catalog gate exceeded its watchdog')
            return original(token)

        self.transport.models = gated
        with ThreadPoolExecutor(max_workers=1) as requests:
            pending = requests.submit(self.post, '/api/conversations/thread/turns', self.message())
            try:
                self.assertTrue(entered.wait(timeout=10))
                self.assertEqual(self.client.get('/api/conversations/thread/turns').json()['turns'], [])
                self.login('bob', 'synthetic-password-bob')
                self.assertEqual(self.client.get('/api/conversations/thread').status_code, 404)
                self.assertFalse(pending.done())
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=10).status_code, 202)
        self.login('alice', 'synthetic-password-alice')
        self.assertEqual(self.events()[-1]['kind'], 'complete')
        self.assertEqual(len([call for call in self.transport.calls if call[0] == 'models']), 1)
        self.assertEqual(len(self.responses()), 1)

    def test_gated_provider_cannot_starve_authorized_store_reads(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()
        original = self.transport.response_events

        def gated(token, body):
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError('Synthetic provider gate exceeded its watchdog')
            yield from original(token, body)

        self.transport.response_events = gated
        with ThreadPoolExecutor(max_workers=1) as requests:
            ack = self.post('/api/conversations/thread/turns', self.message())
            self.assertEqual(ack.status_code, 202, ack.text)
            try:
                self.assertTrue(entered.wait(timeout=10))
                authorized_read = requests.submit(self.client.get, '/api/conversations/thread/turns')
                self.assertEqual(authorized_read.result(timeout=8).json()['turns'][0]['id'], 'first')
                self.login('bob', 'synthetic-password-bob')
                self.assertEqual(self.client.get('/api/conversations/thread').status_code, 404)
                self.assertFalse(release.is_set())
            finally:
                release.set()
        self.login('alice', 'synthetic-password-alice')
        self.assertEqual(self.events()[-1]['kind'], 'complete')
        self.assertEqual(len(self.responses()), 1)

    def test_release_fences_effectful_get_and_new_send_without_cancelling_accepted_turn(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()
        original = self.transport.response_events

        def gated(token, body):
            entered.set()
            if not release.wait(15):
                raise RuntimeError('Synthetic release gate watchdog')
            yield from original(token, body)

        self.transport.response_events = gated
        payload = self.message()
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        gate = self.app.state.runtime.admission
        try:
            self.assertTrue(entered.wait(8))
            result = self.client.portal.call(gate.drain, 'd' * 32, 0.02)
            self.assertEqual(result['phase'], 'fenced')
            before = len(self.transport.calls)
            for response in (self.client.get('/api/siwc/models'),
                             self.post('/api/conversations/thread/turns', self.message('late'))):
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'error': 'release_maintenance'})
            self.assertEqual(len(self.transport.calls), before)
            self.assertFalse(self.app.state.runtime.chat.jobs[('alice', 'thread', 'first')].cancel.is_set())
        finally:
            release.set()
            self.client.portal.call(gate.resume, 'd' * 32)
        self.assertEqual(self.events()[-1]['kind'], 'complete')
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        self.assertEqual(len(self.responses()), 1)

    def test_first_nonempty_word_commits_before_provider_resumes(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()

        def waiting(token, body):
            self.transport.calls.append(('responses', token, body))
            yield {'type': 'response.output_text.delta', 'delta': 'Hello'}, 'req-fixture'
            entered.set()
            if not release.wait(timeout=12):
                raise RuntimeError('Synthetic first-word gate exceeded its watchdog')
            yield {'type': 'response.completed'}, 'req-fixture'

        self.transport.response_events = waiting
        ack = self.post('/api/conversations/thread/turns', self.message())
        self.assertEqual(ack.status_code, 202, ack.text)
        try:
            self.assertTrue(entered.wait(timeout=8))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                archived = self.client.get('/api/conversations/thread/turns/first').json()
                if any(event['kind'] == 'assistant_chunk' and event['payload']['content'] == 'Hello'
                       for event in archived['events']):
                    break
                time.sleep(0.03)
            else:
                self.fail('First validated word did not commit before synthetic provider resumed')
            self.assertFalse(release.is_set())
        finally:
            release.set()
        self.assertEqual(self.events()[-1]['kind'], 'complete')

    def test_later_small_deltas_flush_on_timer_while_provider_stalls(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()

        def waiting(token, body):
            self.transport.calls.append(('responses', token, body))
            for text in ('Hello', ' there', ' friend'):
                yield {'type': 'response.output_text.delta', 'delta': text}, 'req-fixture'
            entered.set()
            if not release.wait(timeout=12):
                raise RuntimeError('Synthetic later-word gate exceeded its watchdog')
            yield {'type': 'response.completed'}, 'req-fixture'

        self.transport.response_events = waiting
        ack = self.post('/api/conversations/thread/turns', self.message())
        self.assertEqual(ack.status_code, 202, ack.text)
        try:
            self.assertTrue(entered.wait(timeout=8))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                events = self.client.get('/api/conversations/thread/turns/first').json()['events']
                words = ''.join(e['payload']['content'] for e in events if e['kind'] == 'assistant_chunk')
                if words == 'Hello there friend':
                    break
                time.sleep(0.03)
            else:
                self.fail('Batched later text was not durably flushed while provider waited')
            self.assertEqual([e['payload']['content'] for e in events
                              if e['kind'] == 'assistant_chunk'], ['Hello', ' there friend'])
            self.assertFalse(release.is_set())
        finally:
            release.set()
        self.assertEqual(self.events()[-1]['kind'], 'complete')
        self.assertEqual(len(self.responses()), 1)

    def test_provider_error_flushes_batched_suffix_before_terminal_error(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})

        def incomplete(token, body):
            self.transport.calls.append(('responses', token, body))
            for text in ('Hello', ' later'):
                yield {'type': 'response.output_text.delta', 'delta': text}, 'req-fixture'
            yield {'type': 'response.failed', 'response': {'error': {'code': 'synthetic_failure'}}}, 'req-fixture'

        self.transport.response_events = incomplete
        self.assertEqual(self.post('/api/conversations/thread/turns', self.message()).status_code, 202)
        events = self.events()
        self.assertEqual([e['payload']['content'] for e in events if e['kind'] == 'assistant_chunk'],
                         ['Hello', ' later'])
        self.assertEqual(events[-1]['kind'], 'error')
        self.assertEqual(events[-1]['payload']['reason'], 'synthetic_failure')
        self.assertEqual(len(self.responses()), 1)

    def test_late_account_switch_drops_old_provider_output_without_rerun(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        bridge = self.app.state.runtime.siwc
        record = bridge.credentials.load('alice')
        record['accounts']['other-client'] = {**record['accounts']['oaiapp_synthetic'],
            'access_token': 'other-synthetic-access'}
        bridge.credentials.save('alice', record)
        entered, release = Event(), Event()
        original = self.transport.response_events

        def gated(token, body):
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError('Synthetic provider gate exceeded its watchdog')
            yield from original(token, body)

        self.transport.response_events = gated
        ack = self.post('/api/conversations/thread/turns', self.message())
        self.assertEqual(ack.status_code, 202, ack.text)
        try:
            self.assertTrue(entered.wait(timeout=10))
            self.assertEqual(self.post('/api/siwc/select', {'client_id': 'other-client'}).status_code, 200)
        finally:
            release.set()
        events = self.events()
        self.assertEqual(events[-1]['kind'], 'error')
        self.assertEqual(events[-1]['payload']['reason'], 'selected_account_changed')
        self.assertNotIn('assistant_chunk', [event['kind'] for event in events])
        self.assertEqual(len(self.responses()), 1)

    def test_account_change_during_catalog_rejects_before_archive(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        bridge = self.app.state.runtime.siwc
        record = bridge.credentials.load('alice')
        record['accounts']['other-client'] = {**record['accounts']['oaiapp_synthetic'],
            'access_token': 'other-synthetic-access', 'refresh_token': 'other-synthetic-refresh'}
        bridge.credentials.save('alice', record)
        entered, release = Event(), Event()
        original = self.transport.models

        def gated(token):
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError('Synthetic catalog gate exceeded its watchdog')
            return original(token)

        self.transport.models = gated
        with ThreadPoolExecutor(max_workers=1) as requests:
            pending = requests.submit(self.post, '/api/conversations/thread/turns', self.message())
            try:
                self.assertTrue(entered.wait(timeout=10))
                changed = self.post('/api/siwc/select', {'client_id': 'other-client'})
                self.assertEqual(changed.status_code, 200, changed.text)
                self.assertFalse(pending.done())
            finally:
                release.set()
            response = pending.result(timeout=10)
        self.assertEqual((response.status_code, response.json()['error']),
                         (409, 'selected_account_changed'))
        self.assertEqual(self.client.get('/api/conversations/thread/turns').json()['turns'], [])
        self.assertEqual(len(self.responses()), 0)

    def test_inference_error_preserves_user_and_prefix_without_rerun(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        self.transport.events = [({'type': 'response.output_text.delta',
                                   'delta': 'Archived prefix'}, 'req-fixture'),
                                 ({'type': 'response.failed', 'response': {'error': {
                                     'code': 'synthetic_provider_failure'}}}, 'req-fixture')]
        payload = self.message('failure')
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        kinds = [e['kind'] for e in self.events('failure')]
        self.assertEqual(kinds, ['user', 'context', 'assistant_chunk', 'error'])
        self.assertEqual(len(self.responses()), 1)
        self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
        self.assertEqual(len(self.responses()), 1)
        self.assertIn('synthetic_provider_failure', json.dumps(self.events('failure')))

    def test_cancellation_auth_and_no_unsaved_delivery(self):
        self.post('/api/conversations', {'id': 'thread', 'title': 'Synthetic thread', 'people': []})
        entered, release = Event(), Event()
        def waiting(token, body):
            self.transport.calls.append(('responses', token, body))
            yield {'type': 'response.output_text.delta', 'delta': 'Committed'}, 'req-fixture'
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError('fixture timed out')
            yield {'type': 'response.output_text.delta', 'delta': 'Should not appear'}, 'req-fixture'
            yield {'type': 'response.completed'}, 'req-fixture'
        self.transport.response_events = waiting
        try:
            payload = self.message('cancelled')
            self.assertEqual(self.post('/api/conversations/thread/turns', payload).status_code, 202)
            self.assertTrue(entered.wait(timeout=8))
            self.assertEqual(self.client.get('/api/conversations/thread/turns').status_code, 200)
            self.assertEqual(self.client.post(
                '/api/conversations/thread/turns/cancelled/cancel',
                headers={'Origin': 'http://127.0.0.1:8765'}).status_code, 403)
            cancelled = self.post('/api/conversations/thread/turns/cancelled/cancel')
            self.assertEqual(cancelled.json()['status'], 'cancellation_requested')
        finally:
            release.set()
        events = self.events('cancelled')
        self.assertEqual([e['kind'] for e in events][-1], 'interrupted')
        self.assertNotIn('Should not appear', json.dumps(events))
        retry = self.post('/api/conversations/thread/turns', payload)
        self.assertEqual(retry.status_code, 202)
        self.assertEqual(retry.json()['turn']['id'], 'cancelled')
        self.assertEqual(len(self.responses()), 1)


if __name__ == '__main__':
    unittest.main()
