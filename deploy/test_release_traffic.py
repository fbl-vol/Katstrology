"""Normal HTTP writes during release verification, only with an explicit owned fixture."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import release_remote as remote
from deploy.test_release_promotion import OwnedRelease


@unittest.skipUnless(os.environ.get('KAT_ISOLATED_TEST_DSN') and
                     os.environ.get('KAT_ISOLATED_TEST_CONTAINER'),
                     'requires freshly owned isolated PostgreSQL fixture; never fall back to user DB')
class ReleaseTrafficTests(unittest.TestCase):
    def test_actual_successful_login_during_public_verification_keeps_app_serving(self):
        import psycopg
        from m2 import test_web_auth
        auth = test_web_auth.BrowserAuthTests()
        auth.setUp()
        self.addCleanup(auth.tearDown)

        def sessions():
            with psycopg.connect(auth.dsn) as database:
                return database.execute('SELECT count(*) FROM web_sessions').fetchone()[0]

        def current_state(*args, **kwargs):
            return {'database': {'web_sessions': sessions()}, 'state': {
                'host_sha256': '1' * 64, 'journal_sha256': '2' * 64, 'journal_bytes': 123}}

        with TemporaryDirectory(prefix='kat-pipeline-traffic-') as directory:
            release = OwnedRelease(Path(directory))
            with patch.object(remote, 'preservation', side_effect=current_state):
                release.snapshot()
                self.assertEqual(release.phase('promote_release')['status'], 'ok')
                self.assertEqual(release.phase('activate_app_only')['status'], 'ok')
                before = sessions()
                with auth.client() as client:
                    for _ in range(3):
                        self.assertEqual(client.get('/api/session').status_code, 401)
                    self.assertEqual(sessions(), before, 'Anonymous readiness must not create a web session')
                    response = client.post('/api/login', headers={'Origin': test_web_auth.ORIGIN},
                        json={'username': 'alice', 'password': 'synthetic-password-alice'})
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(sessions(), before + 1)
                (release.stage / 'phase.json').write_text(json.dumps({
                    'plan_sha256': release.plan['plan_sha256'], 'phase': 'local_verified'}))
                result = release.phase('complete')
            self.assertEqual(result['status'], 'ok')
            self.assertTrue(release.running)
            self.assertFalse((release.root / 'active-attempt').exists())


if __name__ == '__main__':
    unittest.main()
