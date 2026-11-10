"""Pure SQL/source preflight and real temporary-file enrollment; never server access."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deploy import prepare_migration as preparation, enroll_migration as enrollment


class MigrationPreparationTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.old, self.new = root / 'old', root / 'new'
        self.old.mkdir(); self.new.mkdir()
        for directory in (self.old, self.new):
            (directory / '001_initial.sql').write_text('CREATE TABLE retained (id text);')

    def test_exact_new_tables_and_nullable_columns_without_database_access(self):
        (self.new / '002_note.sql').write_text('CREATE TABLE note (id text PRIMARY KEY);')
        (self.new / '003_optional.sql').write_text('ALTER TABLE retained ADD COLUMN label text;')
        with patch('m2.release_schema.psycopg.connect', side_effect=AssertionError('DB touched')):
            result = preparation.prepare(self.old, self.new)
        self.assertEqual((result['from'], result['to'], result['enrollment']), (1, 3, 'required'))
        self.assertEqual(result['lane']['added_tables'], ['note'])
        self.assertEqual(result['lane']['added_columns'], {'retained': ['label']})
        self.assertEqual(result['lane_sha256'], sha256(preparation.lane_bytes(result['lane'])).hexdigest())
        supplied = preparation.prepare(self.old, self.new, {'transitions': [result['lane']]})
        self.assertEqual(supplied['enrollment'], 'present-in-supplied-policy-not-live-verified')

    def test_same_schema_needs_no_permit_and_changed_history_refuses(self):
        self.assertIsNone(preparation.prepare(self.old, self.new)['lane'])
        (self.new / '001_initial.sql').write_text('CREATE TABLE different (id text);')
        with self.assertRaisesRegex(ValueError, 'Retained'):
            preparation.prepare(self.old, self.new)

    def test_destructive_default_backfill_and_noncontiguous_sql_refuse(self):
        path = self.new / '002_new.sql'
        for statement in ('DROP TABLE retained;', 'ALTER TABLE retained ADD COLUMN note text DEFAULT \'x\';',
                          'CREATE TABLE note (id text); INSERT INTO note VALUES (\'x\');'):
            path.write_text(statement)
            with self.subTest(statement=statement), self.assertRaises(ValueError):
                preparation.prepare(self.old, self.new)
        path.rename(self.new / '003_new.sql')
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            preparation.prepare(self.old, self.new)


class MigrationEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.policy = self.root / 'ci-policy.json'
        self.before = {'enabled': True, 'signer_sha': 'a' * 40, 'transitions': [], 'target': 'retained'}
        self.policy.write_text(json.dumps(self.before))
        self.stage = self.root / 'stage'; self.stage.mkdir()
        (self.stage / 'release.lock').touch()
        self.lane = {'from': 1, 'to': 2, 'migrations': {'002_note.sql': 'b' * 64},
                     'added_tables': ['note'], 'added_columns': {}}
        self.body = preparation.lane_bytes(self.lane)
        self.expected = {'request': 'synthetic-only', 'hostname': 'synthetic.invalid',
                         'lane_sha256': sha256(self.body).hexdigest(),
                         'policy_sha256': sha256(self.policy.read_bytes()).hexdigest(),
                         'native_policy_sha256': 'c' * 64,
                         'helper_sha256': {name: 'd' * 64 for name in enrollment.HELPER_NAMES}}
        self.enterContext(patch.object(enrollment, 'POLICY', self.policy))
        self.enterContext(patch.object(enrollment.os, 'geteuid', return_value=0))
        self.enterContext(patch.object(enrollment.socket, 'gethostname', return_value='synthetic.invalid'))
        # Installed guards are explicit doubles; file durability and locking are real.
        self.ci = SimpleNamespace(protected=Path,
            read_policy=lambda path=None: json.loads((path or self.policy).read_text()))
        native = {'target': {'stage_root': str(self.stage), 'project': 'synthetic', 'db_image': 'synthetic'}}
        self.guards = self.enterContext(patch.object(enrollment, 'installed_guards',
            return_value=(self.ci, SimpleNamespace(validate_transition_lane=enrollment.validate_transition_lane), native)))
        self.schema = self.enterContext(patch.object(enrollment, 'running_schema', return_value=1))

    def invoke(self, execute=False):
        raw = json.dumps(self.expected).encode()
        return enrollment.enroll(self.body, raw, sha256(raw).hexdigest(), execute=execute)

    def test_default_is_completely_offline_and_tampered_lane_refuses(self):
        before = list(self.root.rglob('*'))
        self.assertEqual(self.invoke()['status'], 'offline-plan-not-installed')
        self.guards.assert_not_called(); self.schema.assert_not_called()
        self.assertEqual(before, list(self.root.rglob('*')))
        self.body += b' '
        with self.assertRaises(ValueError): self.invoke()
        self.guards.assert_not_called()

    def test_append_preserves_other_fields_retains_original_and_refuses_replay(self):
        original = self.policy.read_bytes()
        result = self.invoke(True)
        self.assertEqual(result['status'], 'enrolled-independent-readback-required')
        self.assertEqual(json.loads(self.policy.read_text()), self.before | {'transitions': [self.lane]})
        backup = self.root / 'migration-enrollment-synthetic-only'
        self.assertEqual((backup / 'policy.before.json').read_bytes(), original)
        self.assertTrue((backup / 'prepared.json').is_file())
        with self.assertRaises(ValueError): self.invoke(True)
        self.assertEqual(json.loads(self.policy.read_text())['signer_sha'], 'a' * 40)

    def test_active_attempt_policy_drift_schema_mismatch_and_busy_lock_refuse(self):
        active = self.stage / 'active-attempt'
        active.symlink_to(self.root / 'absent')
        with self.assertRaisesRegex(ValueError, 'owns'): self.invoke(True)
        active.unlink()
        self.schema.return_value = 2
        with self.assertRaisesRegex(ValueError, 'schema'): self.invoke(True)
        self.schema.return_value = 1
        import fcntl
        with (self.stage / 'release.lock').open('r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.invoke(True)
        self.policy.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'policy changed'): self.invoke(True)
        self.assertFalse((self.root / 'migration-enrollment-synthetic-only').exists())

    def test_installed_candidate_rejection_preserves_original_and_stops_replay(self):
        before = self.policy.read_bytes()
        def reject(path=None):
            if path is not None: raise ValueError('synthetic installed validator rejection')
            return json.loads(before)
        self.ci.read_policy = reject
        with self.assertRaises(ValueError): self.invoke(True)
        self.assertEqual(self.policy.read_bytes(), before)
        with self.assertRaises(FileExistsError): self.invoke(True)

    def test_ambiguous_final_receipt_keeps_installed_candidate_and_never_restores(self):
        original = enrollment.durable_bytes
        def interrupt(path, content, mode=0o600):
            if path.name == 'receipt.json': raise OSError('synthetic interruption')
            original(path, content, mode)
        with patch.object(enrollment, 'durable_bytes', side_effect=interrupt):
            with self.assertRaises(OSError): self.invoke(True)
        self.assertEqual(json.loads(self.policy.read_text())['transitions'], [self.lane])
        with self.assertRaises(ValueError): self.invoke(True)

    def test_wrong_host_and_changed_expectations_stop_before_installed_guards(self):
        with patch.object(enrollment.socket, 'gethostname', return_value='foreign.invalid'):
            with self.assertRaisesRegex(ValueError, 'exact host'): self.invoke(True)
        raw = json.dumps(self.expected).encode()
        with self.assertRaisesRegex(ValueError, 'expectations'):
            enrollment.enroll(self.body, raw, '0' * 64, execute=True)
        self.guards.assert_not_called()

    def test_state_change_at_second_schema_check_preserves_original(self):
        before = self.policy.read_bytes()
        self.schema.side_effect = [1, 2]
        with self.assertRaisesRegex(ValueError, 'changed before commit'): self.invoke(True)
        self.assertEqual(self.policy.read_bytes(), before)
        self.assertTrue((self.root / 'migration-enrollment-synthetic-only/policy.before.json').is_file())

    def test_duplicate_conflicting_or_full_allowlist_cannot_be_appended(self):
        for lanes in ([self.lane], [self.lane | {'to': 3}], [self.lane | {'from': 5}] * 8):
            with self.subTest(lanes=lanes), self.assertRaises(ValueError):
                enrollment.candidate_policy(json.dumps(self.before | {'transitions': lanes}).encode(), self.lane)
