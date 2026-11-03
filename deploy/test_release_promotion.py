"""Real owned files and native framing; Docker/HTTP remain offline synthetic doubles."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import release_access as access
from deploy import release_pipeline as pipeline
from deploy import release_remote as remote
from deploy.test_release_access import fixture, signed_request
from deploy.test_release_pipeline import effective_config, runtime_inspect, source_payload, synthetic_package, synthetic_target


class OwnedRelease:
    """Own real promotion/phase files; simulate only Docker's external effects."""
    old = 'sha256:' + 'd' * 64
    new = 'sha256:' + 'b' * 64

    def __init__(self, root):
        self.root = root
        self.stage = root / 'attempt'
        self.stage.mkdir()
        self.env = root / '.env'
        self.source = root / 'public-source.tar'
        self.original_env = ('# previous KAT_APP_IMAGE=' + self.old + '\nKAT_APP_IMAGE=' + self.old + '\nOTHER=untouched\n').encode()
        self.env.write_bytes(self.original_env)
        self.source.write_bytes(b'old source')
        self.source_bytes = source_payload()
        self.target = synthetic_target() | {'stage': str(self.stage), 'stage_root': str(root),
            'snapshot_dir': str(root / 'snapshots'), 'release_env_file': str(self.env),
            'source_offer_file': str(self.source)}
        self.plan = {'attempt': '1' * 32, 'plan_sha256': 'a' * 64, 'source_bytes': len(self.source_bytes),
            'schema_version': 23, 'compose_sha256': sha256(b'compose').hexdigest(),
            'artifact': {'config_digest': self.new, 'commit': 'c' * 40,
                'source_offer_sha256': sha256(self.source_bytes).hexdigest(),
                'image_archive_sha256': sha256(b'image').hexdigest()}}
        self.config = effective_config(self.target, self.new)
        self.image, self.running = self.old, True
        self.calls = []
        self.fail_activation = False
        self.schema = '23'
        (root / 'active-attempt').write_text(self.plan['attempt'] + '\n')
        (self.stage / 'compose.yaml').write_bytes(b'compose')
        (self.stage / 'runtime.yaml').write_text(remote.installed_db_override(self.target))
        (self.stage / 'image.tar').write_bytes(b'image')
        (self.stage / 'source.tar').write_bytes(self.source_bytes)
        (self.stage / 'phase.json').write_text(json.dumps({'plan_sha256': self.plan['plan_sha256'], 'phase': 'composed'}))

    def docker(self, *args, **kwargs):
        self.calls.append(args)
        if 'config' in args:
            return json.dumps(self.config)
        if 'ps' in args:
            return 'db-id' if args[-1] == 'db' else 'app-id' if self.running or '-aq' in args else ''
        if args[:3] == ('docker', 'inspect', 'app-id'):
            info = runtime_inspect(self.config, self.target)
            info.update(Image=self.image, State={'Running': self.running})
            return json.dumps([info])
        if args[:3] == ('docker', 'inspect', 'db-id'):
            return json.dumps([runtime_inspect(self.config, self.target, app=False)])
        if args[:3] == ('docker', 'image', 'inspect'):
            return json.dumps([{'Id': args[-1], 'Config': {'Labels': {'org.opencontainers.image.revision': 'c' * 40}}}])
        if args[:2] == ('docker', 'load'):
            return ''
        if 'psql' in args:
            return self.schema
        if 'stop' in args:
            self.running = False
            return ''
        if remote.STATE_FINGERPRINT in args:
            return json.dumps({'files_sha256': 'stable', 'host_sha256': 'stable', 'journal_sha256': 'stable'})
        if args[-1].startswith('from pathlib import Path') and 'Tombstones(journal)' in args[-1]:
            return ''
        if 'run' in args:
            assert not self.running
            folder = Path(self.target['snapshot_dir']) / ('snapshot-' + self.plan['plan_sha256'][:16])
            folder.mkdir(parents=True)
            (folder / 'manifest.json').write_text(json.dumps({'schema_version': 23, 'journal_prefix_sha256': 'f' * 64}))
            return ''
        if 'up' in args:
            self.running, self.image = True, self.new
            if self.fail_activation:
                raise subprocess.TimeoutExpired(args, 90)  # Docker may have activated before timeout.
            return ''
        raise AssertionError(args)

    def phase(self, action):
        with patch.object(remote, 'REQUEST', {'target': self.target, 'plan': self.plan, 'action': action}, create=True), \
             patch.object(remote, 'run', side_effect=self.docker), \
             patch.object(remote, 'protected_file', side_effect=lambda p: Path(p)), \
             patch.object(remote, 'check_snapshot', return_value=Path(self.target['snapshot_dir'])):
            return remote.main()

    def snapshot(self):
        assert self.phase('preflight')['status'] == 'ok'
        assert self.phase('quiesce_and_snapshot')['status'] == 'ok'


class PromotionTests(unittest.TestCase):
    def test_promotion_keeps_unrelated_env_and_originals_and_survives_invocation(self):
        with TemporaryDirectory() as directory:
            release = OwnedRelease(Path(directory))
            release.snapshot()
            self.assertFalse(release.running)
            self.assertEqual(release.phase('promote_release')['status'], 'ok')
            self.assertEqual(release.source.read_bytes(), release.source_bytes)
            self.assertEqual(release.env.read_bytes(), release.original_env.replace(
                ('\nKAT_APP_IMAGE=' + release.old).encode(), ('\nKAT_APP_IMAGE=' + release.new).encode(), 1))
            self.assertEqual((release.stage / 'source.before.tar').read_bytes(), b'old source')
            self.assertEqual((release.stage / 'env.before').read_bytes(), release.original_env)
            # New process reads the canonical file, not this process's environment.
            selected = subprocess.check_output(['python3', '-c',
                'from pathlib import Path; import sys; print(next(x.split("=",1)[1] for x in Path(sys.argv[1]).read_text().splitlines() if x.startswith("KAT_APP_IMAGE=")))',
                str(release.env)], text=True).strip()
            self.assertEqual(selected, release.new)
            self.assertEqual(release.phase('activate_app_only')['status'], 'ok')
            self.assertTrue(release.running)
            self.assertEqual(release.image, selected)

    def test_partial_second_file_failure_stops_owned_app_and_reports_mismatch(self):
        with TemporaryDirectory() as directory:
            release = OwnedRelease(Path(directory))
            release.snapshot()
            actual = remote.replace_file
            def replace(path, content, attempt):
                if Path(path) == release.env:
                    raise OSError('synthetic disk failure')
                actual(path, content, attempt)
            with patch.object(remote, 'replace_file', side_effect=replace):
                result = release.phase('promote_release')
            self.assertEqual(result['status'], 'halted')
            self.assertEqual(result['phase'], 'promoting')
            self.assertIn('stopped', result['serving'])
            self.assertFalse(release.running)
            self.assertEqual(release.env.read_bytes(), release.original_env)
            self.assertEqual(release.source.read_bytes(), release.source_bytes)
            self.assertEqual(result['files']['selected_image'], release.old)
            self.assertTrue((release.root / 'active-attempt').exists())
            self.assertTrue((release.stage / 'failure.json').is_file())
            self.assertFalse(any('up' in args for args in release.calls))

    def test_ambiguous_activation_quarantines_candidate_without_database_restore(self):
        with TemporaryDirectory() as directory:
            release = OwnedRelease(Path(directory))
            release.snapshot()
            release.phase('promote_release')
            release.fail_activation = True
            result = release.phase('activate_app_only')
            self.assertEqual(result['phase'], 'activating')
            self.assertIn('stopped', result['serving'])
            self.assertFalse(release.running)
            self.assertEqual(release.image, release.new)
            self.assertEqual(remote.selected_image(release.env.read_bytes()), release.new)
            self.assertFalse(any('restore' in args or 'start' in args for args in release.calls))
            self.assertTrue((Path(release.target['snapshot_dir']) / ('snapshot-' + 'a' * 16)).is_dir())

    def test_containment_does_not_stop_drifted_image_or_mounts(self):
        for drift in ('image', 'mount'):
            with self.subTest(drift=drift), TemporaryDirectory() as directory:
                release = OwnedRelease(Path(directory))
                release.snapshot()
                release.phase('promote_release')
                release.phase('activate_app_only')
                if drift == 'image':
                    release.image = 'sha256:' + 'f' * 64
                else:
                    real = release.docker
                    def docker(*args, **kwargs):
                        result = real(*args, **kwargs)
                        if args[:3] == ('docker', 'inspect', 'app-id'):
                            info = json.loads(result)
                            info[0]['Mounts'][0]['Source'] = '/unrelated'
                            return json.dumps(info)
                        return result
                    release.docker = docker
                before = len(release.calls)
                result = release.phase('quarantine')
                self.assertEqual(result['serving'], 'unknown; containment unconfirmed')
                self.assertTrue(release.running)
                self.assertFalse(any('stop' in args for args in release.calls[before:]))

    def test_drift_and_schema_transition_refuse_before_serving_mutation(self):
        for drift in ('schema', 'env', 'source'):
            with self.subTest(drift=drift), TemporaryDirectory() as directory:
                release = OwnedRelease(Path(directory))
                if drift == 'schema':
                    release.schema = '22'
                    with self.assertRaisesRegex(ValueError, 'cannot migrate'):
                        release.phase('preflight')
                else:
                    release.phase('preflight')
                    (release.env if drift == 'env' else release.source).write_bytes(b'changed')
                    result = release.phase('quiesce_and_snapshot')
                    self.assertEqual(result['status'], 'halted')
                self.assertTrue(release.running)
                self.assertFalse(any('stop' in args or 'up' in args for args in release.calls))

    def test_source_archive_rejects_signed_unsafe_members_and_corruption(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('device', tarfile.CHRTYPE)):
            with self.subTest(name=name), TemporaryDirectory() as directory:
                release = OwnedRelease(Path(directory))
                path = release.stage / 'source.tar'
                with tarfile.open(path, 'w') as archive:
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    archive.addfile(item)
                release.plan['source_bytes'] = path.stat().st_size
                release.plan['artifact']['source_offer_sha256'] = pipeline.digest(path)
                with self.assertRaisesRegex(ValueError, 'Unsafe source'):
                    release.phase('preflight')
                self.assertTrue(release.running)
                self.assertFalse(any('load' in args or 'stop' in args for args in release.calls))

    def test_old_protocol_and_changed_source_size_cannot_create_attempt(self):
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            with patch.object(access, 'protected', side_effect=lambda p: Path(p)):
                for changes in ({'contract': 3}, {'source_bytes': 8}, {'steps': plan['steps'][:-1]}):
                    changed = plan | changes
                    content = {key: value for key, value in changed.items() if key != 'plan_sha256'}
                    changed['plan_sha256'] = sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                    request = signed_request(changed, directory, 'stage') if 'source_bytes' not in changes else signed_request(plan, directory, 'stage') | {'plan': changed}
                    with self.assertRaises(ValueError):
                        access.dispatch(request, policy, BytesIO())
                    self.assertEqual(list(Path(policy['target']['stage_root']).iterdir()), [])

    def test_source_upload_rejects_truncation_trailing_tamper_and_symlinks(self):
        for body in (b'sour', b'source!extra', b'changed'):
            with self.subTest(body=body), TemporaryDirectory() as directory:
                plan, policy = fixture(directory)
                stage = Path(directory) / 'upload'
                stage.mkdir()
                (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'image_uploaded'}))
                with self.assertRaises(ValueError):
                    access.upload(stage, plan, 7, BytesIO(body), source=True)
                self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'image_uploaded')
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            stage = Path(directory) / 'upload'
            stage.mkdir()
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'image_uploaded'}))
            sentinel = Path(directory) / 'sentinel'
            sentinel.write_bytes(b'preserve')
            (stage / 'source.tar').symlink_to(sentinel)
            with self.assertRaises(FileExistsError):
                access.upload(stage, plan, 7, BytesIO(b'source!'), source=True)
            self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_corrupt_canonical_env_does_not_prevent_safe_candidate_containment(self):
        with TemporaryDirectory() as directory:
            release = OwnedRelease(Path(directory))
            release.snapshot()
            release.phase('promote_release')
            release.phase('activate_app_only')
            release.env.write_bytes(b'invalid selection')
            result = release.phase('quarantine')
            self.assertIn('stopped', result['serving'])
            self.assertFalse(release.running)
            self.assertEqual(result['files'], 'unavailable; inspect protected originals')

    def test_failed_preservation_comparison_quarantines_instead_of_completing(self):
        with TemporaryDirectory() as directory:
            release = OwnedRelease(Path(directory))
            release.snapshot()
            release.phase('promote_release')
            release.phase('activate_app_only')
            (release.stage / 'phase.json').write_text(json.dumps({'plan_sha256': release.plan['plan_sha256'], 'phase': 'local_verified'}))
            with patch.object(remote, 'preservation', return_value={'changed': True}):
                result = release.phase('complete')
            self.assertEqual(result['status'], 'halted')
            self.assertFalse(release.running)
            self.assertTrue((release.root / 'active-attempt').exists())
            self.assertEqual(json.loads((release.stage / 'phase.json').read_text())['phase'], 'local_verified')

    def test_fixed_state_and_authority_scripts_on_owned_synthetic_files(self):
        from m2.deletion import Tombstones
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'runtime'
            (root / 'files').mkdir(parents=True, mode=0o700)
            (root / 'siwc').mkdir(mode=0o700)
            (root / 'files/attachment').write_bytes(b'synthetic attachment')
            (root / 'siwc/host.json').write_text('{"synthetic":true}')
            journal = root / 'deletions/deletions.jsonl'
            Tombstones(journal).verify()
            code = remote.STATE_FINGERPRINT.replace('/var/lib/kat/browser-runtime', str(root))
            before = json.loads(subprocess.check_output(['python3', '-c', code], text=True))
            self.assertEqual(set(before), {'files_sha256', 'host_sha256', 'journal_sha256', 'tip_sha256'})
            self.assertNotIn('synthetic attachment', json.dumps(before))
            retained = Path(directory) / 'verification'
            retained.mkdir()
            code = remote.RETAIN_AUTHORITY.replace('/var/lib/kat/browser-runtime', str(root)).replace('/verification', str(retained)).replace('ATTEMPT', '1' * 32)
            subprocess.run(['python3', '-c', code], check=True, capture_output=True)
            destination = retained / ('authority-' + '1' * 32)
            self.assertEqual((destination / journal.name).read_bytes(), journal.read_bytes())
            self.assertEqual((destination / (journal.name + '.tip')).read_bytes(), journal.with_name(journal.name + '.tip').read_bytes())
            self.assertEqual((destination / journal.name).stat().st_mode & 0o777, 0o600)
            (root / 'files/attachment').write_bytes(b'changed')
            after = json.loads(subprocess.check_output(['python3', '-c', remote.STATE_FINGERPRINT.replace('/var/lib/kat/browser-runtime', str(root))], text=True))
            self.assertNotEqual(before['files_sha256'], after['files_sha256'])
            journal.unlink()
            result = subprocess.run(['python3', '-c', code], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(journal.exists(), 'A missing journal must never be initialized by retention')

    def test_preparation_creates_private_unsigned_plan_without_ssh(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = synthetic_package(directory)
            target = root / 'target.json'
            target.write_text(json.dumps(synthetic_target()))
            output = root / 'prepared'
            with patch.object(pipeline, 'remote') as transport:
                pipeline.main(['--artifact-receipt', str(package), '--target', str(target),
                    '--attempt', '1' * 32, '--prepare-dir', str(output)])
            transport.assert_not_called()
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / 'approval.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((output / 'plan.json').read_text())['contract'], 4)
            self.assertFalse((output / 'approval.json.sig').exists())


if __name__ == '__main__':
    unittest.main()
