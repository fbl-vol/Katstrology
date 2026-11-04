"""Source/bootstrap boundaries only: no real policy, keys, SSH, identity or host."""

from hashlib import sha256
from io import BytesIO
import json
import os
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from deploy import bootstrap_bridge as bridge, ci_transport, hosted_tools, prepare_enrollment
from deploy import release_access as access, release_ci_access as ci, release_pipeline as pipeline
from deploy import release_remote as remote
from deploy.test_release_access import fixture
from deploy.test_manual_transition import LANE, migration_archive


def retained24(root, original):
    offer = root / 'running-source.tar'
    offer.write_bytes(migration_archive(24))
    with tarfile.open(offer, 'a') as archive:
        for name in ('release_access.py', 'release_remote.py', 'release_pipeline.py'):
            archive.add(pipeline.ROOT / 'deploy' / name, arcname='deploy/' + name)
    return original['artifact'] | {'source_offer': str(offer)}


class AdoptionTests(unittest.TestCase):
    def test_no_local_execution_or_transport_bootstrap(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(ci_transport, 'execute') as execute:
            with self.assertRaisesRegex(ValueError, 'not enrolled'):
                ci_transport.main()
            execute.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'ephemeral'):
                hosted_tools.install()
        for uid, original in ((1000, ''), (0, 'kat-release-ci-v1')):
            with patch.object(os, 'geteuid', return_value=uid), \
                    patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': original}), \
                    patch.object(ci, 'shared_access') as shared:
                with self.assertRaisesRegex(ValueError, 'local-root'):
                    bridge.execute(Path('/not-read'))
                shared.assert_not_called()
        for action in ('bootstrap', 'stage'):
            with self.assertRaisesRegex(ValueError, 'Unsupported CI request'):
                ci.dispatch({'action': action, 'bootstrap_permit': {}}, {}, {}, None, BytesIO())

    def test_automatic_transport_cannot_continue_bootstrap_witness(self):
        with TemporaryDirectory() as directory:
            plan, manual = fixture(directory)
            manifest = {'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}
            stage = Path(manual['target']['stage_root']) / plan['attempt']
            stage.mkdir()
            (stage / 'ci-admission.json').write_text(json.dumps({
                'mode': 'bootstrap', 'manifest_sha256': sha256(ci.canonical(manifest)).hexdigest(),
                'policy_sha256': sha256(ci.canonical({})).hexdigest()}))
            with patch.object(access, 'protected', side_effect=Path), \
                    patch.object(ci, 'protected', side_effect=Path), \
                    patch.object(access, 'dispatch_locked') as dispatch:
                with self.assertRaisesRegex(ValueError, 'witness differs'):
                    ci.dispatch({'action': 'compose', 'manifest': manifest}, {}, manual, access, BytesIO())
                dispatch.assert_not_called()

    def test_enrollment_plan_is_disabled_exact_and_omits_private_target_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original, manual = fixture(directory)
            manual.update(schema_version=24, manual_transitions=[])
            running = retained24(root, original)
            manual_path = root / 'manual.json'
            manual_path.write_text(json.dumps(manual))
            verifier, trusted_root = root / 'gh', root / 'trusted-root.jsonl'
            verifier.write_bytes(b'synthetic-public-verifier')
            trusted_root.write_bytes(b'synthetic-public-root')
            workflow = (pipeline.ROOT / '.github/workflows/trusted-release.yml').read_bytes()
            results = [b'', 'a' * 40, 'b' * 40, workflow, 'gh version 2.97.0 (synthetic)\n']
            with patch.object(prepare_enrollment.subprocess, 'check_output', side_effect=results), \
                    patch.object(prepare_enrollment, 'artifact', return_value=(
                        running, None, (pipeline.ROOT / 'deploy/compose.yaml').read_bytes(), 24)):
                plan = prepare_enrollment.prepare(manual_path, 'c' * 40, verifier, trusted_root,
                    root / 'output', running_receipt=root / 'retained24.json')
            policy = json.loads((root / 'output/ci-policy.json').read_text())
            scope = json.loads((root / 'output/target-scope.json').read_text())
            self.assertIs(policy['enabled'], False)
            self.assertEqual(policy['transitions'], [])
            self.assertEqual(policy['qualification_job'], 'release / qualify / candidate')
            self.assertEqual(scope, original['target'])
            self.assertEqual(plan['commit'], 'a' * 40)
            self.assertNotIn('bootstrap_bridge.py', plan['helper_sha256'])
            self.assertIsNone(plan['bootstrap'])
            self.assertEqual(plan['mode'], 'existing-drain-runtime')
            self.assertEqual(plan['baseline_schema'], 24)
            self.assertEqual(plan['manual_policy_sha256'], sha256(ci.canonical(manual)).hexdigest())
            self.assertEqual(plan['manual_policy_file_sha256'], sha256(manual_path.read_bytes()).hexdigest())
            self.assertEqual(json.loads(manual_path.read_text()), manual)
            self.assertEqual(plan['manual_schema_baseline'], 24)
            self.assertNotIn('baseline_schema', policy)  # No new gateway override contract.
            policy_path = root / 'output/ci-policy.json'
            installed = {policy['verifier']: verifier, policy['trusted_root']: trusted_root}
            with patch.object(ci, 'protected', side_effect=lambda path: installed.get(str(path), Path(path))):
                self.assertEqual(ci.read_policy(policy_path, enrollment=True), policy)
                with self.assertRaisesRegex(ValueError, 'disabled'):
                    ci.read_policy(policy_path)
            output = ''.join(p.read_text() for p in (root / 'output').iterdir())
            self.assertNotIn(manual['target']['password_file'], output)
            self.assertNotIn(manual['target']['stage_root'], output)

    def test_existing24_preparation_refuses_old_runtime_and_stale_manual_baseline(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original, manual = fixture(directory)
            manual_path = root / 'manual.json'
            running = retained24(root, original)
            workflow = (pipeline.ROOT / '.github/workflows/trusted-release.yml').read_bytes()
            for baseline, schema, lanes in ((24, 23, []), (23, 24, [LANE]), (24, 24, [LANE])):
                manual.update(schema_version=baseline, manual_transitions=lanes)
                manual_path.write_text(json.dumps(manual))
                with self.subTest(baseline=baseline, schema=schema, lanes=bool(lanes)), \
                        patch.object(prepare_enrollment.subprocess, 'check_output',
                                     side_effect=[b'', 'a' * 40, 'b' * 40, workflow]), \
                        patch.object(prepare_enrollment, 'artifact', return_value=(
                            running, None, (pipeline.ROOT / 'deploy/compose.yaml').read_bytes(), schema)), \
                        self.assertRaises(ValueError):
                    prepare_enrollment.prepare(manual_path, 'c' * 40, root / 'unread-verifier',
                        root / 'unread-root', root / 'output', running_receipt=root / 'retained.json')
                self.assertFalse((root / 'output').exists())

    def test_existing_gateway_admits_finalized24_without_bootstrap_or_new_lane(self):
        # Native identity verification is substituted only in this owned unit
        # fixture. This is admission-order/preservation evidence, not provenance.
        with TemporaryDirectory() as directory:
            original, manual = fixture(directory)
            manual.update(schema_version=24, manual_transitions=[])
            policy = {'transitions': []}
            bundle = b'synthetic-verifier-input'
            stage = Path(manual['target']['stage_root']) / original['attempt']
            def request(schema):
                plan = pipeline.plan(original['artifact'], manual['target'], schema,
                    Path(manual['compose_file']).read_bytes(), original['attempt'], 7, 7)
                return {'action': 'stage', 'bytes': len(bundle), 'manifest': {
                    'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}}
            with patch.object(access, 'protected', side_effect=Path), \
                    patch.object(ci, 'protected', side_effect=Path), \
                    patch.object(ci, 'verify', return_value={'run_number': 12}) as verify:
                for schema in (23, 25):
                    with self.assertRaisesRegex(ValueError, 'no installed compatibility lane'):
                        ci.dispatch(request(schema), policy, manual, access, BytesIO(bundle))
                verify.assert_not_called()
                self.assertFalse(stage.exists())
                allowed = request(24)
                self.assertEqual(ci.dispatch(allowed, policy, manual, access, BytesIO(bundle))['status'], 'ok')
                witness = json.loads((stage / 'ci-admission.json').read_text())
                self.assertNotIn('mode', witness)
                self.assertFalse((stage / 'manual-admission.json').exists())
                self.assertEqual(verify.call_count, 1)

    def test_one_time_permit_is_consumed_before_effects_and_never_replayed(self):
        for fail_phase in (None, 'promote_release'):
            with self.subTest(fail_phase=fail_phase), TemporaryDirectory() as directory:
                original, manual = fixture(directory)
                manual['schema_version'] = 23
                plan = pipeline.plan(original['artifact'], manual['target'], 23,
                                     Path(manual['compose_file']).read_bytes(), '1' * 32, 7, 7)
                package = Path(directory) / 'package'
                package.mkdir()
                manifest = {'contract': 1, 'plan': plan, 'run_id': 123, 'run_attempt': 1}
                (package / 'manifest.json').write_bytes(ci.canonical(manifest))
                (package / 'bundle.json').write_bytes(b'synthetic-native-verifier-result')
                (package / 'kat-production-amd64.tar').write_bytes(b'archive')
                (package / 'kat-public-source.tar').write_bytes(b'source!')
                permit = Path(directory) / 'bootstrap.json'
                permit.write_text(json.dumps({'plan_sha256': plan['plan_sha256'],
                    'old_image': 'sha256:' + 'c' * 64, 'old_source_sha256': 'd' * 64,
                    'settled_existing_work': True}))
                stage = Path(manual['target']['stage_root']) / plan['attempt']
                calls = []
                phase = SimpleNamespace(durable_text=remote.durable_text, sync_directory=remote.sync_directory,
                                        quarantine=Mock())
                def dispatch(request, policy, stream, action, selected, **authority):
                    self.assertFalse(permit.exists())
                    self.assertTrue(permit.with_name('bootstrap.used.json').exists())
                    self.assertEqual(authority['bootstrap_permit']['plan_sha256'], plan['plan_sha256'])
                    self.assertEqual(authority['ci_admission']['mode'], 'bootstrap')
                    calls.append(action)
                    if action == fail_phase:
                        raise ValueError('Synthetic phase failure')
                    if action == 'stage':
                        stage.mkdir()
                    if action in ('upload', 'upload_source'):
                        self.assertEqual(len(stream.read()), 7)
                    return {'status': 'ok', 'assets': {}}
                adapter = SimpleNamespace(read_policy=lambda: manual, validate_plan=access.validate_plan,
                                          phase_module=lambda: phase, dispatch_locked=dispatch)
                spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
                public = Mock()
                with patch.object(os, 'geteuid', return_value=0), \
                        patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': ''}), \
                        patch.object(ci, 'protected', side_effect=Path), \
                        patch.object(access, 'protected', side_effect=Path), \
                        patch.object(ci, 'shared_access', return_value=adapter), \
                        patch.object(ci, 'read_policy', return_value={'enabled': False}), \
                        patch.object(ci, 'verify', return_value={'run_number': 12}) as verifier, \
                        patch.object(ci, 'spec_from_file_location', return_value=spec), \
                        patch.object(ci, 'module_from_spec', return_value=SimpleNamespace(verify_public=public)):
                    if fail_phase:
                        with self.assertRaisesRegex(ValueError, 'Synthetic phase failure'):
                            bridge.execute(package, permit_path=permit)
                        phase.quarantine.assert_called_once()
                        public.assert_not_called()
                        self.assertNotIn('complete', calls)
                    else:
                        result = bridge.execute(package, permit_path=permit)
                        self.assertIn('not unattended release proof', result['status'])
                        self.assertEqual(calls[-2:], ['verify_serving_path', 'complete'])
                        public.assert_called_once()
                    verifier.assert_called_once()
                    count = len(calls)
                    with self.assertRaises(FileNotFoundError):
                        bridge.execute(package, permit_path=permit)
                    self.assertEqual(len(calls), count)
                self.assertEqual((stage.parent / 'ci-run-number').read_text(), '12\n')


if __name__ == '__main__':
    unittest.main()
