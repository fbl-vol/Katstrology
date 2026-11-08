"""Failure evidence must survive the hosted boundary without publishing raw logs."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from tests import runner as validation_runner

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kat_validate', ROOT /
    '.agents/skills/kat-isolated-validation/scripts/validate.py')
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)


class ValidationDiagnosticsTests(unittest.TestCase):
    def run_cases(self, case, report):
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0,
            resultclass=lambda *a, **kw: validation_runner.TimedResult(
                *a, report_path=report, **kw)).run(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        result.write_report('passed' if result.wasSuccessful() else 'failed')
        return result, json.loads(report.read_text())

    def test_subtests_are_bounded_and_omit_messages_parameters_and_custom_ids(self):
        marker = 'SYNTHETIC_PASSWORD_AND_PRIVATE_PROMPT'

        class FailingCase(unittest.TestCase):
            def id(self):
                return marker

            def test_failure(self):
                code = compile('raise AssertionError(' + repr(marker) + ')',
                               '/synthetic-private/' + marker + '.py', 'exec')

                def fail(depth):
                    if depth:
                        fail(depth - 1)
                    else:
                        exec(code)

                for index in range(25):
                    with self.subTest(prompt=marker, index=index):
                        fail(12)

        with tempfile.TemporaryDirectory() as directory:
            result, report = self.run_cases(FailingCase, Path(directory) / 'report.json')
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['tests_run'], 1)
        self.assertEqual(report['failure_count'], 25)
        self.assertEqual(len(report['failures']), 20)
        self.assertEqual(report['failures_omitted'], 5)
        self.assertNotIn(marker, json.dumps(report))
        for failure in report['failures']:
            self.assertTrue(failure['test'].endswith('.test_failure'))
            self.assertEqual(failure['exception_type'], 'AssertionError')
            self.assertEqual(failure['outcome'], 'failure')
            self.assertIn('tests/operations/test_validation_runner.py', [frame['file'] for frame in failure['frames']])
            self.assertEqual(len(failure['frames']), 8)
            for frame in failure['frames']:
                self.assertEqual(set(frame), {'file', 'line'})

    def test_fixture_errors_and_unexpected_success_remain_failures(self):
        class FixtureError(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError('SYNTHETIC_DSN_NOT_FOR_PUBLICATION')

            def test_never_runs(self):
                raise AssertionError('unreachable')

        class UnexpectedSuccess(unittest.TestCase):
            @unittest.expectedFailure
            def test_succeeds(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / 'report.json'
            for case, outcome, exception in ((FixtureError, 'error', 'RuntimeError'),
                                             (UnexpectedSuccess, 'unexpected_success', None)):
                with self.subTest(outcome=outcome):
                    result, report = self.run_cases(case, report_path)
                    self.assertFalse(result.wasSuccessful())
                    self.assertEqual(report['failure_count'], 1)
                    self.assertEqual(report['failures'][0]['outcome'], outcome)
                    self.assertEqual(report['failures'][0]['exception_type'], exception)
                    self.assertNotIn('SYNTHETIC_DSN', json.dumps(report))

    def test_abrupt_child_exit_leaves_checkpoint_without_claiming_completion(self):
        child = '''import os, sys, types, unittest
from tests.runner import main
module = types.ModuleType('synthetic_checkpoint')
class ExitCase(unittest.TestCase):
    def test_exit(self):
        os._exit(19)
module.ExitCase = ExitCase
sys.modules[module.__name__] = module
sys.argv = ['validation_runner', '--timings', sys.argv[1], module.__name__]
raise SystemExit(main())
'''
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            child_result = subprocess.run([sys.executable, '-c', child, str(report)],
                cwd=ROOT, env=validate.clean_environment(), capture_output=True, timeout=20)
            self.assertEqual(child_result.returncode, 19)
            checkpoint = json.loads(report.read_text())
            self.assertEqual(checkpoint['status'], 'running')
            self.assertEqual(checkpoint['tests_run'], 1)
            self.assertEqual(checkpoint['sample_count'], 0)
            self.assertEqual(checkpoint['last_started_test'], '__main__.ExitCase.test_exit')
            self.assertFalse(report.with_suffix('.tmp').exists())

    def test_real_failed_child_keeps_structured_diagnostics_and_nonzero_status(self):
        # Missing synthetic module is an actual unittest loader failure, not a
        # fabricated successful report or a process mock returning a failure code.
        with tempfile.TemporaryDirectory(prefix='validation-diagnostics-', dir=ROOT / '.local') as directory:
            results, timings = {}, []
            with redirect_stderr(io.StringIO()), self.assertRaises(subprocess.CalledProcessError) as caught:
                validate.run_profile('backend', validate.clean_environment(), Path(directory), results,
                    ['tests.operations.test_intentionally_missing_validation_module'], timings=timings)
            self.assertEqual(caught.exception.returncode, 1)
            backend = results['backend']
            self.assertEqual(backend['status'], 'stopped')
            self.assertEqual(backend['returncode'], 1)
            self.assertEqual(backend['diagnostics']['status'], 'failed')
            failure = backend['diagnostics']['failures'][0]
            self.assertEqual(failure['exception_type'], 'ImportError')
            self.assertTrue(failure['test'].endswith('.test_intentionally_missing_validation_module'))
            self.assertEqual(timings[0]['status'], 'stopped')

    def test_missing_or_corrupt_report_never_masks_process_failure(self):
        for contents in (None, '{invalid', 'x' * 131073):
            with self.subTest(contents='missing' if contents is None else len(contents)), \
                    tempfile.TemporaryDirectory(dir=ROOT / '.local') as directory:
                out = Path(directory)
                if contents is not None:
                    (out / 'backend-timing.json').write_text(contents)
                failure = subprocess.CalledProcessError(-9, ['SYNTHETIC_SECRET_COMMAND'])
                results = {}
                with patch.object(validate, 'command', side_effect=failure), redirect_stderr(io.StringIO()), \
                        self.assertRaises(subprocess.CalledProcessError) as caught:
                    validate.run_profile('backend', {}, out, results, timings=[])
                self.assertIs(caught.exception, failure)
                self.assertEqual(results['backend']['returncode'], -9)
                self.assertEqual(results['backend']['diagnostics_status'], 'unavailable')
                self.assertNotIn('SYNTHETIC_SECRET', json.dumps(results))

    def test_browser_report_is_bounded_and_excludes_payloads_and_private_paths(self):
        marker = 'SYNTHETIC_PRIVATE_PROMPT'
        error = {'message': marker, 'snippet': marker,
                 'location': {'file': '/private/' + marker + '.ts', 'line': 1},
                 'stack': f'{marker}\n    at {ROOT}/web/tests/conversation/instant-send.spec.ts:123:7\n'
                          f'    at /private/{marker}.ts:4:2'}
        result = {'status': 'failed', 'errors': [error], 'stdout': [marker],
                  'attachments': [{'body': marker}]}
        spec = {'file': 'conversation/instant-send.spec.ts', 'line': 20, 'title': marker,
                'tests': [{'expectedStatus': 'passed', 'results': [result] * 25},
                          {'expectedStatus': 'failed', 'results': [result]}]}
        report = {'suites': [{'suites': [{'specs': [spec]}]}], 'errors': [error],
                  'stats': {'expected': 1, 'unexpected': 25, 'skipped': 0, 'flaky': 0, 'private': marker}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text(json.dumps(report))
            public = validate.browser_diagnostics(path)
        self.assertEqual(public['failure_count'], 26)
        self.assertEqual(public['failures_omitted'], 6)
        self.assertEqual(len(public['failures']), 20)
        self.assertEqual(public['failures'][0], {
            'status': 'failed', 'test': {'file': 'web/tests/conversation/instant-send.spec.ts', 'line': 20},
            'locations': [{'file': 'web/tests/conversation/instant-send.spec.ts', 'line': 123}]})
        self.assertNotIn(marker, json.dumps(public))
        self.assertEqual(set(public['counts']), {'expected', 'unexpected', 'skipped', 'flaky'})

    def test_real_playwright_json_failure_survives_without_raw_content(self):
        marker = 'SYNTHETIC_PRIVATE_BROWSER_VALUE'
        with tempfile.TemporaryDirectory(prefix='browser-diagnostics-', dir=ROOT / '.local') as directory:
            out = Path(directory)
            config = out / 'playwright.config.cjs'
            config.write_text('module.exports = ' + json.dumps({
                'testDir': directory, 'testMatch': '*.spec.cjs', 'workers': 1,
                'outputDir': str(out / 'output'),
                'reporter': [['json'], [str(ROOT / 'web/validation-reporter.cjs')]]}) + ';')
            (out / 'synthetic.spec.cjs').write_text(
                'const {test, expect} = require(' + json.dumps(str(ROOT / 'web/node_modules/@playwright/test')) + ');\n'
                f'test("{marker}", () => {{ expect("{marker}").toBe("other"); }});\n')
            report = out / 'report.json'
            env = validate.clean_environment() | {'PLAYWRIGHT_JSON_OUTPUT_FILE': str(report),
                'KAT_BROWSER_PROGRESS_FILE': str(out / 'progress.json')}
            completed = subprocess.run([str(ROOT / 'web/node_modules/.bin/playwright'), 'test',
                '--config', str(config)], env=env, cwd=ROOT / 'web', capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 1)
            self.assertIn(marker, report.read_text())  # Native raw report really includes sensitive-shaped data.
            public = validate.browser_diagnostics(report)
            self.assertEqual(public['failure_count'], 1)
            self.assertEqual(public['counts']['unexpected'], 1)
            self.assertEqual(public['failures'][0]['status'], 'failed')
            self.assertIsNone(public['failures'][0]['test'])  # Owned temporary file is not repo source.
            self.assertNotIn(marker, json.dumps(public))
            checkpoint = validate.browser_progress(out / 'progress.json')
            self.assertEqual(checkpoint['status'], 'failed')
            self.assertEqual(checkpoint['finished'], 1)
            self.assertEqual(checkpoint['outcomes']['failed'], 1)
            self.assertNotIn(marker, json.dumps(checkpoint))

    def test_browser_timeout_interrupts_native_runner_and_its_detached_webserver(self):
        with tempfile.TemporaryDirectory(prefix='browser-interrupt-', dir=ROOT / '.local') as directory:
            out = Path(directory)
            port = validate.free_port()
            server = out / 'server.py'
            pidfile = out / 'server.pid'
            server.write_text('from http.server import HTTPServer, BaseHTTPRequestHandler\n'
                'from pathlib import Path\nimport os\n'
                'class Handler(BaseHTTPRequestHandler):\n'
                ' def do_GET(self): self.send_response(200); self.end_headers()\n'
                f'server=HTTPServer(("127.0.0.1",{port}),Handler)\n'
                f'Path({str(pidfile)!r}).write_text(str(os.getpid()))\nserver.serve_forever()\n')
            progress, report = out / 'progress.json', out / 'report.json'
            (out / 'blocked.spec.cjs').write_text('const {test}=require(' +
                json.dumps(str(ROOT / 'web/node_modules/@playwright/test')) + ');\n'
                'test("SYNTHETIC_PRIVATE_TITLE",async()=>{test.setTimeout(0);await new Promise(()=>{});});')
            config = out / 'playwright.config.cjs'
            config.write_text('module.exports=' + json.dumps({'testDir': directory,
                'testMatch': '*.spec.cjs', 'workers': 1, 'outputDir': str(out / 'output'),
                'reporter': [['json'], [str(ROOT / 'web/validation-reporter.cjs')]],
                'webServer': {'command': shlex.join([sys.executable, str(server)]), 'cwd': directory,
                              'url': f'http://127.0.0.1:{port}', 'reuseExistingServer': False}}))
            env = validate.clean_environment() | {'PLAYWRIGHT_JSON_OUTPUT_FILE': str(report),
                'KAT_BROWSER_PROGRESS_FILE': str(progress)}
            native_popen = subprocess.Popen
            def ready_child(*args, **kwargs):
                process = native_popen(*args, **kwargs)
                deadline = monotonic() + 20
                while monotonic() < deadline:
                    if progress.exists() and json.loads(progress.read_text())['started'] == 1:
                        return process
                    if process.poll() is not None:
                        break
                    sleep(0.05)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                self.fail('Native Playwright child did not reach the controlled blocked test')
            try:
                with patch.object(validate.subprocess, 'Popen', side_effect=ready_child), \
                        self.assertRaises(subprocess.TimeoutExpired):
                    validate.command([str(ROOT / 'web/node_modules/.bin/playwright'), 'test',
                        '--config', str(config)], cwd=ROOT / 'web', env=env,
                        log=out / 'runner.log', timeout=0.2)
                self.assertEqual(validate.browser_progress(progress)['status'], 'interrupted')
                self.assertNotIn('SYNTHETIC_PRIVATE_TITLE', progress.read_text())
                self.assertTrue(report.is_file(), 'Native reporter must get its interruption callback')
                with socket.socket() as probe:
                    self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0,
                                        'Detached fixture still serves after timeout')
            finally:
                # A failed regression must not leak its own synthetic HTTP child.
                if pidfile.exists():
                    pid = int(pidfile.read_text())
                    cmdline = Path(f'/proc/{pid}/cmdline')
                    try:
                        if str(server).encode() in cmdline.read_bytes().split(b'\0'):
                            os.kill(pid, signal.SIGKILL)
                    except (FileNotFoundError, ProcessLookupError):
                        pass

    def test_failed_browser_profiles_preserve_exit_and_report_unavailability(self):
        for profile in ('browser', 'siwc', 'clock'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory(dir=ROOT / '.local') as directory:
                out = Path(directory)
                (out / 'normal-dist').mkdir()
                (out / 'normal-dist/index.html').write_text('synthetic build placeholder')
                (out / (profile + '-report.json')).write_text('{invalid')
                failure = subprocess.CalledProcessError(9, ['PRIVATE_COMMAND'])
                results = {}
                with patch.object(validate, 'discover_browser', return_value={
                        'workers': 1, 'status': 'passed', 'errors': 0,
                        'tests': [{'id': 'a' * 64, 'allowedSkip': False, 'outcomes': []}]}), \
                        patch.object(validate, 'command', side_effect=failure) as command, \
                        redirect_stderr(io.StringIO()), self.assertRaises(subprocess.CalledProcessError) as caught:
                    validate.run_profile(profile, {}, out, results, timings=[])
                self.assertIs(caught.exception, failure)
                self.assertEqual(results[profile]['returncode'], 9)
                self.assertEqual(results[profile]['status'], 'stopped')
                self.assertEqual(results[profile]['diagnostics_status'], 'unavailable')
                self.assertIn('--reporter=line,json,./validation-reporter.cjs,./inventory-reporter.cjs', command.call_args.args[0])
                self.assertEqual(command.call_args.kwargs['env']['PLAYWRIGHT_JSON_OUTPUT_FILE'],
                                 str(out / (profile + '-report.json')))
                self.assertNotIn('PRIVATE_COMMAND', json.dumps(results))

    def test_terminal_report_reaches_stderr_and_retains_cleanup_and_unrun_profiles(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        failure = subprocess.CalledProcessError(7, ['SYNTHETIC_SECRET_COMMAND'])
        original_command = validate.command

        def command(argv, **kwargs):
            if 'tests.support.template' in argv or argv[:2] == ['docker', 'rm']:
                return ''  # Only fixture lifecycle is substituted; no Docker effects.
            if 'tests.runner' in argv:
                raise failure
            return original_command(argv, **kwargs)

        with patch.object(sys, 'argv', ['validate.py', '--profiles', 'backend', 'browser',
                '--browser-grep', 'SYNTHETIC_PRIVATE_FILTER', '--execute']), \
                patch.object(validate, 'start_fixture', return_value=('owned-id', 'owned-name', 1)), \
                patch.object(validate, 'owned_container', return_value=True), \
                patch.object(validate, 'command', side_effect=command), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(validate.main(), 1)
        report = json.loads(stdout.getvalue())
        # Remove only this test's freshly owned, empty output directory.
        (ROOT / report['logs_dir']).rmdir()
        public = json.loads(stderr.getvalue().split('kat validation stopped: ', 1)[1])
        self.assertEqual(public['unrun'], ['browser'])
        self.assertEqual(public['fixture_cleanup'], 'owned-container-removed')
        self.assertEqual(public['results']['backend']['returncode'], 7)
        self.assertEqual(public['error_type'], 'CalledProcessError')
        self.assertNotIn('SYNTHETIC_SECRET_COMMAND', stderr.getvalue())
        self.assertNotIn('SYNTHETIC_PRIVATE_FILTER', stderr.getvalue())
        self.assertEqual(report['status'], 'stopped')


if __name__ == '__main__':
    unittest.main()
