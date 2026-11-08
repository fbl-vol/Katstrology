"""Synthetic LAN enrollment at the real HTTP/Store boundary; no live edge."""
import asyncio
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from starlette.requests import Request
from starlette.testclient import TestClient

from m2.http_boundary.app import create_app
from m2.http_boundary.signup import Signup, SignupPolicy
from m2.http_boundary.signup_socket import signup_socket
from tests.support.database import DatabaseCase, synthetic_web_dist

ORIGIN = 'http://127.0.0.1:8765'
POLICY = {'socket': '/run/kat-signup/signup.sock', 'networks': ['192.168.42.0/24', 'fd42:1234::/64'],
          'excluded_clients': ['192.168.42.1', '192.168.42.5', 'fd42:1234::1']}
PASSWORD = 'synthetic-signup-password'


def request(peer='192.168.42.20', *, client=None, server=None, extra=()):
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/signup',
        'server': server or (POLICY['socket'], None), 'client': client,
        'headers': [(b'x-kat-signup-client', peer.encode()), *extra]})


class SignupPolicyTests(TestCase):
    def test_exact_network_and_transport_not_private_ip_or_forwarded_claim(self):
        policy = SignupPolicy.parse(POLICY)
        for peer in ('192.168.42.20', '192.168.42.254', 'fd42:1234::2', '::ffff:192.168.42.20'):
            self.assertTrue(policy.admits(request(peer)), peer)
        for peer in ('192.168.42.1', '192.168.42.5', 'fd42:1234::1', '192.168.42.0',
                     '192.168.42.255', '192.168.43.20', '10.0.0.2', '100.64.0.2',
                     '203.0.113.20', '::1', 'fe80::1', 'fd42:1235::2', 'fd42:1234::2%eth0',
                     '192.168.42.20, 203.0.113.1', '192.168.42.20:123', ' 192.168.42.20'):
            self.assertFalse(policy.admits(request(peer)), peer)
        for peer in (('127.0.0.1', 1234), ('172.20.0.1', 5432), ('192.168.42.5', 90)):
            self.assertFalse(policy.admits(request(client=peer)))
        self.assertFalse(policy.admits(request(server=('127.0.0.1', 8765))))
        self.assertFalse(policy.admits(request(server=('/run/other.sock', None))))
        for header in (b'x-kat-signup-client', b'forwarded', b'x-forwarded-for', b'x-forwarded-port', b'x-real-ip'):
            self.assertFalse(policy.admits(request(extra=[(header, b'192.168.42.20')])))
        missing = request(); missing.scope['headers'] = []
        self.assertFalse(policy.admits(missing))

    def test_configuration_and_private_socket_permissions(self):
        for changes in ({'networks': ['0.0.0.0/0']}, {'networks': ['::/0']},
                        {'networks': ['127.0.0.0/16']}, {'excluded_clients': []},
                        {'socket': 'relative.sock'}, {'networks': ['::ffff:192.168.42.0/120']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SignupPolicy.parse({**POLICY, **changes})
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'signup.sock'
            with signup_socket(path) as listener:
                self.assertEqual(path.stat().st_mode & 0o777, 0o660)
                self.assertEqual(listener.family, socket.AF_UNIX)
            self.assertFalse(path.exists())
            path.write_text('not a socket')
            with self.assertRaises(ValueError), signup_socket(path):
                pass
            self.assertEqual(path.read_text(), 'not a socket')
            path.unlink(); Path(directory).chmod(0o777)
            with self.assertRaises(ValueError), signup_socket(path):
                pass

    def test_policy_file_rejects_untrusted_owner_permissions_symlink_and_size(self):
        import json
        import stat
        from types import SimpleNamespace
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            path.write_text(json.dumps(POLICY))
            trusted = dict(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_size=path.stat().st_size)
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(**trusted)):
                self.assertEqual(SignupPolicy.load(path).socket, POLICY['socket'])
            for change in ({'st_uid': 1000}, {'st_mode': stat.S_IFREG | 0o666},
                           {'st_mode': stat.S_IFLNK | 0o777}, {'st_size': 4097}):
                with patch.object(Path, 'lstat', return_value=SimpleNamespace(**{**trusted, **change})):
                    with self.assertRaises(ValueError): SignupPolicy.load(path)

    def test_cli_cannot_enable_signup_in_local_or_enrollment_mode(self):
        from m2.web_server import main
        for args in (['serve'], ['enroll', '--deployment-origin', 'https://fixture.invalid']):
            with patch('sys.argv', ['kat-web', *args, '--signup-policy', '/synthetic/policy.json']), \
                 patch('m2.web_server.fixture_dsn') as fixture, \
                 patch('m2.web_server.SignupPolicy.load') as policy:
                with self.assertRaises(SystemExit): main()
                fixture.assert_not_called(); policy.assert_not_called()

    def test_actual_unix_and_tcp_scopes_keep_header_claims_separate(self):
        import httpx
        import uvicorn
        from starlette.responses import JSONResponse

        async def exercise(directory):
            path = Path(directory) / 'signup.sock'
            policy = SignupPolicy.parse({**POLICY, 'socket': str(path)})
            async def app(scope, receive, send):
                await JSONResponse({'available': policy.admits(Request(scope))})(scope, receive, send)
            with socket.socket() as tcp, signup_socket(path) as unix:
                tcp.bind(('127.0.0.1', 0)); tcp.listen()
                port = tcp.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(app, lifespan='off', proxy_headers=False,
                                                       access_log=False, log_level='error'))
                task = asyncio.create_task(server.serve(sockets=[tcp, unix]))
                try:
                    async with asyncio.timeout(5):
                        while not server.started: await asyncio.sleep(.01)
                    headers = {'X-Kat-Signup-Client': '192.168.42.20'}
                    async with httpx.AsyncClient() as client:
                        response = await client.get(f'http://127.0.0.1:{port}/', headers=headers)
                        self.assertFalse(response.json()['available'])
                    transport = httpx.AsyncHTTPTransport(uds=str(path))
                    async with httpx.AsyncClient(transport=transport, base_url='http://fixture') as client:
                        self.assertTrue((await client.get('/', headers=headers)).json()['available'])
                        self.assertFalse((await client.get('/', headers={**headers,
                            'X-Forwarded-For': '192.168.42.20'})).json()['available'])
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(task, 5)
        with TemporaryDirectory() as directory:
            asyncio.run(exercise(directory))

    def test_disconnect_does_not_release_hash_admission(self):
        async def exercise():
            gate = Signup(clock=lambda: 100)
            started, release = asyncio.Event(), asyncio.Event()
            class Runtime:
                def spawn(self, coroutine): return asyncio.create_task(coroutine)
                async def call(self, operation):
                    started.set(); await release.wait(); return True
            runtime = Runtime()
            first = asyncio.create_task(gate.create(runtime, 'one', PASSWORD))
            await started.wait(); first.cancel()
            with self.assertRaises(asyncio.CancelledError): await first
            gate.clock = lambda: 1000
            self.assertEqual((await gate.create(runtime, 'two', PASSWORD)).status_code, 429)
            release.set(); await gate.pending; await asyncio.sleep(0)
            self.assertIsNone(gate.pending)
        asyncio.run(exercise())


class SignupHTTPTests(DatabaseCase):
    def client(self, *, enabled=True, unix=True):
        self.store.close()  # BrowserRuntime takes exclusive Store ownership.
        app = create_app(self.dsn, Path(self.directory.name) / 'files', self.ledger.path, synthetic_web_dist(self.directory.name),
                         signup_policy=SignupPolicy.parse(POLICY) if enabled else None)
        async def transport(scope, receive, send):
            if scope['type'] == 'http' and unix:
                scope = {**scope, 'server': (POLICY['socket'], None), 'client': None}
            await app(scope, receive, send)
        self.app = app
        return TestClient(transport, base_url=ORIGIN)

    def headers(self, peer='192.168.42.20'):
        return {'Origin': ORIGIN, 'X-Kat-Signup-Client': peer, 'Sec-Fetch-Site': 'same-origin'}

    def payload(self, username='new-reader', password=PASSWORD):
        return {'username': username, 'password': password, 'confirm_password': password}

    def test_allowed_creates_empty_owner_and_returns_to_existing_login(self):
        from m2.people.people import People
        for owner, session in (('alice', self.alice), ('bob', self.bob)):
            People(self.store).charts.add_person(session, owner + '-person', 'Private synthetic person')
            self.store.create_conversation(session, owner + '-conversation')
        with self.client() as client:
            self.assertTrue(client.get('/api/signup', headers=self.headers()).json()['available'])
            response = client.post('/api/signup', headers=self.headers(), json=self.payload())
            self.assertEqual(response.status_code, 201)
            self.assertNotIn('set-cookie', response.headers)
            self.assertEqual(client.get('/api/session').status_code, 401)
            self.assertEqual(self.app.state.runtime.store.db.execute('SELECT count(*) AS n FROM web_sessions').fetchone()['n'], 0)
            login = client.post('/api/login', headers={'Origin': ORIGIN}, json={
                'username': 'new-reader', 'password': PASSWORD})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(login.json()['owner'], 'new-reader')
            self.assertEqual(client.get('/api/people').json()['people'], [])
            for owner in ('alice', 'bob'):
                self.assertEqual(client.get('/api/people/' + owner + '-person').status_code, 404)
                self.assertEqual(client.get('/api/conversations/' + owner + '-conversation').status_code, 404)
            self.assertEqual(self.app.state.runtime.store.db.execute(
                "SELECT count(*) AS n FROM conversations WHERE owner_id='new-reader'").fetchone()['n'], 0)
            self.assertFalse(client.get('/api/siwc/status').json()['connected'])
            self.assertEqual(self.app.state.runtime.store.db.execute('SELECT count(*) AS n FROM accounts').fetchone()['n'], 3)

    def test_forged_changed_and_cross_origin_requests_never_hash_or_write(self):
        with self.client() as client:
            self.assertTrue(client.get('/api/signup', headers=self.headers()).json()['available'])
            store = self.app.state.runtime.store
            with patch.object(type(store.password_hasher), 'hash') as hash_password, \
                 patch.object(self.app.state.runtime, 'call') as queued:
                for headers in (self.headers('203.0.113.1'), {'Origin': ORIGIN},
                                {**self.headers(), 'Origin': 'https://evil.invalid'},
                                {**self.headers(), 'Sec-Fetch-Site': 'cross-site'},
                                {**self.headers(), 'X-Forwarded-For': '192.168.42.20'},
                                [('Origin', ORIGIN), ('X-Kat-Signup-Client', '192.168.42.20'),
                                 ('X-Kat-Signup-Client', '192.168.42.21')]):
                    response = client.post('/api/signup', headers=headers, json=self.payload())
                    self.assertEqual(response.status_code, 403)
                hash_password.assert_not_called(); queued.assert_not_called()
                self.assertEqual(store.db.execute('SELECT count(*) AS n FROM accounts').fetchone()['n'], 2)
                self.assertEqual(store.db.execute('SELECT count(*) AS n FROM web_sessions').fetchone()['n'], 0)

    def test_tcp_and_default_disabled_never_accept_forged_edge_header(self):
        # One app per test directory; reuse a single fixture root across contexts.
        for enabled, unix in ((False, True), (True, False)):
            dist = Path(self.directory.name) / 'synthetic-dist'
            if dist.exists(): (dist / 'index.html').unlink(); dist.rmdir()
            with self.client(enabled=enabled, unix=unix) as client:
                store = self.app.state.runtime.store
                with patch.object(type(store.password_hasher), 'hash') as hash_password:
                    self.assertFalse(client.get('/api/signup', headers=self.headers()).json()['available'])
                    self.assertEqual(client.post('/api/signup', headers=self.headers(), json=self.payload()).status_code, 403)
                    hash_password.assert_not_called()

    def test_racing_name_claim_cannot_overwrite_the_winner(self):
        import psycopg
        with self.client() as client:
            store = self.app.state.runtime.store
            original = store.register_local
            winning_hash = store.db.execute("SELECT password_hash FROM accounts WHERE id='alice'").fetchone()['password_hash']
            def race(username, password):
                # Another enrollment commits after lookup but before this insert.
                with psycopg.connect(self.dsn, autocommit=True) as other:
                    other.execute('INSERT INTO accounts VALUES (%s,%s)', (username, winning_hash))
                original(username, password)
            with patch.object(store, 'register_local', side_effect=race):
                response = client.post('/api/signup', headers=self.headers(), json=self.payload())
            self.assertEqual(response.status_code, 409)
            self.assertEqual(store.db.execute("SELECT password_hash FROM accounts WHERE id='new-reader'").fetchone()['password_hash'], winning_hash)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM accounts').fetchone()['n'], 3)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM web_sessions').fetchone()['n'], 0)

    def test_invalid_duplicate_and_rate_limit_preserve_existing_account(self):
        with self.client() as client:
            store = self.app.state.runtime.store
            old = store.db.execute("SELECT password_hash FROM accounts WHERE id='alice'").fetchone()
            with patch.object(type(store.password_hasher), 'hash', wraps=store.password_hasher.hash) as hash_password:
                for payload in (self.payload('alice', 'short'), self.payload('bad name'),
                                {**self.payload(), 'confirm_password': 'different'},
                                {**self.payload(), 'owner': 'alice'}, self.payload(password='x' * 8192)):
                    self.assertEqual(client.post('/api/signup', headers=self.headers(), json=payload).status_code, 400)
                hash_password.assert_not_called()
                self.assertEqual(client.post('/api/signup', headers=self.headers(), json=self.payload('alice')).status_code, 409)
                hash_password.assert_not_called()
                self.assertEqual(client.post('/api/signup', headers=self.headers(), json=self.payload()).status_code, 429)
                hash_password.assert_not_called()
            self.assertEqual(store.db.execute("SELECT password_hash FROM accounts WHERE id='alice'").fetchone(), old)
