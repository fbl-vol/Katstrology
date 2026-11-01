"""Synthetic browser policy and legacy media replay without a new upload route."""

from base64 import b64decode
from io import BytesIO
from pathlib import Path
from time import time
import json

from PIL import Image
from pypdf import PdfWriter
from starlette.testclient import TestClient

from m2.attachments import Attachments
from m2.gateway import run_turn
from m2.provider_media import validate_chart_file
from m2.provider_model import ResponsesModel
from m2.recall import current_text, rebuild_one, search
from m2.siwc import ProviderBridge
from m2.test_siwc import FakeOpenAI
from m2.test_support import DatabaseCase, synthetic_web_dist
from m2.web_server import create_app


class SelectedProfileMediaTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.store.close()
        self.transport = FakeOpenAI()
        self.app = create_app(self.dsn, Path(self.directory.name) / 'files',
                              Path(self.directory.name) / 'deletions.jsonl',
                              synthetic_web_dist(self.directory.name),
                              siwc_factory=lambda root: ProviderBridge(root, self.transport),
                              siwc_root=Path(self.directory.name) / 'private')
        self.client_context = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.client = self.client_context.__enter__()
        self.app.state.runtime.siwc.credentials.save('alice', {
            'selected': 'synthetic-client', 'accounts': {'synthetic-client': {
                'scopes': ['chatgpt.tokens.use.direct'], 'access_token': 'synthetic-only',
                'refresh_token': 'synthetic-only', 'expires_at': time() + 3600}}})
        self.login('alice', 'synthetic-password-alice')

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        super().tearDown()

    def login(self, username, password):
        response = self.client.post('/api/login', json={'username': username, 'password': password},
                                    headers={'Origin': 'http://127.0.0.1:8765'})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()['csrf']

    def post(self, path, value):
        return self.client.post('/api/' + path, json=value, headers={
            'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': self.csrf})

    def fixture(self):
        draft = {'birth_date': '2001-04-05', 'birth_time': '09:12',
                 'birthplace': 'Unverified town', 'time_unknown': False}
        person = self.post('people', {'name': 'Synthetic Profile', 'draft': draft}).json()
        self.assertEqual(self.post('conversations', {'id': 'thread', 'title': 'Synthetic thread',
                                                     'people': [person['id']]}).status_code, 201)
        return person

    def legacy_file(self, person, content, filename):
        file_id = f'file-{filename.replace(".", "-")}'
        def save(store, auth):
            Attachments(store).add_person(auth.owners['alice'], person['id'], file_id,
                                          filename, content)
        self.client.portal.call(self.app.state.runtime.call, save)
        return file_id

    @staticmethod
    def message(person, turn_id, file_id=None):
        return {'id': turn_id, 'text': 'Describe supplied birth details',
                'selected_people': [{'person_id': person['id'], 'chart_id': None}],
                'parent': '@root', 'revision_kind': 'normal', 'replaces_turn_id': None,
                'mode': 'chatgpt', 'model_slug': 'gpt-6.1-sol',
                'chart_file': ({'person_id': person['id'], 'attachment_id': file_id,
                                'consent': True} if file_id else None)}

    def legacy_turn(self, person, turn_id, file_id):
        payload = self.message(person, turn_id, file_id)
        def archive(store, auth):
            session = auth.owners['alice']
            model = ResponsesModel(self.app.state.runtime.siwc, 'alice', 'gpt-6.1-sol')
            return run_turn(store, session, 'thread', turn_id, payload['text'], model,
                            lambda _event: None, parent_id='@root',
                            selected_people=payload['selected_people'],
                            model_provider='chatgpt_plan', model_slug='gpt-6.1-sol',
                            chart_file=payload['chart_file'])
        self.assertEqual(self.client.portal.call(self.app.state.runtime.call, archive), 'complete')
        return payload

    def captures(self):
        return [call[2] for call in self.transport.calls if call[0] == 'responses']

    def test_new_turn_never_transmits_old_file_and_old_turn_replays_without_resend(self):
        person = self.fixture()
        image = BytesIO()
        Image.new('RGB', (16, 12), '#325844').save(image, format='PNG')
        content = image.getvalue()
        file_id = self.legacy_file(person, content, 'private-chart.png')
        url = 'conversations/thread/turns'
        new = {key: value for key, value in self.message(person, 'fresh').items()
               if key not in ('mode', 'model_slug', 'chart_file')}
        new['selected_people'] = [{'person_id': person['id']}]
        self.assertEqual(self.post(url, new).status_code, 202)
        self.assertIn('Synthetic provider response', self.client.get('/api/' + url + '/fresh/events').text)
        self.assertEqual(len(self.captures()[0]['input'][0]['content']), 1)
        prompt = self.captures()[0]['input'][0]['content'][0]['text']
        self.assertIn('Unverified town', prompt)
        self.assertIn('UNVERIFIED', prompt)
        self.assertNotIn('private-chart.png', json.dumps(self.captures()[0]))
        for override in (self.message(person, 'bypass', file_id),
                         {**new, 'id': 'bypass2', 'chart_file': None}):
            self.assertEqual(self.post(url, override).status_code, 400)
        self.assertEqual(len(self.captures()), 1)

        original = self.legacy_turn(person, 'old-file', file_id)
        media = self.captures()[1]['input'][0]['content'][1]
        self.assertEqual(media['type'], 'input_image')
        self.assertEqual(b64decode(media['image_url'].split(',', 1)[1]), content)
        original_record = self.client.get('/api/' + url + '/old-file').json()
        self.assertEqual(original_record['selected_people'][0]['attachment_id'], file_id)
        self.assertNotIn(content.hex(), json.dumps(original_record))
        self.app.state.runtime.siwc.credentials.save('alice', {'selected': None, 'accounts': {}})
        self.assertEqual(self.post(url, original).status_code, 202)
        self.assertEqual(len(self.captures()), 2)
        self.assertEqual(self.post(url, {**original, 'chart_file': None}).status_code, 400)
        denied = self.client.delete(f'/api/people/{person["id"]}/files/{file_id}',
                                    headers={'Origin': 'http://127.0.0.1:8765',
                                             'X-Kat-CSRF': self.csrf})
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()['conversations'],
                         [{'id': 'thread', 'title': 'Synthetic thread'}])
        self.assertEqual(self.client.get(f'/api/people/{person["id"]}/files/{file_id}').content,
                         content)
        self.login('bob', 'synthetic-password-bob')
        self.assertEqual(self.client.get(f'/api/people/{person["id"]}/files/{file_id}').status_code,
                         404)
        self.login('alice', 'synthetic-password-alice')
        self.assertEqual(self.client.delete('/api/conversations/thread', headers={
            'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': self.csrf}).status_code, 200)
        self.assertEqual(self.client.delete(f'/api/people/{person["id"]}/files/{file_id}',
                        headers={'Origin': 'http://127.0.0.1:8765',
                                 'X-Kat-CSRF': self.csrf}).status_code, 200)

    def test_legacy_pdf_media_and_corrected_draft_are_separate(self):
        person = self.fixture()
        document = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(document)
        content = document.getvalue()
        file_id = self.legacy_file(person, content, 'supplied.pdf')
        original = self.legacy_turn(person, 'pdf', file_id)
        media = self.captures()[0]['input'][0]['content'][1]
        self.assertEqual(media['type'], 'input_file')
        self.assertEqual(b64decode(media['file_data'].split(',', 1)[1]), content)
        self.assertEqual(self.post(f'people/{person["id"]}/drafts', {
            'birth_date': '2002-02-02', 'birth_time': '10:10',
            'birthplace': 'Corrected unverified town', 'time_unknown': False}).status_code, 201)
        def inspect(store, auth):
            session = auth.owners['alice']
            self.assertIsNone(current_text(store, session, 'thread', 'pdf'))
            epoch = store._conversation(store.owner(session), 'thread')['epoch']
            self.assertTrue(rebuild_one(store, session, 'thread', epoch))
            self.assertEqual(search(store, session, 'supplied', 10)['results'], [])
        self.client.portal.call(self.app.state.runtime.call, inspect)
        self.assertEqual(self.client.get('/api/conversations/thread/turns/pdf').json()
                         ['selected_people'][0]['draft_revision'], 1)
        self.assertEqual(self.post('conversations/thread/turns', original).status_code, 202)
        self.assertEqual(len(self.captures()), 1)
        fresh = {key: value for key, value in self.message(person, 'fresh').items()
                 if key not in ('mode', 'model_slug', 'chart_file')}
        fresh['selected_people'] = [{'person_id': person['id']}]
        self.assertEqual(self.post('conversations/thread/turns', fresh).status_code, 202)
        self.client.get('/api/conversations/thread/turns/fresh/events')
        self.assertEqual(self.client.get('/api/conversations/thread/turns/fresh').json()
                         ['selected_people'][0]['draft_revision'], 2)
        prompt = self.captures()[1]['input'][0]['content'][0]['text']
        self.assertIn('Corrected unverified town', prompt)
        self.assertNotIn('Unverified town', prompt)

    def test_legacy_media_validation_rejects_damaged_or_oversized_bytes(self):
        person = self.fixture()
        damaged = self.legacy_file(person, b'\x89PNG\r\n\x1a\nnot-a-valid-png', 'damaged.png')
        pdf = BytesIO()
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        too_many = self.legacy_file(person, pdf.getvalue(), 'five-pages.pdf')
        def validate(store, auth):
            session = auth.owners['alice']
            for file_id in (damaged, too_many):
                with self.assertRaises(ValueError):
                    validate_chart_file(*Attachments(store).read_person(session, person['id'], file_id))
        self.client.portal.call(self.app.state.runtime.call, validate)
        self.assertEqual(self.captures(), [])
