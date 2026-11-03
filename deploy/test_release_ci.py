"""CI trust is tested separately from synthetic phase effects; no live identity claim."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import release_access as access, release_ci_access as ci, release_pipeline as pipeline
from deploy.test_release_access import fixture
from deploy.test_release_promotion import OwnedRelease
from deploy import release_remote as remote


def identity_fixture(manifest):
    source = manifest['plan']['artifact']['commit']
    policy = {'signer_workflow': '.github/workflows/trusted-release.yml', 'signer_sha': 'f' * 40,
              'caller_workflow': '.github/workflows/release.yml', 'max_age_seconds': 21600}
    cert = {'issuer': 'https://token.actions.githubusercontent.com',
            'sourceRepositoryURI': 'https://github.com/fbl-vol/Katstrology',
            'sourceRepositoryIdentifier': '1437147047', 'sourceRepositoryDigest': source,
            'sourceRepositoryRef': 'refs/heads/main', 'runnerEnvironment': 'github-hosted',
            'buildTrigger': 'push',
            'buildSignerURI': 'https://github.com/fbl-vol/Katstrology/.github/workflows/trusted-release.yml@' + 'f' * 40,
            'buildSignerDigest': 'f' * 40,
            'buildConfigURI': 'https://github.com/fbl-vol/Katstrology/.github/workflows/release.yml@refs/heads/main',
            'buildConfigDigest': source,
            'runInvocationURI': 'https://github.com/fbl-vol/Katstrology/actions/runs/123/attempts/1'}
    result = {'verificationResult': {'signature': {'certificate': cert},
              'statement': {'subject': [{'name': 'manifest.json', 'digest': {
                  'sha256': sha256(ci.canonical(manifest)).hexdigest()}}],
                  'predicate': {'tests_passed': True}},
              'verifiedTimestamps': [{'timestamp': datetime.fromtimestamp(1800000000, timezone.utc).isoformat()}]}}
    return policy, result


class CIAdmissionTests(unittest.TestCase):
    def test_verified_certificate_not_predicate_binds_every_identity_and_fresh_subject(self):
        manifest = {'contract': 1, 'plan': {'artifact': {'commit': 'a' * 40}},
                    'run_id': 123, 'run_attempt': 1}
        policy, result = identity_fixture(manifest)
        self.assertEqual(ci.verified_identity([result], manifest, policy, 1800000001)['sourceRepositoryIdentifier'],
                         '1437147047')
        for field in result['verificationResult']['signature']['certificate']:
            changed = deepcopy(result)
            changed['verificationResult']['signature']['certificate'][field] = 'foreign'
            # Even a perfectly matching user predicate cannot repair certificate identity.
            changed['verificationResult']['statement']['predicate'][field] = result['verificationResult']['signature']['certificate'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                ci.verified_identity([changed], manifest, policy, 1800000001)
        for now in (1799999999, 1800021601):
            with self.assertRaises(ValueError):
                ci.verified_identity([result], manifest, policy, now)
        changed = deepcopy(manifest)
        changed['plan']['attempt'] = 'different'
        with self.assertRaises(ValueError):
            ci.verified_identity([result], changed, policy, 1800000001)
        with self.assertRaises(ValueError):
            ci.validate_manifest(manifest | {'run_attempt': 2})

    def test_current_repo_main_and_completed_qualification_gate_before_admission(self):
        manifest = {'contract': 1, 'plan': {'artifact': {'commit': 'a' * 40}}, 'run_id': 123, 'run_attempt': 1}
        policy = {'caller_workflow': '.github/workflows/release.yml', 'qualification_job': 'release / qualify'}
        responses = [
            {'id': 1437147047, 'full_name': 'fbl-vol/Katstrology', 'default_branch': 'main', 'archived': False},
            {'protected': True, 'commit': {'sha': 'a' * 40}},
            {'repository': {'id': 1437147047}, 'head_sha': 'a' * 40, 'head_branch': 'main', 'event': 'push',
             'run_attempt': 1, 'path': '.github/workflows/release.yml', 'status': 'in_progress', 'run_number': 12},
            {'total_count': 1, 'jobs': [{'name': 'release / qualify', 'status': 'completed', 'conclusion': 'success'}]},
        ]
        with patch.object(ci, 'github', side_effect=responses):
            self.assertEqual(ci.eligible_run(manifest, policy, {})['run_number'], 12)
        for changed_index, key, value in ((0, 'id', 12), (1, 'protected', False),
                                          (1, 'commit', {'sha': 'b' * 40}),
                                          (2, 'event', 'pull_request'), (2, 'run_attempt', 2),
                                          (3, 'jobs', [{'name': 'release / qualify', 'status': 'completed', 'conclusion': 'skipped'}])):
            changed = deepcopy(responses)
            changed[changed_index][key] = value
            with patch.object(ci, 'github', side_effect=changed), self.assertRaises(ValueError):
                ci.eligible_run(manifest, policy, {})

    def test_out_of_order_run_cannot_claim_target_even_with_valid_provenance(self):
        with TemporaryDirectory() as directory:
            plan, manual = fixture(directory)
            manifest = {'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}
            root = Path(manual['target']['stage_root'])
            (root / 'ci-run-number').write_text('12\n')
            with patch.object(access, 'protected', side_effect=Path), \
                    patch.object(ci, 'verify', return_value={'run_number': 11}):
                with self.assertRaisesRegex(ValueError, 'out-of-order'):
                    ci.dispatch({'action': 'stage', 'manifest': manifest, 'bytes': 2},
                                {}, manual, access, BytesIO(b'{}'))
            self.assertFalse((root / 'active-attempt').exists())
            self.assertFalse((root / plan['attempt']).exists())
            self.assertEqual((root / 'ci-run-number').read_text(), '12\n')

    def test_admission_is_frozen_with_common_lock_and_no_network_after_stage(self):
        with TemporaryDirectory() as directory:
            plan, manual = fixture(directory)
            manifest = {'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}
            policy = {'synthetic': 'policy'}
            root = Path(manual['target']['stage_root'])
            stage = root / plan['attempt']
            witness = {'identity': {}, 'run_number': 10, 'admitted_at': 1800000000}
            request = {'action': 'stage', 'manifest': manifest, 'bytes': 2}
            with patch.object(access, 'protected', side_effect=Path), patch.object(ci, 'protected', side_effect=Path), \
                    patch.object(ci, 'verify', return_value=witness) as verify:
                ci.dispatch(request, policy, manual, access, BytesIO(b'{}'))
                self.assertEqual((root / 'active-attempt').read_text().strip(), plan['attempt'])
                self.assertTrue((stage / 'ci-admission.json').exists())
                ci.dispatch({'action': 'upload', 'manifest': manifest, 'bytes': 7},
                            policy, manual, access, BytesIO(b'archive'))
                self.assertEqual((stage / 'image.tar').read_bytes(), b'archive')
                self.assertEqual(verify.call_count, 1)
                with self.assertRaises(ValueError):
                    ci.dispatch(request, policy, manual, access, BytesIO(b'{}'))
                with self.assertRaises(ValueError):
                    ci.dispatch({'action': 'upload_source', 'manifest': manifest, 'bytes': 7},
                                {'synthetic': 'changed-policy'}, manual, access, BytesIO(b'source!'))
                self.assertFalse((stage / 'source.tar').exists())

    def test_bad_bundle_and_wrong_target_refuse_before_attempt_effects(self):
        with TemporaryDirectory() as directory:
            plan, manual = fixture(directory)
            manifest = {'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}
            root = Path(manual['target']['stage_root'])
            with patch.object(access, 'protected', side_effect=Path), \
                    patch.object(ci, 'verify', side_effect=ValueError('synthetic denial')):
                for body in (b'', b'{}x', b'{}'):
                    with self.assertRaises(ValueError):
                        ci.dispatch({'action': 'stage', 'manifest': manifest, 'bytes': 2},
                                    {}, manual, access, BytesIO(body))
                    self.assertFalse((root / 'active-attempt').exists())
                    self.assertFalse((root / plan['attempt']).exists())
                changed = deepcopy(manifest)
                changed['plan']['target']['target_sha256'] = '0' * 64
                with self.assertRaises(ValueError):
                    ci.dispatch({'action': 'stage', 'manifest': changed, 'bytes': 2},
                                {}, manual, access, BytesIO(b'{}'))

    def test_native_phase_drain_failure_never_stops_admitted_work_and_backup_uses_old_image(self):
        for drain_phase in ('fenced', 'drained'):
            with self.subTest(outcome=drain_phase), TemporaryDirectory() as directory:
                release = OwnedRelease(Path(directory))
                self.assertEqual(release.phase('preflight')['status'], 'ok')
                (release.stage / 'transition.json').write_text('null')
                state = {'phase': 'open', 'attempt': None, 'boot': 'b' * 32}
                backups = []

                def maintenance(container, action, attempt):
                    self.assertEqual(container, 'app-id')
                    if action == 'drain':
                        self.assertTrue(release.running)
                        state.update(phase=drain_phase, attempt=attempt)
                    elif action == 'resume':
                        self.assertTrue(release.running)
                        state.update(phase='open', attempt=None)
                    return dict(state)

                def docker(*args, **kwargs):
                    if 'm2.deployment_backup' in args:
                        backups.append(kwargs['env']['KAT_APP_IMAGE'])
                    return release.docker(*args, **kwargs)

                request = {'target': release.target, 'plan': release.plan,
                           'action': 'quiesce_and_snapshot', 'ci_admission': {'transitions': []}}
                with patch.object(remote, 'REQUEST', request, create=True), \
                        patch.object(remote, 'run', side_effect=docker), \
                        patch.object(remote, 'maintenance', side_effect=maintenance), \
                        patch.object(remote, 'protected_file', side_effect=Path), \
                        patch.object(remote, 'check_snapshot', return_value=Path(release.target['snapshot_dir'])):
                    result = remote.main()
                if drain_phase == 'fenced':
                    self.assertEqual(result['status'], 'halted')
                    self.assertEqual(result['serving'], 'unchanged; old app admission reopened before stop')
                    self.assertTrue(release.running)
                    self.assertFalse(backups)
                    self.assertFalse(any('stop' in call for call in release.calls))
                else:
                    self.assertEqual(result['status'], 'ok')
                    self.assertFalse(release.running)
                    self.assertEqual(backups, [release.old])

    def test_native_maintained_verifier_denies_unsigned_bundle_without_credentials(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text('{}\n')
            (root / 'bundle.json').write_text('{}\n')
            result = subprocess.run(['/usr/bin/gh', 'attestation', 'verify', str(root / 'manifest.json'),
                '--bundle', str(root / 'bundle.json'), '--repo', 'fbl-vol/Katstrology', '--format', 'json'],
                env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'GH_PROMPT_DISABLED': '1'},
                capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'"verificationResult"', result.stdout)
