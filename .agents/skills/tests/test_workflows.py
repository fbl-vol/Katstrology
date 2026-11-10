"""Synthetic policy/transport doubles only; no database, service, browser or provider access."""
import contextlib
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def module(name, relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


validation = module('kat_validation', '.agents/skills/kat-isolated-validation/scripts/validate.py')
activation = module('kat_activation', '.agents/skills/kat-local-activation/scripts/activate.py')
live = module('kat_live', '.agents/skills/kat-approved-live-check/scripts/live_check.py')
regression = module('kat_regression', '.agents/skills/kat-provider-continuation-regression/scripts/regress.py')
SHA = 'a' * 40
QUESTION = sha256(b'synthetic already entered question').hexdigest()


def invoke(fn, args):
    out = io.StringIO()
    with patch.object(sys, 'argv', ['script.py', *args]), contextlib.redirect_stdout(out):
        code = fn()
    return code, json.loads(out.getvalue())


class WorkflowTests(unittest.TestCase):
    def test_validation_default_is_non_mutating_and_scrubs_ambient_fixture(self):
        with patch.object(validation, 'git_state', return_value={'sha': SHA, 'dirty': True}), \
             patch.object(validation, 'start_fixture', side_effect=AssertionError('fixture touched')):
            code, report = invoke(validation.main, [])
        self.assertEqual(code, 0)
        self.assertEqual(report['action'], 'plan')
        self.assertEqual(report['unrun'], list(validation.PROFILES))
        with patch.dict(validation.os.environ, {'KAT_ISOLATED_TEST_DSN': 'real-unsafe',
                                                'PGPASSWORD': 'real-unsafe'}):
            env = validation.clean_environment()
        self.assertNotIn('KAT_ISOLATED_TEST_DSN', env)
        self.assertNotIn('PGPASSWORD', env)
        self.assertEqual(env['DOCKER_HOST'], 'unix:///var/run/docker.sock')
        self.assertEqual(validation.browser_env(env, 'siwc', Path('/tmp/synthetic'))['KAT_BROWSER_FAKE_PLAN'], '0')
        self.assertEqual(validation.browser_env(env, 'browser', Path('/tmp/synthetic'))['KAT_BROWSER_FAKE_PLAN'], '1')
        clock = validation.browser_env(env, 'clock', Path('/tmp/synthetic'))
        self.assertEqual((clock['KAT_BROWSER_SIWC'], clock['KAT_BROWSER_FAKE_PLAN']), ('1', '1'))

    def test_browser_override_is_the_only_ambient_kat_input_retained(self):
        with TemporaryDirectory() as temp:
            browser = Path(temp) / 'synthetic-browser'
            browser.write_text('#!/bin/sh\nexit 0\n')
            browser.chmod(0o700)
            ambient = {'KAT_BROWSER_BIN': str(browser), 'KAT_BROWSER_TEST_PORT': '8765',
                       'KAT_BROWSER_DIST': '/unowned/dist', 'KAT_BROWSER_SIWC': '1',
                       'KAT_ISOLATED_TEST_DSN': 'unowned', 'PGPASSWORD': 'unowned',
                       'OPENAI_API_KEY': 'synthetic', 'SIWC_TOKEN': 'synthetic',
                       'https_proxy': 'http://unowned', 'DOCKER_HOST': 'tcp://unowned'}
            with patch.dict(validation.os.environ, ambient, clear=True):
                clean = validation.clean_environment(include_browser=True)
                self.assertNotIn('KAT_BROWSER_BIN', validation.clean_environment())
                with patch.object(validation, 'free_port', return_value=23456):
                    env = validation.browser_env(clean, 'browser', Path(temp) / 'owned-dist')
            self.assertEqual(clean['KAT_BROWSER_BIN'], str(browser))
            for key in ambient.keys() - {'KAT_BROWSER_BIN', 'DOCKER_HOST'}:
                self.assertNotIn(key, clean)
            self.assertEqual(clean['DOCKER_HOST'], 'unix:///var/run/docker.sock')
            self.assertEqual(env['KAT_BROWSER_BIN'], str(browser))
            self.assertEqual(env['KAT_BROWSER_TEST_PORT'], '23456')
            self.assertEqual(env['KAT_BROWSER_DIST'], str(Path(temp) / 'owned-dist'))
            self.assertEqual(env['KAT_BROWSER_SIWC'], '0')

    def test_browser_override_refuses_invalid_paths_without_fallback(self):
        with TemporaryDirectory() as temp:
            nonexecutable = Path(temp) / 'not-executable'
            nonexecutable.touch(mode=0o600)
            for value in ('', 'relative-browser', temp, str(nonexecutable), temp + '/missing'):
                with self.subTest(value=value), patch.dict(validation.os.environ,
                        {'KAT_BROWSER_BIN': value}, clear=True):
                    with self.assertRaisesRegex(ValueError, 'absolute executable file'):
                        validation.clean_environment(include_browser=True)
                    # Docker ownership/cleanup must not depend on browser availability.
                    self.assertNotIn('KAT_BROWSER_BIN', validation.clean_environment())
        with patch.dict(validation.os.environ, {}, clear=True):
            self.assertNotIn('KAT_BROWSER_BIN', validation.clean_environment())

    def test_invalid_browser_override_refuses_before_fixture_start(self):
        with TemporaryDirectory() as temp, \
             patch.object(validation, 'ROOT', Path(temp)), \
             patch.object(validation, 'git_state', return_value={'sha': SHA, 'dirty': False}), \
             patch.dict(validation.os.environ, {'KAT_BROWSER_BIN': temp + '/missing'}, clear=True), \
             patch.object(validation, 'start_fixture', side_effect=AssertionError('fixture touched')):
            code, report = invoke(validation.main, ['--profile', 'browser', '--execute'])
        self.assertEqual((code, report['status'], report['error_type']), (1, 'stopped', 'ValueError'))
        self.assertEqual(report['unrun'], ['browser'])
        self.assertNotIn('fixture', report)

    def test_validation_never_removes_unowned_fixture(self):
        def command(argv, **kwargs):
            if argv[:2] == ['docker', 'run']:
                Path(argv[argv.index('--cidfile') + 1]).write_text('a' * 64)
                return 'a' * 64
            return '0.0.0.0:5432'
        with TemporaryDirectory() as directory, \
             patch.object(validation, 'command', side_effect=command) as calls, \
             patch.object(validation, 'owned_container', return_value=False):
            with self.assertRaises(RuntimeError):
                validation.start_fixture(validation.clean_environment(), Path(directory))
            self.assertFalse(any(call.args[0][:2] == ['docker', 'rm'] for call in calls.call_args_list))

    def test_activation_plan_and_explicit_receipt_refusal(self):
        args = ['--commit', SHA, '--service', 'kat-synthetic.service',
                '--origin', 'http://127.0.0.1:8765']
        with patch.object(activation, 'exact_tip', return_value=True), \
             patch.object(activation, 'run', side_effect=AssertionError('service touched')):
            code, report = invoke(activation.main, args)
        self.assertEqual((code, report['status']), (0, 'planned'))
        with patch.object(activation, 'exact_tip', return_value=True), \
             patch.object(activation, 'metadata', side_effect=AssertionError('DB touched')):
            code, report = invoke(activation.main, args + ['--execute'])
        self.assertEqual((code, report['error_type']), (1, 'ValueError'))

    def test_activation_migration_gate_precedes_build_and_restart(self):
        args = ['--commit', SHA, '--service', 'kat-synthetic.service',
                '--origin', 'http://127.0.0.1:8765', '--execute']
        with TemporaryDirectory() as temp:
            receipt = Path(temp) / 'scope.json'
            receipt.write_text(json.dumps({'action': 'activate-local', 'commit': SHA,
                'service': 'kat-synthetic.service', 'origin': 'http://127.0.0.1:8765',
                'allow_migrations': False}))
            with patch.object(activation, 'exact_tip', return_value=True), \
                 patch.object(activation, 'metadata', return_value=((1, 2, 3, 4, 5), 1)), \
                 patch.dict(activation.os.environ, {'KAT_LOCAL_ACTIVATION_DSN': 'synthetic-only'}), \
                 patch.object(activation, 'run', side_effect=AssertionError('build/restart touched')):
                code, report = invoke(activation.main, args + ['--approval-file', str(receipt)])
        self.assertEqual((code, report['status']), (1, 'stopped'))
        self.assertFalse(report['service_restarted'])

    def live_args(self, op='send'):
        return [op, '--commit', SHA, '--origin', 'http://127.0.0.1:8765',
                '--session', 'kat-synthetic', '--question-sha256', QUESTION,
                '--model-slug', 'synthetic-model']

    def live_receipt(self, temp):
        receipt = {'action': 'one-live-send', 'approval_id': 'synthetic-one',
            'commit': SHA, 'origin': 'http://127.0.0.1:8765', 'session': 'kat-synthetic',
            'question_sha256': QUESTION, 'model_slug': 'synthetic-model',
            'scope': [['synthetic-person', 'synthetic-chart']]}
        path = Path(temp) / 'receipt.json'
        path.write_text(json.dumps(receipt))
        return path, receipt

    def test_live_plan_never_contacts_browser_and_send_requires_receipt(self):
        with patch.object(live, 'git_tip', return_value=(SHA, False)), \
             patch.object(live, 'browser', side_effect=AssertionError('browser touched')):
            code, report = invoke(live.main, self.live_args())
            self.assertEqual((code, report['status'], report['browser_calls']), (0, 'planned', 0))
            code, report = invoke(live.main, self.live_args() + ['--execute'])
            self.assertEqual((code, report['status'], report['browser_calls']), (1, 'stopped', 0))

    def test_live_guard_survives_ambiguous_click_and_refuses_resend(self):
        with TemporaryDirectory() as temp:
            receipt_path, receipt = self.live_receipt(temp)
            expected = live.scope_digest(receipt['scope'])
            preflight = {'origin': receipt['origin'], 'model_slug': receipt['model_slug'],
                'question_sha256': QUESTION, 'question_length': 32,
                'scope_sha256': expected, 'scope_count': 1, 'conversation_id': 'synthetic-thread',
                'previous_turns': 0, 'send_ready': True, 'dialog_open': False}
            calls = []
            def fake_browser(session, script):
                calls.append(script)
                if script == 'dispatch.js':
                    raise RuntimeError('ACK ambiguous after click')
                return preflight
            with patch.object(live, 'GUARDS', Path(temp) / 'guards'), \
                 patch.object(live, 'git_tip', return_value=(SHA, False)), \
                 patch.object(live, 'browser', side_effect=fake_browser):
                argv = self.live_args() + ['--execute', '--approval-file', str(receipt_path)]
                code, report = invoke(live.main, argv)
                self.assertEqual((code, report['status']), (2, 'ambiguous-send-attempt'))
                self.assertTrue(report['guard_recorded'])
                self.assertEqual(calls, ['preflight.js', 'dispatch.js'])
                code, report = invoke(live.main, argv)
                self.assertEqual((code, report['status']), (1, 'stopped'))
                self.assertEqual(calls, ['preflight.js', 'dispatch.js'])
                self.assertEqual(len(list((Path(temp) / 'guards').glob('*.json'))), 1)
                archived = {'status': 'complete', 'visible_turns': 1, 'scope_sha256': expected,
                    'model_slug': 'synthetic-model', 'answer_length': 42, 'complete_markers': 1,
                    'tool_calls': 8, 'tool_results': 8, 'event_count': 30, 'pages': 1}
                with patch.object(live, 'browser', return_value=archived) as observing:
                    code, report = invoke(live.main, self.live_args('observe') + argv[-3:])
                self.assertEqual((code, report['status'], report['metadata']['tool_results']),
                                 (0, 'complete', 8))
                observing.assert_called_once_with('kat-synthetic', 'observe.js')
                self.assertNotIn('synthetic already entered question', json.dumps(report))

    def test_live_wrong_selection_refuses_before_guard_and_observe_is_read_only(self):
        with TemporaryDirectory() as temp:
            receipt_path, receipt = self.live_receipt(temp)
            with patch.object(live, 'GUARDS', Path(temp) / 'guards'), \
                 patch.object(live, 'git_tip', return_value=(SHA, False)), \
                 patch.object(live, 'browser', return_value={'origin': receipt['origin'],
                     'model_slug': 'synthetic-model', 'question_sha256': QUESTION,
                     'scope_sha256': sha256(b'wrong selection').hexdigest()}):
                argv = self.live_args() + ['--execute', '--approval-file', str(receipt_path)]
                code, report = invoke(live.main, argv)
                self.assertEqual((code, report['status']), (1, 'stopped'))
                self.assertFalse((Path(temp) / 'guards').exists())
                code, report = invoke(live.main, self.live_args('observe') + argv[-3:])
                self.assertEqual((code, report['status']), (1, 'stopped'))

    def test_regression_plan_does_not_run(self):
        with patch.object(regression.subprocess, 'run', side_effect=AssertionError('tests touched')):
            code, report = invoke(regression.main, ['--case', 'many-reads'])
        self.assertEqual((code, report['status']), (0, 'planned'))
        self.assertTrue(report['backend_selectors'])
        self.assertIsNone(report['browser_filter'])

    def test_regression_all_keeps_capacity_covered_once_and_uses_one_owned_run(self):
        completed = regression.subprocess.CompletedProcess([], 0, stdout='{"status":"ok"}', stderr='')
        with patch.object(regression.subprocess, 'run', return_value=completed) as run:
            code, report = invoke(regression.main, ['--case', 'all', '--execute'])
        self.assertEqual((code, report['status'], len(report['runs'])), (0, 'passed', 1))
        argv = run.call_args.args[0]
        self.assertEqual(argv[2:5], ['--profiles', 'backend', 'siwc'])
        self.assertIn('--tests', argv)
        self.assertEqual(argv[-2:], ['--browser-grep', regression.BROWSER_GREP])
        self.assertNotIn('test_continuation_capacity_preserves_call_result_but_never_sends_overflow',
                         ' '.join(report['backend_selectors']))
        self.assertEqual(len(report['backend_selectors']), 4)
        code, focused = invoke(regression.main, ['--case', 'capacity'])
        self.assertEqual((code, len(focused['backend_selectors'])), (0, 2))


class ValidationPerformanceTests(unittest.TestCase):
    @contextlib.contextmanager
    def synthetic_runner(self):
        calls = []

        def fake_command(argv, **kwargs):
            calls.append((argv, kwargs))
            log = kwargs.get('log')
            if log:
                log.write_text('1 passed (1.0s)\n')
                if '--timings' in argv:
                    Path(argv[argv.index('--timings') + 1]).write_text(json.dumps({
                        'sample_count': 1, 'slowest_tests': [], 'slowest_fixture_setup': []}))
                if log.name.endswith('-build.log'):
                    dist = Path(argv[argv.index('--outDir') + 1])
                    dist.mkdir(parents=True)
                    (dist / 'index.html').write_text('synthetic build')
                env = kwargs.get('env', {})
                if 'KAT_BROWSER_INVENTORY_FILE' in env:
                    Path(env['KAT_BROWSER_INVENTORY_FILE']).write_text(json.dumps({
                        'workers': 1, 'status': 'passed', 'errors': 0,
                        'tests': [{'id': 'b' * 64, 'allowedSkip': False,
                                   'outcomes': [] if '--list' in argv else ['passed']}]}))
                if 'PLAYWRIGHT_JSON_OUTPUT_FILE' in env and '--list' not in argv:
                    Path(env['PLAYWRIGHT_JSON_OUTPUT_FILE']).write_text(json.dumps({
                        'suites': [{'specs': [{'tests': [{'expectedStatus': 'passed',
                            'results': [{'status': 'passed'}]}]}]}],
                        'stats': {'expected': 1, 'unexpected': 0, 'flaky': 0, 'skipped': 0}}))
                    Path(env['KAT_BROWSER_PROGRESS_FILE']).write_text(json.dumps({
                        'status': 'passed', 'total': 1, 'started': 1, 'finished': 1,
                        'global_errors': 0, 'active_omitted': 0, 'active': [],
                        'outcomes': {'passed': 1}, 'resources': {}}))
            return ''

        with TemporaryDirectory() as temp, \
             patch.object(validation, 'ROOT', Path(temp)), \
             patch.object(validation, 'git_state', return_value={'sha': SHA, 'dirty': False}), \
             patch.object(validation, 'git_tree', return_value='c' * 40), \
             patch.object(validation, 'start_fixture', return_value=(
                 'synthetic-id', 'kat-origin-isolated-synthetic', 34567)) as start, \
             patch.object(validation, 'owned_container', return_value=True) as owned, \
             patch.object(validation, 'command', side_effect=fake_command) as command:
            yield calls, start, owned, command

    def test_shard_is_passed_to_native_discovery_and_execution(self):
        with self.synthetic_runner() as (calls, start, _, _):
            code, report = invoke(validation.main, ['--profile', 'browser', '--browser-shard', '2/4', '--execute'])
        self.assertEqual((code, report['browser_shard'], report['tree']), (0, '2/4', 'c' * 40))
        start.assert_called_once()
        native = [argv for argv, _ in calls if '--shard=2/4' in argv]
        self.assertEqual(len(native), 2)
        self.assertIn('--list', native[0])
        self.assertNotIn('--list', native[1])
        self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')

    def test_inventory_only_never_builds_or_starts_fixture(self):
        with self.synthetic_runner() as (calls, start, _, _):
            code, report = invoke(validation.main, ['--profile', 'browser', '--inventory-only', '--execute'])
        self.assertEqual(code, 0)
        start.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertIn('--list', calls[0][0])
        self.assertEqual(report['results']['browser']['status'], 'discovered')

    def test_interrupt_cleans_owned_fixture_and_never_passes(self):
        with self.synthetic_runner() as (_, _, _, command):
            original = command.side_effect
            def interrupt(argv, **kwargs):
                if kwargs.get('log') and kwargs['log'].name == 'browser.log':
                    raise KeyboardInterrupt
                return original(argv, **kwargs)
            command.side_effect = interrupt
            code, report = invoke(validation.main, ['--profile', 'browser', '--browser-shard', '1/4', '--execute'])
        self.assertEqual((code, report['status'], report['error_type']), (1, 'stopped', 'KeyboardInterrupt'))
        self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')

    def test_grouped_plan_preserves_order_deduplicates_and_never_executes(self):
        with self.synthetic_runner() as (calls, start, _, _):
            code, report = invoke(validation.main, ['--profiles', 'clock', 'browser', 'clock'])
        self.assertEqual((code, report['action']), (0, 'plan'))
        self.assertEqual(report['selected'], ['clock', 'browser'])
        self.assertEqual(report['unrun'], report['selected'])
        self.assertEqual(report['timings'], [])
        start.assert_not_called()
        self.assertEqual(calls, [])

    def test_grouped_profiles_share_one_fixture_and_one_normal_build(self):
        profiles = ['browser', 'siwc', 'clock']
        with self.synthetic_runner() as (calls, start, _, _):
            code, report = invoke(validation.main, ['--profiles', *profiles, 'browser', '--execute'])
        self.assertEqual((code, report['selected'], report['unrun']), (0, profiles, []))
        start.assert_called_once()
        self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')
        logs = [kwargs['log'].name for _, kwargs in calls if kwargs.get('log')]
        self.assertEqual(logs.count('normal-build.log'), 1)
        self.assertEqual(sum(argv[:3] == ['docker', 'rm', '-f'] for argv, _ in calls), 1)
        test_calls = [(argv, kwargs) for argv, kwargs in calls
                      if kwargs.get('log') and kwargs['log'].stem in profiles]
        self.assertEqual([kwargs['log'].stem for _, kwargs in test_calls], profiles)
        self.assertEqual([kwargs['env']['KAT_BROWSER_FAKE_PLAN'] for _, kwargs in test_calls],
                         ['1', '0', '1'])
        self.assertTrue(all('KAT_BROWSER_ASSISTANT_PROOF' not in kwargs['env'] and
                            'KAT_LAYOUT_PRIVATE_REFERENCE' not in kwargs['env']
                            for _, kwargs in test_calls))
        for argv, kwargs in test_calls:
            self.assertNotEqual(kwargs['env']['KAT_BROWSER_TEST_PORT'], '8765')
            self.assertNotIn('--pass-with-no-tests', argv)
        for result in report['results'].values():
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['diagnostics']['counts'],
                             {'expected': 1, 'unexpected': 0, 'flaky': 0, 'skipped': 0})
            self.assertEqual(result['diagnostics']['failure_count'], 0)
            self.assertEqual(result['progress']['status'], 'passed')
            self.assertEqual(result['progress']['finished'], 1)
        self.assertEqual([entry['stage'] for entry in report['timings']], [
            'fixture-start', 'normal-build', 'browser-tests', 'siwc-tests',
            'clock-tests', 'fixture-cleanup'])
        self.assertTrue(all(entry['seconds'] >= 0 for entry in report['timings']))

    def test_grouped_backend_and_siwc_use_distinct_filters_one_template_and_fixture(self):
        with self.synthetic_runner() as (calls, start, _, _):
            code, report = invoke(validation.main, ['--profiles', 'backend', 'siwc',
                '--tests', 'tests.archive.test_store', '--browser-grep', 'synthetic selection', '--execute'])
        self.assertEqual((code, report['selected'], report['unrun']),
                         (0, ['backend', 'siwc'], []))
        start.assert_called_once()
        self.assertEqual([entry['stage'] for entry in report['timings']], [
            'fixture-start', 'template-setup', 'backend-tests', 'normal-build',
            'siwc-tests', 'fixture-cleanup'])
        self.assertEqual(report['results']['backend']['diagnostics']['sample_count'], 1)
        backend = next(argv for argv, kwargs in calls if kwargs.get('log') and
                       kwargs['log'].name == 'backend.log')
        browser = next(argv for argv, kwargs in calls if kwargs.get('log') and
                       kwargs['log'].name == 'siwc.log')
        self.assertIn('tests.archive.test_store', backend)
        self.assertNotIn('--grep', backend)
        self.assertEqual(browser[-2:], ['--grep', 'synthetic selection'])
        self.assertNotIn('tests.archive.test_store', browser)
        self.assertEqual(sum(argv[:3] == ['docker', 'rm', '-f'] for argv, _ in calls), 1)

    def test_browser_filter_applies_to_each_selected_profile(self):
        with self.synthetic_runner() as (calls, _, _, _):
            code, report = invoke(validation.main, ['--profiles', 'browser', 'clock',
                '--browser-grep', 'synthetic selected behavior', '--execute'])
        self.assertEqual(code, 0)
        tests = [argv for argv, _ in calls if '--grep' in argv and '--list' not in argv]
        self.assertEqual(len(tests), 2)
        self.assertTrue(all(argv[-2:] == ['--grep', 'synthetic selected behavior'] for argv in tests))
        self.assertEqual(report['filters']['browser_grep'], 'synthetic selected behavior')

    def test_private_layout_comparison_requires_explicit_runner_flag_and_normal_browser(self):
        with self.synthetic_runner() as (calls, _, _, _):
            code, report = invoke(validation.main, ['--profiles', 'browser', 'siwc',
                '--private-layout-reference', '--execute'])
        self.assertEqual(code, 0)
        self.assertTrue(report['filters']['private_layout_reference'])
        test_envs = {kwargs['log'].stem: kwargs['env'] for _, kwargs in calls
                     if kwargs.get('log') and kwargs['log'].stem in ('browser', 'siwc')}
        self.assertEqual(test_envs['browser']['KAT_LAYOUT_PRIVATE_REFERENCE'], '1')
        self.assertNotIn('KAT_LAYOUT_PRIVATE_REFERENCE', test_envs['siwc'])

    def test_failed_profile_keeps_timings_cleans_up_and_leaves_later_profile_unrun(self):
        with self.synthetic_runner() as (_, _, _, command):
            original = command.side_effect

            def fail_test(argv, **kwargs):
                if kwargs.get('log') and kwargs['log'].name == 'browser.log':
                    raise validation.subprocess.CalledProcessError(1, ['private-command-must-not-leak'])
                return original(argv, **kwargs)

            command.side_effect = fail_test
            code, report = invoke(validation.main, ['--profiles', 'browser', 'clock', '--execute'])
        self.assertEqual((code, report['status']), (1, 'stopped'))
        self.assertEqual(report['unrun'], ['clock'])
        self.assertEqual(report['results']['browser'].pop('inventory')['tests'][0]['id'], 'b' * 64)
        self.assertEqual(report['results'], {'browser': {
            'status': 'stopped', 'log': str(Path(report['logs_dir']) / 'browser.log'),
            'error_type': 'CalledProcessError', 'returncode': 1,
            'diagnostics_status': 'unavailable', 'progress_status': 'unavailable'}})
        self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')
        stopped = [entry['stage'] for entry in report['timings'] if entry['status'] == 'stopped']
        self.assertEqual(stopped, ['browser-tests'])
        self.assertEqual(report['timings'][-1]['stage'], 'fixture-cleanup')
        self.assertNotIn('private-command-must-not-leak', json.dumps(report))

    def test_successful_command_without_diagnostics_stops_and_cleans_up(self):
        with self.synthetic_runner() as (_, _, _, command):
            original = command.side_effect

            def omit_diagnostics(argv, **kwargs):
                result = original(argv, **kwargs)
                report_path = kwargs.get('env', {}).get('PLAYWRIGHT_JSON_OUTPUT_FILE')
                if report_path and '--list' not in argv:
                    Path(report_path).unlink()
                return result

            command.side_effect = omit_diagnostics
            code, report = invoke(validation.main, ['--profiles', 'browser', 'clock', '--execute'])
        self.assertEqual((code, report['status'], report.get('error_type')),
                         (1, 'stopped', 'RuntimeError'))
        self.assertEqual(report['results']['browser']['status'], 'stopped')
        self.assertEqual(report['results']['browser']['diagnostics_status'], 'unavailable')
        self.assertEqual(report['results']['browser']['progress']['status'], 'passed')
        self.assertEqual(report['unrun'], ['clock'])
        self.assertEqual(report['fixture_cleanup'], 'owned-container-removed')
        self.assertEqual(report['timings'][-1]['stage'], 'fixture-cleanup')

    def test_cleanup_failure_is_reported_and_never_removes_unowned_fixture(self):
        with self.synthetic_runner() as (calls, _, owned, _):
            owned.return_value = False
            code, report = invoke(validation.main, ['--profile', 'backend', '--execute'])
        self.assertEqual((code, report['status']), (1, 'stopped'))
        self.assertEqual(report['fixture_cleanup'], 'identity-mismatch-manual-inspection-required')
        self.assertEqual(report['timings'][-1]['status'], 'stopped')
        self.assertFalse(any(argv[:2] == ['docker', 'rm'] for argv, _ in calls))

    def test_cleanup_inspection_error_still_emits_sanitized_failure_report(self):
        with self.synthetic_runner() as (_, _, owned, _):
            owned.side_effect = validation.subprocess.CalledProcessError(1, ['private-inspection'])
            code, report = invoke(validation.main, ['--profile', 'backend', '--execute'])
        self.assertEqual((code, report['status']), (1, 'stopped'))
        self.assertEqual(report['cleanup_error_type'], 'CalledProcessError')
        self.assertEqual(report['timings'][-1]['status'], 'stopped')
        self.assertNotIn('private-inspection', json.dumps(report))

    def test_timing_records_failure_without_changing_exception(self):
        timings = []
        with patch.object(validation, 'perf_counter', side_effect=[10, 12.75]):
            with self.assertRaisesRegex(ValueError, 'synthetic failure'):
                with validation.timed_stage(timings, 'synthetic-stage'):
                    raise ValueError('synthetic failure')
        self.assertEqual(timings, [{'stage': 'synthetic-stage', 'status': 'stopped', 'seconds': 2.75}])

    def test_invalid_mixed_selectors_fail_before_any_execution(self):
        invalid = [
            ['--profile', 'browser', '--profiles', 'clock'],
            ['--profiles', 'probes', 'browser', '--tests', 'tests.archive.test_store'],
            ['--profiles', 'backend', 'probes', '--browser-grep', 'synthetic'],
            ['--profiles', 'all'],
            ['--profile', 'siwc', '--private-layout-reference'],
            *[['--profile', 'browser', '--browser-shard', value] for value in ('0/4', '5/4', '1/0', '1/65', '2', '1/4x')],
            ['--profile', 'all', '--browser-shard', '1/4'],
            ['--profile', 'browser', '--browser-shard', '1/4', '--browser-grep', 'partial'],
            ['--profile', 'siwc', '--inventory-only'],
        ]
        with patch.object(validation, 'git_state', side_effect=AssertionError('execution started')):
            for args in invalid:
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as stopped:
                        invoke(validation.main, args)
                    self.assertEqual(stopped.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
