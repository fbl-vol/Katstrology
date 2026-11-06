"""Hosted browser archive works without the optional local inference binding."""

import os
import subprocess
import sys
import unittest


class HostedOnlyImportTests(unittest.TestCase):
    def test_hosted_ack_and_fake_provider_without_local_inference_binding(self):
        if not os.environ.get('KAT_ISOLATED_TEST_DSN'):
            self.skipTest('Requires the owned isolated PostgreSQL fixture')
        # Fresh interpreter: blocking modules after another test imported them would not
        # exercise actual hosted startup/import boundaries.
        script = '''
import sys
import unittest
sys.modules['llama_cpp'] = None
from m2.http_boundary.runtime import BrowserRuntime
from m2.chat.chat_jobs import ChatJobs
suite = unittest.defaultTestLoader.loadTestsFromName(
    'tests.http_boundary.test_web_chat.ChatHttpTests.test_committed_ack_reconnect_cursor_retry_and_owner_scope')
result = unittest.TextTestRunner(verbosity=0).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=90, check=False, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
