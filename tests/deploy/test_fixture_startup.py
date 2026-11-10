"""A1 cold/ambiguous startup boundaries; Docker is explicitly doubled throughout."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tests.deploy.test_validation_deadlines import validation
from deploy.validation_budget import budget, STARTUP_SECONDS


class FixtureStartupTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(self.enterContext(TemporaryDirectory()))
        self.identifier = 'a' * 64
        self.timeout = False
        self.write_id = True
        self.foreign = False
        self.calls = []
        self.enterContext(patch.object(validation, 'command', side_effect=self.command))
        self.enterContext(patch.object(validation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))

    def command(self, argv, **options):
        self.calls.append(argv)
        if argv[:2] == ['docker', 'run']:
            # The durable plan must already exist before any simulated daemon effect.
            plan = json.loads((self.out / 'fixture-start-plan.json').read_text())
            self.name = argv[argv.index('--name') + 1]
            self.assertEqual(plan['name'], self.name)
            self.assertEqual(plan['status'], 'planned-not-proved-owned')
            self.assertEqual(options['timeout'], 900)
            self.assertEqual(plan['startup_seconds'], 900)
            cid = Path(argv[argv.index('--cidfile') + 1])
            self.assertEqual(cid, self.out / plan['cidfile'])
            if self.write_id:
                cid.write_text(self.identifier + '\n')
            if self.timeout:
                raise subprocess.TimeoutExpired('synthetic-start', 900, output=None)
            return self.identifier
        if argv[:2] == ['docker', 'port']:
            self.assertEqual(argv[2], self.identifier)
            return '127.0.0.1:23456'
        if argv[:2] == ['docker', 'inspect']:
            self.assertEqual(argv[-1], self.identifier)
            return f'{self.identifier} /{self.name if not self.foreign else "foreign"} isolated'
        if argv[:3] == ['docker', 'rm', '-f']:
            self.assertEqual(argv[3], self.identifier)
            return self.identifier
        raise AssertionError('Unexpected command')

    def result(self):
        return json.loads((self.out / 'fixture-start-result.json').read_text())

    def test_cold_start_has_explicit_ceiling_and_budget_and_known_identity(self):
        self.assertEqual(STARTUP_SECONDS, 900)
        self.assertEqual(budget(('backend',))['execution_seconds'], 2980)
        self.assertEqual(budget(('probes',))['startup_seconds'], 0)
        env = validation.clean_environment()
        identity = validation.start_fixture(env, self.out)
        self.assertEqual(identity, (self.identifier, self.name, 23456))
        self.assertEqual(self.result()['status'], 'ready')
        self.assertEqual(env['KAT_ISOLATED_TEST_CONTAINER'], self.name)
        self.assertFalse(any(call[:2] == ['docker', 'rm'] for call in self.calls))

    def test_timeout_without_stdout_or_cid_preserves_ambiguity_without_adoption(self):
        self.timeout, self.write_id = True, False
        with self.assertRaises(subprocess.TimeoutExpired):
            validation.start_fixture(validation.clean_environment(), self.out)
        self.assertEqual(self.result()['cleanup'], 'manual-inspection-required')
        self.assertEqual(self.result()['status'], 'stopped')
        self.assertEqual(len(self.calls), 1, 'No name-based lookup, replay or deletion')

    def test_timeout_without_stdout_can_remove_only_proved_cid_identity(self):
        self.timeout = True
        with self.assertRaises(subprocess.TimeoutExpired):
            validation.start_fixture(validation.clean_environment(), self.out)
        self.assertEqual(self.result()['cleanup'], 'owned-container-removed')
        self.assertEqual(self.result()['status'], 'stopped')
        self.assertEqual(self.calls[-1], ['docker', 'rm', '-f', self.identifier])
        self.assertEqual(sum(call[:2] == ['docker', 'run'] for call in self.calls), 1)

    def test_foreign_or_malformed_identity_never_authorizes_cleanup(self):
        for malformed in (False, True):
            with self.subTest(malformed=malformed), TemporaryDirectory() as directory:
                self.out = Path(directory)
                self.calls = []
                self.foreign, self.timeout = True, True
                self.identifier = 'invalid' if malformed else 'a' * 64
                with self.assertRaises(subprocess.TimeoutExpired):
                    validation.start_fixture(validation.clean_environment(), self.out)
                self.assertEqual(self.result()['cleanup'], 'manual-inspection-required')
                self.assertFalse(any(call[:2] == ['docker', 'rm'] for call in self.calls))

    def test_existing_id_or_plan_refuses_before_side_effect_and_preserves_evidence(self):
        cid = self.out / 'fixture.cid'
        cid.write_text(self.identifier)
        with self.assertRaisesRegex(RuntimeError, 'no replay'):
            validation.start_fixture(validation.clean_environment(), self.out)
        self.assertEqual(cid.read_text(), self.identifier)
        cid.unlink()
        (self.out / 'fixture-start-plan.json').write_text('preserved')
        with self.assertRaises(FileExistsError):
            validation.start_fixture(validation.clean_environment(), self.out)
        self.assertFalse(self.calls)
