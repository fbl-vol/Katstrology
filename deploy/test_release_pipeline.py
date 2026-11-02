"""Offline release control tests: never contact an SSH host or serving state."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import release_pipeline as pipeline
from deploy import release_remote

ROOT = Path(__file__).resolve().parents[1]


def synthetic_package(directory):
    root = Path(directory)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip()
    offer = root / 'source.tar'
    with offer.open('wb') as output:
        subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, stdout=output, check=True)
    config = json.dumps({'os': 'linux', 'architecture': 'amd64',
                         'config': {'Labels': {'org.opencontainers.image.revision': commit}}}).encode()
    config_hash = sha256(config).hexdigest()
    manifest = json.dumps({'config': {'digest': 'sha256:' + config_hash}}).encode()
    manifest_hash = sha256(manifest).hexdigest()
    index = json.dumps({'manifests': [{'digest': 'sha256:' + manifest_hash,
                                      'platform': {'os': 'linux', 'architecture': 'amd64'}}]}).encode()
    index_hash = sha256(index).hexdigest()
    archive = root / 'image.tar'
    with tarfile.open(archive, 'w') as tar:
        for name, content in [('blobs/sha256/' + config_hash, config),
                              ('blobs/sha256/' + manifest_hash, manifest),
                              ('blobs/sha256/' + index_hash, index),
                              ('index.json', json.dumps({'manifests': [{'digest': 'sha256:' + index_hash}]}).encode())]:
            item = tarfile.TarInfo(name)
            item.size = len(content)
            tar.addfile(item, BytesIO(content))
    receipt = {'commit': commit, 'tree': tree, 'architecture': 'linux/amd64',
               'image_id': 'sha256:' + index_hash, 'config_digest': 'sha256:' + config_hash,
               'image_archive_sha256': pipeline.digest(archive),
               'source_offer_sha256': pipeline.digest(offer),
               'image_archive': str(archive), 'source_offer': str(offer)}
    path = root / 'receipt.json'
    path.write_text(json.dumps(receipt))
    return path


def synthetic_target():
    return {'ssh_alias': 'synthetic-alias', 'project': 'kat-synthetic',
            'stage': '/srv/synthetic-release', 'password_file': '/srv/synthetic-secret',
            'ephemeris_dir': '/srv/synthetic-ephe', 'snapshot_dir': '/srv/synthetic-snapshot',
            'origin': 'https://example.invalid', 'loopback_port': 28765}


class ReleasePlanTests(unittest.TestCase):
    def test_immutable_existing_package_and_nonmutating_plan(self):
        with TemporaryDirectory() as directory:
            receipt, archive, compose, schema = pipeline.artifact(synthetic_package(directory))
            self.assertTrue(archive.is_file())
            self.assertEqual(schema, 22)
            target = Path(directory) / 'target.json'
            target.write_text(json.dumps(synthetic_target()))
            with patch('deploy.release_pipeline.remote') as remote:
                planned = pipeline.plan(receipt, pipeline.target_config(target), schema, compose)
            remote.assert_not_called()
            self.assertEqual(planned['artifact']['commit'], receipt['commit'])
            self.assertNotIn('/srv/', json.dumps(planned))
            self.assertNotIn('synthetic-secret', json.dumps(planned))

    def test_tampered_archive_is_rejected_before_transport(self):
        with TemporaryDirectory() as directory:
            path = synthetic_package(directory)
            receipt = json.loads(path.read_text())
            Path(receipt['image_archive']).write_bytes(b'corrupt archive')
            with patch('deploy.release_pipeline.remote') as remote:
                with self.assertRaisesRegex(ValueError, 'Artifact hash mismatch'):
                    pipeline.artifact(path)
                remote.assert_not_called()

    def test_target_changes_invalidate_exact_approval_and_no_side_effects(self):
        receipt = {key: 'a' * 64 for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256')}
        receipt.update(image_id='sha256:' + 'b' * 64, config_digest='sha256:' + 'c' * 64)
        target = synthetic_target()
        approved = pipeline.plan(receipt, target, 22, b'compose')
        target['password_file'] = '/srv/other-secret'
        changed = pipeline.plan(receipt, target, 22, b'compose')
        self.assertNotEqual(approved['plan_sha256'], changed['plan_sha256'])
        with TemporaryDirectory() as directory:
            result = Path(directory) / 'receipt.json'
            with patch('deploy.release_pipeline.remote') as remote:
                with self.assertRaisesRegex(ValueError, 'approval'):
                    pipeline.execute(receipt, Path('/nonexistent'), b'compose', target, changed,
                                     {'approved_action': 'release', 'plan_sha256': approved['plan_sha256']}, result)
            remote.assert_not_called()
            self.assertFalse(result.exists())

    def test_guard_prevents_ambiguous_replay_and_records_halt(self):
        receipt = {key: 'a' * 64 for key in ('commit', 'tree', 'image_archive_sha256', 'source_offer_sha256')}
        receipt.update(image_id='sha256:' + 'b' * 64, config_digest='sha256:' + 'c' * 64)
        target = synthetic_target()
        planned = pipeline.plan(receipt, target, 22, b'compose')
        approval = {'approved_action': 'release', 'plan_sha256': planned['plan_sha256']}
        with TemporaryDirectory() as directory:
            result = Path(directory) / 'receipt.json'
            with patch('deploy.release_pipeline.remote', side_effect=RuntimeError('synthetic failure')) as remote:
                with self.assertRaisesRegex(RuntimeError, 'halted'):
                    pipeline.execute(receipt, Path('/nonexistent'), b'compose', target, planned, approval, result)
                self.assertEqual(remote.call_count, 1)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    pipeline.execute(receipt, Path('/nonexistent'), b'compose', target, planned, approval, result)
                self.assertEqual(remote.call_count, 1)
            self.assertIn('started', result.read_text())

    def test_remote_stage_is_exclusive_before_any_docker_action(self):
        with TemporaryDirectory() as directory:
            stage = Path(directory) / 'new-stage'
            target = synthetic_target()
            target['stage'] = str(stage)
            planned = {'plan_sha256': 'a' * 64, 'artifact': {'config_digest': 'sha256:' + 'b' * 64}}
            request = {'action': 'stage', 'target': target, 'plan': planned}
            with patch.object(release_remote, 'REQUEST', request, create=True), \
                 patch.object(release_remote, 'run') as docker:
                release_remote.main()
                self.assertEqual(json.loads((stage / 'phase.json').read_text()),
                                 {'plan_sha256': planned['plan_sha256'], 'phase': 'staged'})
                with self.assertRaisesRegex(ValueError, 'no retry'):
                    release_remote.main()
                docker.assert_not_called()

    def test_invalid_target_never_calls_ssh(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'target.json'
            for field, value in [('ssh_alias', 'user@host'), ('stage', '/srv/../etc'),
                                 ('snapshot_dir', '/srv/synthetic-release')]:
                target = synthetic_target()
                target[field] = value
                path.write_text(json.dumps(target))
                with self.assertRaises(ValueError):
                    pipeline.target_config(path)


if __name__ == '__main__':
    unittest.main()
