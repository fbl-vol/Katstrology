"""HTTP security and restart semantics through the owned PostgreSQL fixture."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient

from m2.attachments import Attachments
from m2.charts import Charts
from m2.deletion import Tombstones
from m2.local_fixture import ROOT
from m2.store import Store
from m2.test_support import synthetic_web_dist, test_fixture_dsn
from m2.web_server import create_app


ORIGIN = 'http://127.0.0.1:8765'


class BrowserAuthTests(unittest.TestCase):
    def setUp(self):
        self.admin_dsn = test_fixture_dsn()
        self.database = 'kat_web_test_' + uuid4().hex[:12]
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.database)))
        self.dsn = make_conninfo(self.admin_dsn, dbname=self.database)
        self.directory = TemporaryDirectory(prefix='kat-browser-test-', dir=ROOT / '.local')
        self.files = Path(self.directory.name) / 'files'
        self.ledger = Path(self.directory.name) / 'deletions.jsonl'
        self.dist = synthetic_web_dist(self.directory.name)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            store.register_local('alice', 'synthetic-password-alice')
            store.register_local('bob', 'synthetic-password-bob')

    def tearDown(self):
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.database)))
        self.directory.cleanup()

    def client(self):
        return TestClient(create_app(self.dsn, self.files, self.ledger,
                                     self.dist), base_url=ORIGIN)

    def test_https_deployment_keeps_exact_browser_boundary_and_offline_enrollment(self):
        origin = 'https://katstrology.dk'
        app = create_app(self.dsn, self.files, self.ledger, self.dist,
                         origin=origin, deployment=True)
        with TestClient(app, base_url=origin) as client:
            self.assertEqual(client.get('/api/session').status_code, 401)
            self.assertEqual(client.get('/', headers={'Host': 'attacker.test'}).status_code, 403)
            self.assertEqual(client.get('/api/session', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
            self.assertEqual(client.post('/api/login', json={'username': 'alice',
                'password': 'synthetic-password-alice'}).status_code, 403)
            self.assertEqual(client.post('/api/login', headers={'Origin': 'http://katstrology.dk'},
                json={'username': 'alice', 'password': 'synthetic-password-alice'}).status_code, 403)
            response = client.post('/api/login', headers={'Origin': origin},
                json={'username': 'alice', 'password': 'synthetic-password-alice'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertIn('SameSite=strict', response.headers['set-cookie'])
            self.assertEqual(client.get('/api/siwc/status').json()['registration'], 'offline')
            self.assertFalse(client.get('/api/siwc/status').json()['available'])
            self.assertEqual(client.post('/auth/chatgpt/start', headers={'Origin': origin},
                data={'csrf': response.json()['csrf']}).status_code, 404)
            self.assertEqual(client.get('/auth/chatgpt/callback', params={'state': 'fake'},
                headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                         'Sec-Fetch-Dest': 'document'}).status_code, 403)
            self.assertEqual(client.post('/api/logout', headers={'Origin': origin}).status_code, 403)
            logout_response = client.post('/api/logout', headers={'Origin': origin,
                'X-Kat-CSRF': response.json()['csrf']})
            self.assertEqual(logout_response.status_code, 200)
            self.assertIn('Secure', logout_response.headers['set-cookie'])
            home = client.get('/')
            self.assertEqual(home.headers['strict-transport-security'], 'max-age=31536000')
            self.assertNotIn('auth.openai.com', home.headers['content-security-policy'])

    def test_offline_enrolled_bridge_has_status_but_no_browser_registration(self):
        class SyntheticBridge:
            def status(self, owner):
                return {'available': True, 'connected': owner == 'alice', 'accounts': [],
                        'selected': None}

            def close(self):
                pass

        origin = 'https://katstrology.dk'
        app = create_app(self.dsn, self.files, self.ledger, self.dist, origin=origin,
                         deployment=True, siwc_factory=lambda _root: SyntheticBridge())
        with TestClient(app, base_url=origin) as client:
            login = client.post('/api/login', headers={'Origin': origin}, json={
                'username': 'alice', 'password': 'synthetic-password-alice'})
            self.assertEqual(login.status_code, 200)
            status = client.get('/api/siwc/status').json()
            self.assertEqual((status['registration'], status['available'], status['connected']),
                             ('offline', True, True))
            self.assertEqual(client.post('/auth/chatgpt/start', headers={'Origin': origin}).status_code, 404)

    def test_workspace_login_requires_origin_and_csrf_and_can_reconnect(self):
        with self.client() as client:
            self.assertEqual(client.get('/api/session').status_code, 401)
            self.assertEqual(client.post('/api/login', json={'username': 'alice',
                                                            'password': 'synthetic-password-alice'}).status_code, 403)
            self.assertEqual(client.post('/api/login', headers={'Origin': 'https://foreign.test'},
                                         json={'username': 'alice', 'password': 'synthetic-password-alice'}).status_code, 403)
            self.assertEqual(client.post('/api/login', headers={'Origin': ORIGIN},
                                         json={'username': 'alice', 'password': 'wrong'}).status_code, 401)
            response = client.post('/api/login', headers={'Origin': ORIGIN},
                                   json={'username': 'alice', 'password': 'synthetic-password-alice'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('HttpOnly', response.headers['set-cookie'])
            self.assertIn('SameSite=strict', response.headers['set-cookie'])
            token = response.cookies['kat_session']
            csrf = response.json()['csrf']
            self.assertEqual(client.get('/api/session').json()['owner'], 'alice')
            self.assertEqual(client.get('/api/session', headers={'Host': 'foreign.test'}).status_code, 403)
            self.assertEqual(client.get('/api/session', headers={'Origin': 'https://foreign.test'}).status_code, 403)
            self.assertEqual(client.post('/api/logout', headers={'Origin': ORIGIN}).status_code, 403)

        with self.client() as restarted:
            restarted.cookies.set('kat_session', token)
            self.assertEqual(restarted.get('/api/session').json()['owner'], 'alice')
            self.assertEqual(restarted.post('/api/logout', headers={'Origin': ORIGIN,
                                                                   'X-Kat-CSRF': csrf}).status_code, 200)
            self.assertEqual(restarted.get('/api/session').status_code, 401)

    def test_person_drafts_solar_versions_and_owner_scoped_files(self):
        with self.client() as alice:
            bob = TestClient(alice.app, base_url=ORIGIN)
            self.addCleanup(bob.close)
            a = alice.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'alice', 'password': 'synthetic-password-alice'}).json()
            b = bob.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'bob', 'password': 'synthetic-password-bob'}).json()
            headers = {'Origin': ORIGIN, 'X-Kat-CSRF': a['csrf']}
            draft = {'birth_date': '2024-03-20', 'birth_time': '',
                     'birthplace': 'Unverified city', 'time_unknown': True}
            created = alice.post('/api/people', headers=headers,
                                 json={'name': 'Synthetic Example', 'draft': draft})
            self.assertEqual(created.status_code, 201)
            person_id = created.json()['id']
            self.assertEqual(created.json()['drafts'][0]['details'], draft)
            self.assertEqual(bob.get('/api/people/' + person_id).status_code, 404)
            self.assertEqual(bob.get('/api/people').json()['people'], [])
            self.assertEqual(alice.get('/api/people').json()['people'][0]['id'], person_id)
            self.assertEqual(alice.post('/api/people/' + person_id + '/drafts',
                                         json=draft, headers={'Origin': ORIGIN}).status_code, 403)

            next_draft = {**draft, 'birth_time': '03:06', 'time_unknown': False}
            self.assertEqual(alice.post('/api/people/' + person_id + '/drafts',
                                        json=next_draft, headers=headers).json()['revision'], 2)
            self.assertEqual(alice.get('/api/people/' + person_id).json()['drafts'][1]['details'], draft)
            self.assertEqual(alice.post('/api/people/' + person_id + '/births', headers=headers,
                                        json={'mode': 'exact', 'zone': 'Made/Up',
                                              'wall_time': '2024-03-20T03:06'}).status_code, 400)
            # No chart can be computed from a draft city or unverified time.
            self.assertEqual(alice.get('/api/people/' + person_id).json()['charts'], [])
            birth = alice.post('/api/people/' + person_id + '/births', headers=headers,
                               json={'mode': 'exact', 'zone': 'UTC',
                                     'wall_time': '2024-03-20T03:06:00'})
            self.assertEqual(birth.status_code, 201)
            chart = alice.post('/api/people/' + person_id + '/charts', headers=headers,
                               json={'birth_id': birth.json()['birth_id'],
                                     'profile_id': 'solar-default', 'revision': 1})
            self.assertEqual(chart.status_code, 201)
            self.assertEqual(chart.json()['result']['natal_sun']['status'], 'exact_supplied_time')
            self.assertEqual(chart.json()['result']['houses'], 'unsupported')
            self.assertEqual(bob.post('/api/people/' + person_id + '/charts',
                                      headers={'Origin': ORIGIN, 'X-Kat-CSRF': b['csrf']},
                                      json={'birth_id': birth.json()['birth_id'],
                                            'profile_id': 'solar-default', 'revision': 1}).status_code, 404)

            file_url = '/api/people/' + person_id + '/files'
            # Existing attachment archives remain readable; browser ingress is closed.
            file_id = 'file-legacy-synthetic'
            alice.portal.call(alice.app.state.runtime.call,
                              lambda store, auth: Attachments(store).add_person(
                                  auth.owners[a['owner']], person_id, file_id,
                                  'synthetic-chart.pdf', b'%PDF-1.4\nsynthetic only'))
            self.assertIn(alice.post(file_url, content=b'%PDF-1.4\nsynthetic only',
                                     headers={**headers, 'Content-Type': 'application/octet-stream'}).status_code,
                          (404, 405))
            self.assertEqual(bob.get(file_url + '/' + file_id).status_code, 404)
            self.assertEqual(alice.get(file_url + '/' + file_id).content,
                             b'%PDF-1.4\nsynthetic only')
            self.assertEqual(alice.get(file_url + '/' + file_id).headers['content-disposition'],
                             "attachment; filename*=UTF-8''synthetic-chart.pdf")
            self.assertEqual(alice.delete(file_url + '/' + file_id, headers=headers).status_code, 200)
            self.assertEqual(alice.get(file_url + '/' + file_id).status_code, 404)
            self.assertEqual(bob.delete('/api/people/' + person_id, headers={
                'Origin': ORIGIN, 'X-Kat-CSRF': b['csrf']}).status_code, 404)
            self.assertEqual(alice.delete('/api/people/' + person_id,
                                          headers={'Origin': ORIGIN}).status_code, 403)
            self.assertEqual(alice.delete('/api/people/' + person_id, headers=headers).status_code, 200)
            self.assertEqual(alice.get('/api/people/' + person_id).status_code, 404)

    def test_general_and_shared_threads_are_filtered_and_owner_scoped(self):
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            a = store.authenticate('alice', 'synthetic-password-alice')
            Charts(store).add_person(a, 'one', 'One synthetic person')
            Charts(store).add_person(a, 'two', 'Two synthetic person')
        with self.client() as alice:
            bob = TestClient(alice.app, base_url=ORIGIN)
            self.addCleanup(bob.close)
            a = alice.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'alice', 'password': 'synthetic-password-alice'}).json()
            b = bob.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'bob', 'password': 'synthetic-password-bob'}).json()
            a_headers = {'Origin': ORIGIN, 'X-Kat-CSRF': a['csrf']}
            b_headers = {'Origin': ORIGIN, 'X-Kat-CSRF': b['csrf']}
            for conv_id, selected in [('general', []), ('shared', ['one', 'two'])]:
                self.assertEqual(alice.post('/api/conversations', headers=a_headers,
                    json={'id': conv_id, 'title': conv_id.title() + ' synthetic conversation',
                          'people': selected}).status_code, 201)
            self.assertEqual([row['id'] for row in alice.get('/api/conversations?person=one')
                              .json()['conversations']], ['shared'])
            self.assertEqual([row['id'] for row in alice.get('/api/conversations?person=two')
                              .json()['conversations']], ['shared'])
            self.assertEqual(len(alice.get('/api/conversations').json()['conversations']), 2)
            self.assertEqual(bob.get('/api/conversations?person=one').status_code, 404)
            self.assertEqual(bob.get('/api/conversations/shared').status_code, 404)
            self.assertEqual(bob.post('/api/conversations', headers=b_headers,
                     json={'id': 'bad', 'title': 'Foreign person', 'people': ['one']}).status_code, 404)
            self.assertEqual(bob.post('/api/conversations', headers=b_headers,
                     json={'id': 'shared', 'title': 'Bob synthetic thread', 'people': []}).status_code, 201)
            self.assertEqual(bob.get('/api/conversations/shared').json()['title'],
                             'Bob synthetic thread')
            self.assertEqual(alice.get('/api/conversations/shared').json()['title'],
                             'Shared synthetic conversation')
            self.assertEqual(bob.patch('/api/conversations/general', headers=b_headers,
                                       json={'title': 'Foreign'}).status_code, 404)
            self.assertEqual(alice.patch('/api/conversations/shared', headers=a_headers,
                                       json={'title': 'Renamed shared synthetic'}).json()['title'],
                             'Renamed shared synthetic')
            self.assertEqual(alice.post('/api/conversations/search', headers=a_headers,
                 json={'query': 'shared', 'person': 'one', 'offset': 0}).json()
                 ['conversations'][0]['id'], 'shared')
            self.assertEqual(alice.get('/api/conversations/shared/turns').json()['turns'], [])
            self.assertEqual(bob.delete('/api/conversations/general', headers=b_headers).status_code, 404)
            self.assertEqual(alice.delete('/api/people/one', headers=a_headers).status_code, 400)
            self.assertEqual(alice.delete('/api/conversations/shared', headers=a_headers).status_code, 200)
            self.assertEqual(alice.delete('/api/people/one', headers=a_headers).status_code, 200)
            self.assertEqual([row['id'] for row in alice.get('/api/conversations')
                              .json()['conversations']], ['general'])

    def test_colliding_person_and_attachment_ids_remain_owner_scoped_over_http(self):
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            a = store.authenticate('alice', 'synthetic-password-alice')
            b = store.authenticate('bob', 'synthetic-password-bob')
            Charts(store).add_person(a, 'same-id', 'Alice synthetic person')
            Charts(store).add_person(b, 'same-id', 'Bob synthetic person')
            Attachments(store).add_person(a, 'same-id', 'same-file', 'reference.pdf', b'%PDF-A')
            Attachments(store).add_person(b, 'same-id', 'same-file', 'reference.pdf', b'%PDF-B')
        with self.client() as alice:
            bob = TestClient(alice.app, base_url=ORIGIN)
            self.addCleanup(bob.close)
            alice.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'alice', 'password': 'synthetic-password-alice'})
            bob.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'bob', 'password': 'synthetic-password-bob'})
            self.assertEqual(alice.get('/api/people/same-id').json()['name'], 'Alice synthetic person')
            self.assertEqual(bob.get('/api/people/same-id').json()['name'], 'Bob synthetic person')
            self.assertEqual(alice.get('/api/people/same-id/files/same-file').content, b'%PDF-A')
            self.assertEqual(bob.get('/api/people/same-id/files/same-file').content, b'%PDF-B')

    def test_same_id_accounts_do_not_share_workspace_identity(self):
        with self.client() as client:
            for user in ('alice', 'bob'):
                response = client.post('/api/login', headers={'Origin': ORIGIN},
                                       json={'username': user, 'password': 'synthetic-password-' + user})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get('/api/session').json()['owner'], user)
            self.assertEqual(client.get('/api/session', headers={'Sec-Fetch-Site': 'cross-site'}).status_code, 403)
            self.assertEqual(client.get('/').status_code, 200)
            self.assertNotIn('synthetic-password', client.get('/').text)
