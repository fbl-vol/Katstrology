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

    def verify(self):
        opener = type('Opener', (), {'open': lambda _, request, timeout: self.open(request, timeout)})()
        with patch.object(remote, 'build_opener', return_value=opener), \
             patch.object(remote, 'monotonic', self.clock.now, create=True), \
             patch.object(remote, 'sleep', self.clock.sleep, create=True), \
             patch.object(remote, 'LOCAL_READINESS_SECONDS', 3.0, create=True):
            return self.release.phase('verify_serving_path')

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

    def test_other_transport_error_is_fatal_without_polling(self):
        self.events = [URLError(PermissionError(13, 'synthetic transport refusal'))]
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
        for status in (200, 403, 302):
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
