"""Cold HTTP readiness through the actual verification/containment phase; no host I/O."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from deploy import release_remote as remote
from deploy.test_release_promotion import OwnedRelease


class Clock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class Response:
    def __init__(self, status, body=b''):
        self.status, self.body = status, body

    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def read(self): return self.body


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture()

    def fixture(self):
        directory = TemporaryDirectory(prefix='kat-readiness-test-')
        self.addCleanup(directory.cleanup)
        self.release = OwnedRelease(Path(directory.name))
        self.release.snapshot()
        self.release.phase('promote_release')
        self.release.phase('activate_app_only')
        self.clock = Clock()
        self.requests = []
        self.events = []
        self.never_ready = False
        self.bad_asset = False
        self.wrong_host_status = 403
        self.bodies = {'index.html': b'home', 'manifest.webmanifest': b'manifest',
                       'icons/kat-192.png': b'192', 'icons/kat-512.png': b'512',
                       'icons/kat-512-maskable.png': b'mask'}
        native_double = self.release.docker

        def docker(*args, **kwargs):
            if args[-1].startswith('import hashlib,json,pathlib;'):
                return json.dumps({name: sha256(body).hexdigest() for name, body in self.bodies.items()})
            return native_double(*args, **kwargs)
        self.release.docker = docker

    def open(self, request, timeout):
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(urlsplit(request.full_url).hostname, '127.0.0.1')
        self.assertNotIn('Authorization', dict(request.header_items()))
        self.assertNotIn('Cookie', dict(request.header_items()))
        self.requests.append(request)
        self.clock.value += 0.01
        if request.get_header('Host') == 'wrong.invalid':
            if self.wrong_host_status >= 400:
                raise HTTPError(request.full_url, self.wrong_host_status, 'synthetic', {}, BytesIO())
            return Response(self.wrong_host_status)
        if urlsplit(request.full_url).path == '/api/session':
            if self.never_ready:
                raise URLError(ConnectionRefusedError(111, 'synthetic cold start'))
            event = self.events.pop(0) if self.events else 401
            if isinstance(event, Exception):
                raise event
            return Response(event)
        name = urlsplit(request.full_url).path.lstrip('/') or 'index.html'
        return Response(200, b'corrupt' if self.bad_asset else self.bodies[name])

    def verify(self, *, ci=False):
        opener = type('Opener', (), {'open': lambda _, request, timeout: self.open(request, timeout)})()
        with patch.object(remote, 'build_opener', return_value=opener), \
             patch.object(remote, 'monotonic', self.clock.now, create=True), \
             patch.object(remote, 'sleep', self.clock.sleep, create=True), \
             patch.object(remote, 'LOCAL_READINESS_SECONDS', 3.0, create=True):
            return self.release.phase('verify_serving_path', ci_admission={} if ci else None)

    def test_ci_stays_fenced_through_public_boundary_and_never_stops_work_after_reopen(self):
        for failed_receipt in (False, True):
            with self.subTest(failed_receipt=failed_receipt):
                self.fixture()
                state = {'phase': 'fenced', 'attempt': self.release.plan['attempt'], 'boot': 'b' * 32}
                resumes = []
                def maintenance(container, action, attempt):
                    self.assertEqual(container, 'app-id')
                    if action == 'resume':
                        resumes.append(action)
                        state.update(phase='open', attempt=None)
                    return dict(state)
                original = remote.os.replace
                def replace(source, destination):
                    if (failed_receipt and Path(source).name == 'phase.next'
                            and json.loads(Path(source).read_text())['phase'] == 'completed'):
                        raise OSError('Synthetic completion receipt failure')
                    return original(source, destination)
                with patch.object(remote, 'maintenance', side_effect=maintenance):
                    self.assertEqual(self.verify(ci=True)['status'], 'ok')
                    self.assertEqual(state['phase'], 'fenced')
                    self.assertFalse(resumes, 'Local verification must not admit work before public verification')
                    stops = sum('stop' in call for call in self.release.calls)
                    with patch.object(remote.os, 'replace', side_effect=replace):
                        result = self.release.phase('complete', ci_admission={})
                    self.assertEqual(resumes, ['resume'])
                    self.assertTrue(self.release.running)
                    self.assertEqual(sum('stop' in call for call in self.release.calls), stops)
                    self.assertEqual(state['phase'], 'open')
                    if failed_receipt:
                        self.assertEqual(result['status'], 'halted')
                        self.assertIn('completion unconfirmed', result['serving'])
                        self.assertTrue((self.release.root / 'active-attempt').exists())
                    else:
                        self.assertEqual(result['status'], 'ok')
                        self.assertFalse((self.release.root / 'active-attempt').exists())

    def test_refused_then_503_then_401_proceeds_without_activation_retry(self):
        self.events = [URLError(ConnectionRefusedError(111, 'synthetic startup')), 503, 401]
        result = self.verify()
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(self.release.running)
        self.assertEqual(result['readiness']['attempts'], 3)
        self.assertGreater(len(self.clock.sleeps), 0)
        self.assertEqual(sum('up' in args for args in self.release.calls), 1)
        self.assertEqual(json.loads((self.release.stage / 'phase.json').read_text())['phase'], 'local_verified')

    def test_read_timeout_then_401_retries_only_the_anonymous_probe(self):
        self.events = [TimeoutError('synthetic cold response timeout'), 401]
        result = self.verify()
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(self.release.running)
        self.assertEqual(result['readiness']['attempts'], 2)
        self.assertEqual(sum('up' in args for args in self.release.calls), 1)

    def test_bare_and_wrapped_reset104_then_401_retry_only_initial_anonymous_readiness(self):
        for error in (ConnectionResetError(104, 'synthetic cold forwarding reset'),
                      URLError(ConnectionResetError(104, 'synthetic wrapped reset'))):
            with self.subTest(error=type(error).__name__):
                self.fixture()
                self.events = [error, 401]
                result = self.verify()
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['readiness']['attempts'], 2)
                self.assertTrue(self.release.running)
                self.assertEqual(len(self.clock.sleeps), 1)
                self.assertEqual(sum('up' in args for args in self.release.calls), 1)

    def test_repeated_reset104_exhausts_existing_deadline_and_quarantines_without_reactivation(self):
        self.events = [ConnectionResetError(104, 'synthetic repeated cold reset') for _ in range(10)]
        result = self.verify()
        self.assertEqual(result['status'], 'halted')
        self.assertEqual(result['failure_type'], 'TimeoutError')
        self.assertFalse(self.release.running)
        self.assertGreaterEqual(self.clock.value, 3.0)
        self.assertGreater(len(self.requests), 1)
        self.assertEqual(sum('up' in args for args in self.release.calls), 1)
        self.assertTrue((self.release.root / 'active-attempt').exists())

    def test_reset_does_not_hide_owner_drift_on_next_probe_or_after_ready_response(self):
        for after_ready in (False, True):
            with self.subTest(after_ready=after_ready):
                self.fixture()
                original = self.open
                def changing_owner(request, timeout):
                    response = original(request, timeout)
                    self.release.image = 'sha256:' + 'f' * 64
                    if not after_ready:
                        raise ConnectionResetError(104, 'synthetic reset before owner recheck')
                    return response
                with patch.object(self, 'open', side_effect=changing_owner):
                    result = self.verify()
                self.assertEqual(result['status'], 'halted')
                self.assertIn('unknown', result['serving'])
                self.assertTrue(self.release.running, 'Must not stop a different image')
                self.assertEqual(len(self.requests), 1)

    def test_reset_after_initial_401_is_fatal_definitive_verification_not_readiness(self):
        self.events = [401, ConnectionResetError(104, 'synthetic definitive session reset')]
        result = self.verify()
        self.assertEqual(result['status'], 'halted')
        self.assertEqual(result['failure_type'], 'ConnectionResetError')
        self.assertFalse(self.release.running)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(sum('up' in args for args in self.release.calls), 1)

    def test_other_transport_error_is_fatal_without_polling(self):
        for error in (URLError(PermissionError(13, 'synthetic transport refusal')),
                      ConnectionAbortedError(103, 'synthetic aborted connection'),
                      BrokenPipeError(32, 'synthetic broken pipe'),
                      ConnectionResetError(105, 'synthetic reset class but different errno'),
                      URLError('synthetic Connection reset by peer without errno')):
            with self.subTest(error=repr(error)):
                self.fixture()
                self.events = [error]
                result = self.verify()
                self.assertEqual(result['status'], 'halted')
                self.assertFalse(self.release.running)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.clock.sleeps, [])

    def test_never_ready_deadline_quarantines_exact_app_without_reactivation(self):
        self.never_ready = True
        result = self.verify()
        self.assertEqual(result['status'], 'halted')
        self.assertIn('stopped', result['serving'])
        self.assertFalse(self.release.running)
        self.assertGreaterEqual(self.clock.value, 3.0)
        self.assertGreater(len(self.requests), 1)
        self.assertEqual(sum('up' in args for args in self.release.calls), 1)
        self.assertTrue((self.release.root / 'active-attempt').exists())
        self.assertEqual(result['failure_type'], 'TimeoutError')
        self.assertEqual(self.release.phase('quarantine')['failure_type'], 'TimeoutError')

    def test_permanent_anonymous_status_and_redirect_fail_without_polling(self):
        for status in (200, 403, 404, 302):
            with self.subTest(status=status):
                self.fixture()
                self.events = [status]
                result = self.verify()
                self.assertEqual(result['status'], 'halted')
                self.assertFalse(self.release.running)
                self.assertEqual(len(self.requests), 1)
                self.assertEqual(self.clock.sleeps, [])

    def test_final_host_or_asset_failure_is_not_retried_as_readiness(self):
        for defect in ('host', 'asset'):
            with self.subTest(defect=defect):
                self.fixture()
                self.wrong_host_status = 200 if defect == 'host' else 403
                self.bad_asset = defect == 'asset'
                result = self.verify()
                self.assertEqual(result['status'], 'halted')
                self.assertFalse(self.release.running)
                self.assertEqual(self.clock.sleeps, [])
                self.assertEqual(sum('up' in args for args in self.release.calls), 1)

    def test_image_identity_drift_is_fatal_before_any_http_probe(self):
        self.release.image = 'sha256:' + 'f' * 64
        result = self.verify()
        self.assertEqual(result['status'], 'halted')
        self.assertIn('unknown', result['serving'])
        self.assertTrue(self.release.running, 'Must not stop a mismatched image')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.clock.sleeps, [])


if __name__ == '__main__':
    unittest.main()
