"""Fresh local process cancellation; no database, browser, build or native release."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from deploy import qualify
from deploy.validation_budget import budget

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / '.agents/skills/kat-isolated-validation/scripts/validate.py'
spec = importlib.util.spec_from_file_location('deadline_validation', RUNNER)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ValidationDeadlineTests(unittest.TestCase):
    def test_budget_includes_shared_build_discovery_control_and_cleanup(self):
        backend, browser = budget(('backend',)), budget(('browser',))
        self.assertGreater(backend['recommended_outer_seconds'], 2 * 900)
        self.assertGreater(browser['recommended_outer_seconds'], 3 * 900)
        self.assertGreaterEqual(browser['cleanup_grace_seconds'], 120)
        grouped = budget(('browser', 'siwc'))
        self.assertLess(grouped['recommended_outer_seconds'], 2 * browser['recommended_outer_seconds'])
        self.assertLess(budget(('browser',), inventory_only=True)['recommended_outer_seconds'],
                        browser['recommended_outer_seconds'])
        self.assertGreater(browser['recommended_outer_seconds'],
                           browser['execution_seconds'] + browser['cleanup_grace_seconds'])

    def test_qualifier_timeout_sends_term_and_waits_existing_cleanup_never_passes(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleanup'
            child = ('import signal,time,pathlib\n'
                'def stop(*_):\n'
                ' time.sleep(0.15)\n'
                f' pathlib.Path({str(marker)!r}).write_text("cleanup-finished")\n'
                ' raise SystemExit(0)\n'
                'signal.signal(signal.SIGTERM,stop)\n'
                'time.sleep(60)\n')
            with self.assertRaises(subprocess.TimeoutExpired):
                qualify.run(sys.executable, '-c', child, timeout=1, cleanup_grace=3)
            self.assertEqual(marker.read_text(), 'cleanup-finished')

    def test_logged_command_timeout_reaps_owned_sigint_ignoring_child(self):
        with TemporaryDirectory() as directory, patch.object(validation, 'INTERRUPT_SECONDS', 0.1):
            with self.assertRaises(subprocess.TimeoutExpired):
                validation.command([sys.executable, '-c',
                    'import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);time.sleep(60)'],
                    log=Path(directory) / 'child.log', timeout=0.2)

    def test_real_sigterm_uses_original_runner_cleanup_and_preserves_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ready, cleaned = root / 'ready', root / 'cleaned'
            child = f'import pathlib,time;pathlib.Path({str(ready)!r}).touch();time.sleep(60)'
            script = f'''
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('synthetic_validation',{str(RUNNER)!r})
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
v.ROOT=pathlib.Path({directory!r})
v.git_state=lambda: {{'sha':'a'*40,'dirty':False}}
v.git_tree=lambda: 'b'*40
v.start_fixture=lambda env: ('synthetic-owned-id','synthetic-owned-name',12345)
v.owned_container=lambda *args: args == ('synthetic-owned-id','synthetic-owned-name',12345)
original=v.command
def command(argv,**kwargs):
 if argv[:3] == ['docker','rm','-f']:
  pathlib.Path({str(cleaned)!r}).write_text('owned-cleanup-finished')
  return ''
 return original(argv,**kwargs)
v.command=command
def profile(name,env,out,results,*args,**kwargs):
 v.command([sys.executable,'-c',{child!r}],log=out/'child.log')
v.run_profile=profile
sys.argv=['validate.py','--profile','browser','--execute']
raise SystemExit(v.main())
'''
            process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                end = time.monotonic() + 10
                while not ready.exists() and process.poll() is None and time.monotonic() < end:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), 'Synthetic child did not reach wait point')
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=10)
                report = json.loads(stdout)
                self.assertEqual((process.returncode, report['status'], report['error_type']),
                                 (1, 'stopped', 'KeyboardInterrupt'))
                self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')
                self.assertEqual(cleaned.read_text(), 'owned-cleanup-finished')
                stored = root / report['logs_dir'] / 'fixture-identity.json'
                self.assertEqual(json.loads(stored.read_text()), report['fixture_identity'])
                self.assertEqual(report['fixture_identity']['container_id'], 'synthetic-owned-id')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.communicate(timeout=5)
