"""Browser product policy, without credentials, provider traffic or a shared archive."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from starlette.testclient import TestClient

from m2.operations.product_policy import MODEL, REPORTING_ZONE
from m2.chat.prompting import HOSTED, identity
from m2.chat.tone_profiles import DEFAULT, instructions
from m2.provider.siwc import ProviderBridge
from tests.provider.test_siwc import FakeOpenAI
from tests.support.database import DatabaseCase, synthetic_web_dist
from m2.http_boundary.app import create_app


class ProductPolicyTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.directory_http = TemporaryDirectory(prefix='kat-policy-http-')
        self.transport = FakeOpenAI()
        self.app = create_app(self.dsn, Path(self.directory_http.name) / 'files',
                              Path(self.directory_http.name) / 'ledger.jsonl',
                              synthetic_web_dist(self.directory_http.name),
                              siwc_factory=lambda root: ProviderBridge(root, self.transport))
        self.store.close()
        self.client_context = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.client = self.client_context.__enter__()
        login = self.client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                                 json={'username': 'alice', 'password': 'synthetic-password-alice'})
        self.assertEqual(login.status_code, 200)
        self.csrf = login.json()['csrf']
        self.headers = {'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': self.csrf}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory_http.cleanup()
        super().tearDown()

    @staticmethod
    def message(**overrides):
        return {'id': 'policy-turn', 'text': 'Synthetic question', 'selected_people': [],
                'parent': '@active', 'revision_kind': 'normal', 'replaces_turn_id': None,
                **overrides}

    def test_defaults_are_server_owned_and_no_new_turn_has_fallback(self):
        self.assertEqual(self.client.get('/api/session').json()['product'],
                         {'model': MODEL, 'reporting_zone': REPORTING_ZONE})
        self.client.post('/api/conversations', headers=self.headers,
                         json={'id': 'policy-thread', 'title': 'New conversation', 'people': []})
        url = '/api/conversations/policy-thread/turns'
        no_plan = self.client.post(url, headers=self.headers, json=self.message())
        self.assertEqual(no_plan.status_code, 409)
        self.assertEqual(no_plan.json(), {'error': 'chatgpt_plan_permission_required'})
        for override in ({'mode': 'local', 'model_slug': None},
                         {'mode': 'chatgpt', 'model_slug': 'other-model'},
                         {'reporting_zone': 'America/Los_Angeles'},
                         {'chart_file': {'person_id': 'x', 'attachment_id': 'y', 'consent': True}}):
            with self.subTest(override=override):
                self.assertEqual(self.client.post(url, headers=self.headers,
                                                  json=self.message(**override)).status_code, 400)
        self.assertEqual(self.client.get('/api/conversations/policy-thread/turns').json()['turns'], [])

    def grant_synthetic_plan(self):
        self.app.state.runtime.siwc.credentials.save('alice', {
            'selected': 'oaiapp_synthetic', 'accounts': {'oaiapp_synthetic': {
                'scopes': ['chatgpt.tokens.use.direct'], 'access_token': 'synthetic-access',
                'refresh_token': 'synthetic-refresh', 'expires_at': time.time() + 1800}}})

    def test_fixed_plan_route_is_archived_and_replay_needs_no_grant(self):
        bridge = self.app.state.runtime.siwc
        self.grant_synthetic_plan()
        self.client.post('/api/conversations', headers=self.headers,
                         json={'id': 'policy-thread', 'title': 'New conversation', 'people': []})
        url = '/api/conversations/policy-thread/turns'
        payload = self.message()
        sent = self.client.post(url, headers=self.headers, json=payload)
        self.assertEqual(sent.status_code, 202, sent.text)
        events = self.client.get(url + '/policy-turn/events')
        self.assertEqual(events.status_code, 200)
        self.assertIn('Synthetic provider response', events.text)
        self.assertIn(MODEL, events.text)
        self.assertIn(REPORTING_ZONE, events.text)
        calls = list(self.transport.calls)
        self.assertEqual(next(call[2]['model'] for call in calls if call[0] == 'responses'), MODEL)
        bridge.credentials.save('alice', {'selected': None, 'accounts': {}})
        self.assertEqual(self.client.post(url, headers=self.headers, json=payload).status_code, 202)
        self.assertEqual(self.transport.calls, calls)
        self.assertEqual(self.client.post(url, headers=self.headers,
                                          json=self.message(text='Changed')).status_code, 400)
        natural = self.message(id='natural-text', text='saved chart is a phrase, not a command')
        self.grant_synthetic_plan()
        self.assertEqual(self.client.post(url, headers=self.headers, json=natural).status_code, 202)
        reply = self.client.get(url + '/natural-text/events').text
        self.assertIn('Synthetic provider response', reply)
        self.assertNotIn('invalid chart request syntax', reply)

    def test_new_browser_turn_delivers_versioned_capability_guidance_without_media(self):
        self.grant_synthetic_plan()
        self.client.post('/api/conversations', headers=self.headers,
                         json={'id': 'voice-thread', 'title': 'Synthetic topic', 'people': []})
        url = '/api/conversations/voice-thread/turns'
        request = self.message(id='visual-question', text=(
            'I saw a star-like shape but have no image here. What can you say from that description?'))
        self.assertEqual(self.client.post(url, headers=self.headers, json=request).status_code, 202)
        self.client.get(url + '/visual-question/events')
        body = next(call[2] for call in self.transport.calls if call[0] == 'responses')
        self.assertEqual(body['instructions'], instructions(DEFAULT)[0])
        self.assertIn('skip known method, birth-time and default-zone boilerplate unless asked or material', body['instructions'])
        self.assertIn('Copenhagen/default-zone setup belongs in chart/message details', body['instructions'])
        self.assertIn('semantic Markdown when helpful: subject headings, short paragraphs', body['instructions'])
        self.assertIn('No fixed template or visible Acknowledgement / Answer / Follow-up rhythm labels', body['instructions'])
        self.assertEqual([part['type'] for part in body['input'][0]['content']], ['input_text'])
        self.assertIn(request['text'], body['input'][0]['content'][0]['text'])
        self.assertNotIn(HOSTED, body['input'][0]['content'][0]['text'])
        self.assertEqual(body['model'], MODEL)
        self.assertEqual(body['store'], False)
        context = next(item['payload'] for item in self.client.get(
            url + '/visual-question').json()['events'] if item['kind'] == 'context')
        tone_id = instructions(DEFAULT)[1]
        self.assertEqual({key: context[key] for key in tone_id}, tone_id)

    def test_active_natal_is_resolved_at_ack_and_old_turn_replays_unchanged(self):
        self.grant_synthetic_plan()
        person = self.client.post('/api/people', headers=self.headers,
                                  json={'name': 'Synthetic reader'}).json()
        person_id = person['id']
        details = {'birth_date': '2024-03-20', 'birth_time': '03:06',
                   'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
                   'place_id': '2618425', 'provisional': True, 'zone_override': None,
                   'latitude_override': None, 'longitude_override': None,
                   'fold': None, 'settings': None}
        def generate(request_id, minute):
            response = self.client.post(f'/api/people/{person_id}/generate', headers=self.headers,
                                        json={**details, 'request_id': request_id,
                                              'birth_time': f'03:{minute}'})
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()['chart']['id']
        first = generate('first-generation', '06')
        self.assertEqual(self.client.get(f'/api/people/{person_id}').json()['active_chart_id'], first)
        self.client.post('/api/conversations', headers=self.headers,
                         json={'id': 'policy-thread', 'title': 'New conversation',
                               'people': [person_id]})
        url = '/api/conversations/policy-thread/turns'
        selected = [{'person_id': person_id}]
        original = self.message(selected_people=selected)
        self.assertEqual(self.client.post(url, headers=self.headers, json=original).status_code, 202)
        self.client.get(url + '/policy-turn/events')
        original_record = self.client.get(url + '/policy-turn').json()
        self.assertEqual(original_record['selected_people'][0]['chart_id'], first)
        second = generate('second-generation', '07')
        self.assertNotEqual(first, second)
        self.assertEqual(self.client.get(f'/api/people/{person_id}').json()['active_chart_id'], second)
        self.assertEqual(self.client.post(url, headers=self.headers, json=self.message(
            id='spoof', selected_people=[{'person_id': person_id, 'chart_id': first}])).status_code, 400)
        new = self.message(id='new-turn', selected_people=selected)
        self.assertEqual(self.client.post(url, headers=self.headers, json=new).status_code, 202)
        self.client.get(url + '/new-turn/events')
        self.assertEqual(self.client.get(url + '/new-turn').json()['selected_people'][0]['chart_id'], second)
        before = list(self.transport.calls)
        self.app.state.runtime.siwc.credentials.save('alice', {'selected': None, 'accounts': {}})
        self.assertEqual(self.client.post(url, headers=self.headers, json=original).status_code, 202)
        self.assertEqual(self.transport.calls, before)
        self.assertEqual(self.client.get(url + '/policy-turn').json()['selected_people'][0]['chart_id'], first)

    def test_upload_endpoint_is_closed_and_requires_no_file_read(self):
        person = self.client.post('/api/people', headers=self.headers,
                                  json={'name': 'Synthetic person'}).json()
        response = self.client.post(f"/api/people/{person['id']}/files", headers={
            **self.headers, 'Content-Type': 'application/octet-stream'}, content=b'%PDF-1.4\nsynthetic')
        self.assertIn(response.status_code, (404, 405))
        self.assertNotIn('attachments', self.client.get('/api/people/' + person['id']).json())


if __name__ == '__main__':
    unittest.main()
