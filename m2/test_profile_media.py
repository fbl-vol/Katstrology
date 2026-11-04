"""Retired person files remain archived evidence, never a new model input."""

from pathlib import Path
from time import time

from psycopg.types.json import Jsonb
from starlette.testclient import TestClient

from m2.siwc import ProviderBridge
from m2.test_siwc import FakeOpenAI
from m2.test_support import DatabaseCase, seed_legacy_person_file, synthetic_web_dist
from m2.web_server import create_app

ORIGIN = 'http://127.0.0.1:8765'


class RetiredPersonMediaTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.store.close()
        self.transport = FakeOpenAI()
        self.app = create_app(self.dsn, Path(self.directory.name) / 'files',
                              Path(self.directory.name) / 'deletions.jsonl',
                              synthetic_web_dist(self.directory.name),
                              siwc_factory=lambda root: ProviderBridge(root, self.transport),
                              siwc_root=Path(self.directory.name) / 'private')
        self.client_context = TestClient(self.app, base_url=ORIGIN)
        self.client = self.client_context.__enter__()
        self.app.state.runtime.siwc.credentials.save('alice', {
            'selected': 'synthetic-client', 'accounts': {'synthetic-client': {
                'scopes': ['chatgpt.tokens.use.direct'], 'access_token': 'synthetic-only',
                'refresh_token': 'synthetic-only', 'expires_at': time() + 3600}}})
        login = self.client.post('/api/login', json={
            'username': 'alice', 'password': 'synthetic-password-alice'}, headers={'Origin': ORIGIN})
        self.assertEqual(login.status_code, 200, login.text)
        self.csrf = login.json()['csrf']

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        super().tearDown()

    def post(self, path, payload):
        return self.client.post('/api/' + path, json=payload, headers={
            'Origin': ORIGIN, 'X-Kat-CSRF': self.csrf})

    def test_retained_file_turn_replays_without_reading_bytes_or_sending_again(self):
        person = self.post('people', {'name': 'Synthetic legacy person'}).json()
        self.assertEqual(self.post('conversations', {'id': 'thread', 'title': 'Synthetic archive',
                                                     'people': [person['id']]}).status_code, 201)
        file_id = 'old-chart'
        legacy_file = {'person_id': person['id'], 'attachment_id': file_id, 'consent': True}
        text = 'An older archived question'

        def seed(store, auth):
            session = auth.owners['alice']
            seed_legacy_person_file(store, session, person['id'], file_id, 'old-chart.pdf',
                                    b'%PDF-1.4\nSynthetic retained bytes')
            store.begin(session, 'thread', 'old-file', text, parent_id=None,
                        selected_people=[{'person_id': person['id'], 'chart_id': None}],
                        model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
            with store.db.transaction():
                store.db.execute('''
                    UPDATE events SET payload=jsonb_set(payload, '{chart_file}', %s)
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND sequence=0
                ''', (Jsonb(legacy_file), 'alice', 'thread', 'old-file'))
                store.db.execute('''
                    UPDATE turn_people SET attachment_id=%s
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND person_id=%s
                ''', (file_id, 'alice', 'thread', 'old-file', person['id']))
            store.append(session, 'thread', 'old-file', 'assistant_chunk', {'content': 'Archived answer'})
            store.append(session, 'thread', 'old-file', 'complete', {})
        self.client.portal.call(self.app.state.runtime.call, seed)

        url = 'conversations/thread/turns'
        old = {'id': 'old-file', 'text': text, 'selected_people': [
            {'person_id': person['id'], 'chart_id': None}], 'parent': '@root',
            'revision_kind': 'normal', 'replaces_turn_id': None,
            'mode': 'chatgpt', 'model_slug': 'gpt-6.1-sol', 'chart_file': legacy_file}
        record = self.client.get('/api/' + url + '/old-file').json()
        self.assertEqual(record['selected_people'][0]['attachment_id'], file_id)
        self.assertEqual(record['events'][0]['payload']['chart_file'], legacy_file)
        self.assertNotIn('attachments', self.client.get('/api/people/' + person['id']).json())
        self.app.state.runtime.siwc.credentials.save('alice', {'selected': None, 'accounts': {}})
        self.assertEqual(self.post(url, old).status_code, 202)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.client.get('/api/' + url + '/old-file').json()['events'], record['events'])
        self.assertEqual(self.post(url, {**old, 'chart_file': None}).status_code, 400)
        self.assertEqual(self.post(url, {**old, 'id': 'new-file'}).status_code, 400)
        self.assertEqual(self.client.get(f"/api/people/{person['id']}/files/{file_id}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/people/{person['id']}/files/{file_id}",
                                           headers={'Origin': ORIGIN, 'X-Kat-CSRF': self.csrf}).status_code, 405)
        self.assertEqual(self.transport.calls, [])

    def test_store_rejects_new_person_file_even_outside_browser(self):
        def attempt(store, auth):
            session = auth.owners['alice']
            from m2.people import People
            person = People(store).add(session, 'Synthetic person')
            store.create_conversation(session, 'thread')
            with self.assertRaisesRegex(ValueError, 'New turns cannot attach person files'):
                store.begin(session, 'thread', 'new-file', 'Send file', parent_id=None,
                            selected_people=[{'person_id': person['id'], 'chart_id': None}],
                            model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                            chart_file={'person_id': person['id'], 'attachment_id': 'old',
                                        'consent': True})
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns WHERE id=%s',
                                               ('new-file',)).fetchone()['n'], 0)
        self.client.portal.call(self.app.state.runtime.call, attempt)
