"""Local unsigned evidence is never promoted into review or deployment authority."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import delivery_receipt as receipt


class DeliveryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.source = {'commit': 'a' * 40, 'tree': 'b' * 40, 'base': 'c' * 40,
                       'diff_sha256': 'd' * 64, 'changed': True}
        self.identity = self.enterContext(patch.object(receipt, 'source_identity', return_value=self.source))
        directory = self.root / '.local/kat-validation/123456789abcdef0'
        directory.mkdir(parents=True)
        self.log = directory / 'backend.log'; self.log.write_text('Ran 2 tests\nOK\n')
        self.path = self.root / 'focused.json'
        self.report = {'action': 'execute', 'status': 'ok', 'inventory_only': False,
            'git': {'sha': 'a' * 40, 'dirty': False}, 'tree': 'b' * 40,
            'fixture': 'owned-isolated-loopback', 'fixture_cleanup': 'owned-container-removed',
            'unrun': [], 'selected': ['backend'], 'filters': {'tests': ['synthetic.tests']},
            'logs_dir': str(directory.relative_to(self.root)), 'results': {'backend': {
                'status': 'passed', 'log': str(self.log.relative_to(self.root)),
                'diagnostics': {'tests_run': 2, 'failure_count': 0, 'status': 'passed'}}}}

    def prepare(self, report=None, **kwargs):
        self.path.write_text(json.dumps(self.report if report is None else report))
        return receipt.prepare(self.root, 'c' * 40, 'synthetic', [self.path], **kwargs)

    def test_exact_local_reports_bind_filters_and_logs_without_claiming_release(self):
        record = self.prepare()
        self.assertEqual(record['states']['focused-tested']['state'], 'local-reported-pass')
        for state in receipt.STATES:
            self.assertEqual(record['states'][state]['state'], 'held-unrun')
        self.assertEqual(len(list(receipt.evidence_refs(record))), 2)
        text = receipt.summary(record)
        self.assertIn('LOCAL-ONLY HOLD', text)
        self.assertIn('unsigned', text)
        self.log.write_text('altered after receipt')
        with self.assertRaisesRegex(ValueError, 'changed'):
            receipt.summary(record)

    def test_absent_failed_filtered_foreign_or_cleanup_incomplete_never_qualifies(self):
        blank = receipt.prepare(self.root, 'c' * 40, 'synthetic')
        self.assertEqual(blank['states']['focused-tested']['state'], 'unrun')
        for change in ({'status': 'stopped'}, {'fixture_cleanup': 'failed'},
                       {'unrun': ['backend']}, {'git': {'sha': 'e' * 40, 'dirty': False}},
                       {'tree': 'e' * 40}, {'git': {'sha': 'a' * 40, 'dirty': True}},
                       {'inventory_only': True}):
            record = self.prepare(self.report | change)
            with self.subTest(change=change):
                self.assertNotEqual(record['states']['focused-tested']['state'], 'local-reported-pass')
                self.assertEqual(record['states']['qualified']['state'], 'held-unrun')
        # A valid filtered focused pass stays focused, never full qualification.
        self.assertEqual(self.prepare()['states']['qualified']['state'], 'held-unrun')

    def test_arbitrary_json_success_and_old_native_results_are_only_references(self):
        fake = self.root / 'release-result.json'
        fake.write_text(json.dumps({'status': 'verified', 'artifact': {
            'commit': 'e' * 40, 'tree': 'f' * 40}}))
        record = self.prepare(external={'deployed': [fake], 'qualified': [fake]})
        self.assertEqual(record['states']['deployed']['state'], 'unverified-reference')
        self.assertEqual(record['states']['deployed']['evidence'][0]['source_binding'], 'foreign-or-incomplete')
        record['states']['deployed']['state'] = 'verified'
        with self.assertRaisesRegex(ValueError, 'Unsupported delivery assertion'):
            receipt.summary(record)
        report = self.prepare({'status': 'ok'})
        self.assertNotEqual(report['states']['focused-tested']['state'], 'local-reported-pass')

    def test_missing_evidence_and_outside_logs_fail_closed(self):
        self.log.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            self.prepare()
        report = deepcopy(self.report)
        report['results']['backend']['log'] = '/outside/secret'
        with self.assertRaisesRegex(ValueError, 'owned evidence'):
            self.prepare(report)

    def test_focused_local_policy_records_addition_without_scheduling_full_suites(self):
        with patch.object(receipt.subprocess, 'run', side_effect=AssertionError('pipeline invoked')):
            record = receipt.prepare(self.root, 'c' * 40, ['original', 'addition'],
                                     selection_notes=['Schema grammar and adjacent preservation checks'])
        self.assertEqual(record['requests'], ['original', 'addition'])
        self.assertEqual(record['validation_policy']['full_ci_native'], 'mandatory-when-delivery-authorized')
        self.assertEqual(record['validation_policy']['full_local'],
                         'optional-diagnosis-or-ci-reproduction-not-a-release-prerequisite')
        self.assertEqual(record['validation_policy']['selection_notes'],
                         ['Schema grammar and adjacent preservation checks'])
        self.assertEqual(record['states']['qualified']['state'], 'held-unrun')

    def test_collection_is_read_only_and_source_change_during_collection_refuses(self):
        self.path.write_text(json.dumps(self.report))
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        receipt.prepare(self.root, 'c' * 40, 'synthetic', [self.path])
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()})
        self.identity.side_effect = [self.source, self.source | {'tree': 'f' * 40}]
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            receipt.prepare(self.root, 'c' * 40, 'synthetic')
