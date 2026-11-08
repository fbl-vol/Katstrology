"""Offline joins use native-shaped inventories and a real synthetic OCI/source package."""
from copy import deepcopy
import json
import os
import glob
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import qualification_evidence as evidence, qualify, release_ci
from deploy.qualification_inventory import read_json
from tests.deploy.test_qualification_inventory import discovery
from tests.deploy.test_release_pipeline import synthetic_package
from tests.deploy.test_workflow_contract import workflow


class QualificationJoinTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.receipt_path = synthetic_package(self.root)
        self.receipt = read_json(self.receipt_path)
        self.identity = {key: self.receipt[key] for key in ('commit', 'tree')}
        self.identity.update(run_id='12345', run_attempt=1)
        self.full = discovery(1, 2, 3, 4)
        self.native = {'status': 'passed', 'cleanup': 'passed',
            **{key: self.receipt[key] for key in ('commit', 'image_id', 'config_digest')},
            'archive_image_id': self.receipt['image_id']}
        self.paths = []
        for lane, profiles in evidence.LANES.items():
            shard = lane[-1] + '/4' if lane.startswith('browser-') else None
            self.store(lane, self.synthetic(profiles, shard))
        self.store('native', self.native)

    def synthetic(self, profiles, shard=None):
        results = {}
        for profile in profiles:
            result = {'status': 'passed'}
            if profile in ('browser', 'siwc', 'clock'):
                selected = discovery(int(shard[0])) if shard else deepcopy(self.full)
                executed = deepcopy(selected)
                for test in executed['tests']:
                    test['outcomes'] = ['passed']
                result.update(inventory=selected, executed=executed)
            elif profile == 'backend':
                result['diagnostics'] = {'tests_run': 551, 'failure_count': 0, 'status': 'passed'}
            else:
                result['summary'] = ['Ran 17 tests']
            results[profile] = result
        return {'action': 'execute', 'status': 'ok', 'unrun': [], 'results': results,
            'git': {'sha': self.identity['commit'], 'dirty': False}, 'tree': self.identity['tree'],
            'selected': list(profiles), 'browser_shard': shard, 'inventory_only': False,
            'fixture': 'owned-isolated-loopback', 'fixture_cleanup': 'owned-container-removed',
            'filters': {'tests': [], 'browser_grep': None, 'private_layout_reference': False}}

    def store(self, lane, report):
        folder = self.root / 'lanes' / lane
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'report.json'
        path.write_text(json.dumps(report))
        record = folder / 'evidence.json'
        record.unlink(missing_ok=True)
        evidence.write_lane(folder, lane, self.identity, path,
                            receipt_path=self.receipt_path if lane == 'native' else None)
        if record not in self.paths:
            self.paths.append(record)

    def join(self, paths=None, **kwargs):
        return evidence.assemble(self.paths if paths is None else paths, self.identity, self.full,
                                 self.receipt_path, self.root / 'joined', **kwargs)

    def test_complete_join_preserves_bytes_and_existing_admission_contract(self):
        members = [self.receipt_path, Path(self.receipt['image_archive']), Path(self.receipt['source_offer'])]
        before = [evidence.digest(p) for p in members]
        witness = self.join()
        self.assertEqual(before, [evidence.digest(p) for p in members])
        self.assertEqual(set(witness), {'commit', 'tree', 'receipt_sha256', 'image_archive_sha256',
            'source_offer_sha256', 'synthetic_report_sha256', 'native_report_sha256'})
        manifest = release_ci.prepare(self.receipt_path, {'project': 'kat-synthetic',
            'origin': 'https://example.invalid', 'loopback_port': 28765, 'target_sha256': 'a' * 64}, 12345)
        self.assertEqual(manifest['plan']['artifact']['image_archive_sha256'], self.receipt['image_archive_sha256'])

    def test_workflow_native_upload_download_join_preserves_portable_package(self):
        package = self.root / '.local/fresh-production/package' / self.identity['commit'][:12]
        package.mkdir(parents=True)
        portable = dict(self.receipt)
        for key, filename in [('image_archive', 'kat-production-amd64.tar'), ('source_offer', 'kat-public-source.tar')]:
            shutil.copyfile(portable[key], package / filename)
            portable[key] = filename
        receipt = package / 'receipt.json'
        receipt.write_text(json.dumps(portable))
        self.receipt_path = receipt
        self.store('native', self.native)
        output = self.root / 'github-output'
        with patch.object(qualify, 'ROOT', self.root), patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}):
            qualify.emit_native_package(receipt, self.identity)
            with self.assertRaisesRegex(ValueError, 'differs from qualified source'):
                qualify.emit_native_package(receipt, self.identity | {'commit': 'a' * 40})
        self.assertEqual(output.read_text().splitlines(), [f'path={package.relative_to(self.root)}'])
        package_output = output.read_text().strip().removeprefix('path=')
        jobs = workflow('qualify.yml')['jobs']
        build = next(step for step in jobs['native']['steps'] if step.get('id') == 'package')
        self.assertEqual(build['run'], '.venv-swiss/bin/python -m deploy.qualify --lane native --execute')
        upload = next(step for step in jobs['native']['steps'] if step.get('id') == 'native')
        patterns = [line.replace('${{ steps.package.outputs.path }}', package_output)
                    for line in upload['with']['path'].splitlines()]
        # Pinned upload-artifact roots at the first wildcard, or the common
        # parent of explicit files. The ZIP then downloads relative to that root.
        search_roots = []
        members = []
        for pattern in patterns:
            parts = Path(pattern).parts
            wildcard = next((i for i, part in enumerate(parts) if glob.has_magic(part)), None)
            search_roots.append(self.root / (Path(*parts[:wildcard]) if wildcard is not None else Path(pattern).parent))
            members.extend(Path(path) for path in glob.glob(str(self.root / pattern)))
        upload_root = Path(os.path.commonpath(search_roots))
        transport = self.root / 'native.zip'
        with zipfile.ZipFile(transport, 'w') as archive:
            for member in members:
                archive.write(member, member.relative_to(upload_root))
        candidate = jobs['candidate']['steps']
        download = next(step for step in candidate if step.get('with', {}).get('name', '').startswith('native-'))
        destination = self.root / download['with']['path']
        with zipfile.ZipFile(transport) as archive:
            archive.extractall(destination)
        join = next(step['run'] for step in candidate if '--join' in step.get('run', ''))
        joined_receipt = self.root / join.split('--receipt ', 1)[1].split()[0]
        self.assertTrue(joined_receipt.is_file(), 'Native upload root must match the actual join receipt path')
        before = {member.name: evidence.digest(member) for member in members}
        witness = evidence.assemble(self.paths, self.identity, self.full, joined_receipt, self.root / 'joined')
        self.assertEqual(before, {name: evidence.digest(destination / name) for name in before})
        final = next(step for step in candidate if step.get('id') == 'upload')
        self.assertTrue(all((self.root / name).is_file() for name in final['with']['path'].splitlines()))
        self.assertEqual(len(witness), 7)

    def test_missing_duplicate_and_foreign_lane_or_attempt_fail_closed(self):
        with self.assertRaises(ValueError):
            self.join(self.paths[:-1])
        with self.assertRaises(ValueError):
            self.join(self.paths + self.paths[:1])
        path = self.paths[0]
        original = read_json(path)
        for key, wrong in [('commit', 'a' * 40), ('tree', 'b' * 40), ('run_id', '999'), ('run_attempt', 2)]:
            changed = deepcopy(original)
            changed['identity'][key] = wrong
            path.write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.join()
        path.write_text(json.dumps(original))
        self.assertFalse(self.receipt_path.with_name('qualification.json').exists())

    def test_reports_must_match_their_bound_digest(self):
        self.paths[0].with_name('report.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Altered'):
            self.join()

    def test_failure_cleanup_filter_or_partial_selection_cannot_qualify(self):
        good = self.synthetic(('browser',), '1/4')
        cases = [('status', 'stopped'), ('fixture_cleanup', 'failed'), ('unrun', ['browser']),
                 ('selected', []), ('browser_shard', '2/4'), ('inventory_only', True),
                 ('filters', {'tests': [], 'browser_grep': 'partial', 'private_layout_reference': False}),
                 ('git', {'sha': self.identity['commit'], 'dirty': True})]
        for key, wrong in cases:
            report = deepcopy(good)
            report[key] = wrong
            self.store('browser-1', report)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.join()
        self.assertFalse(self.receipt_path.with_name('qualification.json').exists())

    def test_green_counts_cannot_replace_exact_inventory_or_execution(self):
        for outcome in ([], ['skipped'], ['interrupted'], ['failed', 'passed']):
            report = self.synthetic(('browser',), '1/4')
            report['results']['browser']['executed']['tests'][0]['outcomes'] = outcome
            self.store('browser-1', report)
            with self.subTest(outcome=outcome), self.assertRaises(ValueError):
                self.join()
        report = self.synthetic(('browser',), '1/4')
        for key in ('inventory', 'executed'):
            report['results']['browser'][key]['tests'][0]['id'] = '2' * 64
        self.store('browser-1', report)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.join()

    def test_changed_receipt_archive_and_native_identity_are_rejected(self):
        original = self.receipt_path.read_bytes()
        self.receipt_path.write_bytes(original + b' ')
        with self.assertRaises(ValueError):
            self.join()
        self.receipt_path.write_bytes(original)
        report = self.native | {'cleanup': 'failed'}
        self.store('native', report)
        with self.assertRaises(ValueError):
            self.join()
        self.store('native', self.native)
        Path(self.receipt['image_archive']).write_bytes(b'altered archive')
        with self.assertRaises(ValueError):
            self.join()

    def test_hosted_identity_refuses_replays_and_foreign_checkout_before_lanes(self):
        environment = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
            'GITHUB_SHA': self.identity['commit'], 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1'}
        for change in ({}, {'GITHUB_RUN_ATTEMPT': '2'}, {'GITHUB_SHA': 'a' * 40},
                       {'GITHUB_RUN_ID': ''}, {'RUNNER_ENVIRONMENT': 'self-hosted'}):
            with self.subTest(change=change), patch.dict(os.environ, environment | change, clear=True), \
                    patch.object(qualify.subprocess, 'check_output', side_effect=[
                        '', self.identity['commit'], self.identity['tree']]):
                if change:
                    with self.assertRaises(ValueError):
                        qualify.identity()
                else:
                    self.assertEqual(qualify.identity(), self.identity)

    def test_sequential_local_shape_uses_same_assembler(self):
        self.store('all', self.synthetic(evidence.PROFILES))
        paths = [p for p in self.paths if p.parent.name in ('all', 'native')]
        witness = self.join(paths, sequential=True)
        self.assertEqual(witness['commit'], self.identity['commit'])
        self.assertEqual(set(read_json(self.root / 'joined/synthetic.json')['results']), set(evidence.PROFILES))

    def test_sequential_entrypoint_and_native_lane_build_only_once(self):
        self.store('all', self.synthetic(evidence.PROFILES))
        native_path = next(p for p in self.paths if p.parent.name == 'native')
        all_path = next(p for p in self.paths if p.parent.name == 'all')
        with patch.object(qualify, 'identity', return_value=self.identity), \
                patch.object(qualify, 'run_lane', side_effect=[(all_path, self.receipt_path), (native_path, self.receipt_path)]) as lanes, \
                patch.object(qualify, 'ROOT', self.root):
            qualify.qualify()
        self.assertEqual([call.args[0] for call in lanes.call_args_list], ['all', 'native'])
        def fake_native(*args, **kwargs):
            if args[1:] == ('deploy/build_local.py',):
                target = self.root / '.local/fresh-production/package' / self.identity['commit'][:12] / 'receipt.json'
                target.parent.mkdir(parents=True)
                target.write_bytes(self.receipt_path.read_bytes())
            if 'output' in kwargs:
                kwargs['output'].write(json.dumps(self.native))
        with patch.object(qualify, 'ROOT', self.root), patch.object(qualify, 'run', side_effect=fake_native) as run:
            qualify.run_lane('native', self.identity)
        self.assertEqual(sum(call.args[1:] == ('deploy/build_local.py',) for call in run.call_args_list), 1)
        self.assertFalse(any('docker' in str(call) or 'save' in str(call) for call in run.call_args_list))
