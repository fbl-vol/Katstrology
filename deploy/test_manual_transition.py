"""Explicit human-signed transition admission; no CI identity or live credentials."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request

from deploy import release_access as access, release_ci_access as ci
from deploy import release_pipeline as pipeline, release_remote as remote
from deploy.test_release_access import fixture, signed_request
from deploy.test_release_promotion import OwnedRelease

LANE = {'from': 23, 'to': 24, 'migrations': {
    '024_account_tones.sql': '523775c5caa77b398d2f8804711f12029a7c810031f66ad4505003486feb8a71'},
    'added_tables': ['account_tones'], 'added_columns': {}}


def signed_transition_fixture(directory):
    base, policy = fixture(directory)
    policy.update(schema_version=23, manual_transitions=[LANE])
    manual = {'lane': LANE, 'old_image': 'sha256:' + 'e' * 64,
              'old_source_sha256': 'f' * 64, 'settled_existing_work': True}
    plan = pipeline.plan(base['artifact'], policy['target'], 24,
        Path(policy['compose_file']).read_bytes(), base['attempt'], 7, 7, manual_transition=manual)
    return plan, policy


class ManualAdmissionTests(unittest.TestCase):
    def test_real_signature_admits_once_and_freezes_policy_without_ci(self):
        with TemporaryDirectory() as directory:
            plan, policy = signed_transition_fixture(directory)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)):
                request = signed_request(plan, directory, 'stage')
                self.assertEqual(access.dispatch(request, policy, BytesIO())['status'], 'ok')
                self.assertNotIn('ci_admission', remote.REQUEST)
                self.assertNotIn('bootstrap_permit', remote.REQUEST)
                self.assertEqual(remote.REQUEST['manual_admission']['lane'], LANE)
                stage = Path(policy['target']['stage_root']) / plan['attempt']
                witness = json.loads((stage / 'manual-admission.json').read_text())
                self.assertEqual(witness['plan_sha256'], plan['plan_sha256'])
                with self.assertRaisesRegex(ValueError, 'Stage exists'):
                    access.dispatch(request, policy, BytesIO())
                changed_policy = policy | {'max_archive_bytes': policy['max_archive_bytes'] + 1}
                with self.assertRaisesRegex(ValueError, 'policy changed'):
                    access.dispatch(signed_request(plan, directory, 'upload', bytes=7), changed_policy, BytesIO(b'archive'))
                self.assertFalse((stage / 'image.tar').exists())
                self.assertTrue((stage.parent / 'active-attempt').exists())

    def test_unknown_lane_missing_settlement_and_unsigned_scope_changes_are_denied(self):
        with TemporaryDirectory() as directory:
            plan, policy = signed_transition_fixture(directory)
            request = signed_request(plan, directory, 'stage')
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)), \
                    patch.object(remote, 'main') as effects:
                for altered in (policy | {'manual_transitions': []}, policy | {'schema_version': 24},
                                policy | {'manual_transitions': [LANE | {'added_tables': ['wrong']}]}):
                    with self.subTest(policy=altered['schema_version']), self.assertRaises(ValueError):
                        access.dispatch(request, altered, BytesIO())
                changed = json.loads(json.dumps(plan))
                changed['manual_transition']['old_source_sha256'] = '0' * 64
                content = {key: value for key, value in changed.items() if key != 'plan_sha256'}
                changed['plan_sha256'] = sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                tampered = request | {'plan': changed, 'approval': request['approval'] | {'plan_sha256': changed['plan_sha256']}}
                with self.assertRaisesRegex(ValueError, 'signature differs'):
                    access.dispatch(tampered, policy, BytesIO())
                for bad in (plan['manual_transition'] | {'settled_existing_work': False},
                            plan['manual_transition'] | {'command': 'sql'}):
                    with self.assertRaises(ValueError):
                        access.validate_manual_transition(bad)
                for extra in ('ci_admission', 'manual_admission', 'bootstrap_permit'):
                    with self.assertRaises(ValueError):
                        access.dispatch(request | {extra: {}}, policy, BytesIO())
                effects.assert_not_called()

    def test_legacy_same_schema_is_unchanged_and_transition_cannot_enter_ci(self):
        with TemporaryDirectory() as directory:
            legacy, policy = fixture(directory)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)):
                self.assertEqual(access.dispatch(signed_request(legacy, directory, 'stage'), policy, BytesIO())['status'], 'ok')
                self.assertNotIn('manual_admission', remote.REQUEST)
                self.assertNotIn('manual_transition', legacy)
            with self.assertRaises(ValueError):
                ci.validate_manifest({'contract': 1, 'run_id': 1, 'run_attempt': 1,
                                      'plan': legacy | {'manual_transition': {}}})

    def test_public_verification_is_required_before_manual_completion(self):
        with TemporaryDirectory() as directory:
            plan, policy = signed_transition_fixture(directory)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)):
                access.dispatch(signed_request(plan, directory, 'stage'), policy, BytesIO())
                with patch.object(access, 'verify_manual_public', side_effect=ValueError('synthetic public failure')) as verify, \
                        patch.object(remote, 'main') as effects, self.assertRaises(ValueError):
                    access.dispatch(signed_request(plan, directory, 'complete'), policy, BytesIO())
                verify.assert_called_once()
                effects.assert_not_called()
                self.assertTrue((Path(policy['target']['stage_root']) / 'active-attempt').exists())


def migration_archive(last):
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for version in range(1, last + 1):
            path = next((pipeline.ROOT / 'm2/migrations').glob(f'{version:03d}_*.sql'))
            body = path.read_bytes()
            member = tarfile.TarInfo('m2/migrations/' + path.name)
            member.size = len(body)
            archive.addfile(member, BytesIO(body))
    return stream.getvalue()


class ManualRelease(OwnedRelease):
    def __init__(self, root):
        super().__init__(root)
        self.source.write_bytes(migration_archive(23))
        self.source_bytes = migration_archive(24)
        (self.stage / 'source.tar').write_bytes(self.source_bytes)
        self.plan['source_bytes'] = len(self.source_bytes)
        self.plan['artifact']['source_offer_sha256'] = sha256(self.source_bytes).hexdigest()
        self.plan['schema_version'] = 24
        self.manual = {'lane': LANE, 'old_image': self.old,
            'old_source_sha256': pipeline.digest(self.source), 'settled_existing_work': True,
            'plan_sha256': self.plan['plan_sha256']}
        self.events = []
        self.ambiguous = False
        self.fenced = False

    def phase(self, action):
        return super().phase(action, manual_admission=self.manual)

    def docker(self, *args, **kwargs):
        if 'python' in args and 'from m2.release_drain import Admission' in args[-2]:
            self.calls.append(args)
            self.assert_stopped()
            self.events.append('seed-fence')
            self.fenced = True
            return ''
        if 'm2.deployment_backup' in args:
            self.events.append('old-image-backup')
            assert kwargs['env']['KAT_APP_IMAGE'] == self.old
        if 'm2.release_schema' in args:
            self.calls.append(args)
            self.assert_stopped()
            assert self.fenced and json.loads(kwargs['input']) == LANE
            self.events.append('migrate')
            self.schema = '24'
            if self.ambiguous:
                raise subprocess.TimeoutExpired(args, 180)
            return json.dumps({'schema': 24, 'status': 'migrated'})
        return super().docker(*args, **kwargs)

    def assert_stopped(self):
        assert not self.running


class NativeEdgeFixtureTests(unittest.TestCase):
    def test_edge421_fixture_requires_actual_inner_app403_and_owned_destination(self):
        from deploy.smoke_manual_transition import LocalEdge
        edge = LocalEdge(54321, 'https://example.invalid')
        edge.opener = Mock()
        edge.opener.open.side_effect = HTTPError('synthetic', 403, 'denied', {}, BytesIO())
        request = Request('https://example.invalid/api/session', headers={'Host': 'wrong.invalid'})
        self.assertEqual(edge.open(request, 10).status, 421)
        forwarded = edge.opener.open.call_args.args[0]
        self.assertEqual(forwarded.full_url, 'http://127.0.0.1:54321/api/session')
        self.assertEqual(forwarded.get_header('Host'), 'wrong.invalid')
        accepted = BytesIO()
        accepted.status = 200
        edge.opener.open.side_effect = None
        edge.opener.open.return_value = accepted
        with self.assertRaisesRegex(AssertionError, 'did not deny'):
            edge.open(request, 10)
        with self.assertRaisesRegex(ValueError, 'external destination'):
            edge.open(Request('https://foreign.invalid/'), 10)


class ManualLifecycleTests(unittest.TestCase):
    def test_old_non_drain_owner_stops_then_fences_backs_up_and_migrates(self):
        with TemporaryDirectory() as directory:
            release = ManualRelease(Path(directory))
            with patch.object(remote, 'maintenance', side_effect=AssertionError('Old094 has no drain socket')):
                self.assertEqual(release.phase('preflight')['status'], 'ok')
                self.assertEqual(release.phase('quiesce_and_snapshot')['status'], 'ok')
            self.assertEqual(release.events, ['seed-fence', 'old-image-backup', 'migrate'])
            self.assertEqual(release.schema, '24')
            self.assertFalse(release.running)
            self.assertTrue((release.stage / 'state.migrated.json').exists())
            self.assertEqual(release.source.read_bytes(), migration_archive(23))

    def test_ambiguous_migration_never_restarts_old_app_or_restores_data(self):
        with TemporaryDirectory() as directory:
            release = ManualRelease(Path(directory))
            release.ambiguous = True
            release.phase('preflight')
            result = release.phase('quiesce_and_snapshot')
            self.assertEqual(result['status'], 'halted')
            self.assertEqual(result['phase'], 'migrating')
            self.assertEqual(release.schema, '24')  # Commit happened; acknowledgement lost.
            self.assertFalse(release.running)
            self.assertTrue((release.root / 'active-attempt').exists())
            self.assertFalse(any('up' in call or 'start' in call or 'restore' in call for call in release.calls))
            self.assertEqual(release.events.count('migrate'), 1)

    def test_wrong_old_image_source_or_sql_lane_refuses_before_stop(self):
        for changed in ('old_image', 'old_source_sha256', 'lane', 'schema'):
            with self.subTest(changed=changed), TemporaryDirectory() as directory:
                release = ManualRelease(Path(directory))
                if changed == 'lane':
                    release.manual['lane'] = LANE | {'migrations': {'024_account_tones.sql': '0' * 64}}
                elif changed == 'schema':
                    release.schema = '24'
                else:
                    release.manual[changed] = ('sha256:' if changed == 'old_image' else '') + '0' * 64
                with self.assertRaises(ValueError):
                    release.phase('preflight')
                self.assertTrue(release.running)
                self.assertFalse(any('load' in call or 'stop' in call for call in release.calls))


if __name__ == '__main__':
    unittest.main()
