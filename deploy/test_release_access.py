"""Forced-command boundary: all fixtures are synthetic, no server/SSH contact."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from deploy import release_access as access
from deploy import release_pipeline as pipeline
from deploy import release_remote
from deploy.test_release_pipeline import synthetic_target


def fixture(directory):
    target = synthetic_target() | {'stage': str(Path(directory) / 'stage')}
    compose = Path(directory) / 'compose.yaml'
    compose.write_text('synthetic protected compose')
    receipt = {'commit': 'a' * 40, 'tree': 'b' * 40,
               'image_id': 'sha256:' + 'c' * 64, 'config_digest': 'sha256:' + 'd' * 64,
               'image_archive_sha256': sha256(b'archive').hexdigest(),
               'source_offer_sha256': 'f' * 64}
    plan = pipeline.plan(receipt, target, 22, compose.read_bytes())
    policy = {'target': target, 'approved_plan_sha256': plan['plan_sha256'],
              'compose_file': str(compose), 'schema_version': 22, 'max_archive_bytes': 1024}
    return plan, policy


class AppScopedAccessTests(unittest.TestCase):
    def test_documented_isolated_script_enters_command_guard_without_import_escape(self):
        script = Path(access.__file__)
        result = subprocess.run(['/usr/bin/python3', '-I', str(script)], input=b'',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/',
            env={'PATH': '/usr/bin:/bin', 'SSH_ORIGINAL_COMMAND': 'python3 -',
                 'PYTHONPATH': '/nonexistent/client-injected'}, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'Restricted release refused', result.stderr)
        self.assertNotIn(b'ModuleNotFoundError', result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)
        with patch.object(access, 'release_remote', None), \
             patch.object(access, 'protected', side_effect=lambda path: Path(path)):
            phase = access.phase_module()
        self.assertEqual(Path(phase.__file__), script.with_name('release_remote.py'))
        self.assertTrue(callable(phase.main))

    def test_isolated_adjacent_loader_rejects_symlink_module(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'release_access.py'
            (Path(directory) / 'release_remote.py').symlink_to('/etc/passwd')
            with patch.object(access, '__file__', str(source)), patch.object(access, 'release_remote', None):
                with self.assertRaisesRegex(ValueError, 'root protected'):
                    access.phase_module()

    def test_only_forced_protocol_command_is_accepted(self):
        for command in ('', 'python3 -', 'sh', 'scp -t /tmp/archive', 'sftp',
                        'kat-release-v1 ; id', 'kat-release-v1 --pty'):
            with self.subTest(command=command), patch.object(access, 'read_policy') as policy:
                with self.assertRaisesRegex(ValueError, 'Unsupported SSH command'):
                    access.main(input_stream=BytesIO(b''), original_command=command)
                policy.assert_not_called()

    def test_policy_approval_template_and_request_allow_only_fixed_effects(self):
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)), \
                 patch.object(release_remote, 'main', return_value={'phase': 'stage', 'status': 'ok'}) as phase:
                result = access.dispatch({'action': 'stage', 'plan': plan}, policy, BytesIO())
                self.assertEqual(result, {'phase': 'stage', 'status': 'ok'})
                self.assertEqual(release_remote.REQUEST['target'], policy['target'])
                phase.assert_called_once_with()
                for bad in (
                    {'action': 'stage', 'plan': plan, 'command': 'docker ps'},
                    {'action': 'stage', 'plan': plan, 'target': {'stage': '/etc'}},
                    {'action': 'stage', 'plan': plan, 'compose': 'services: {evil: {privileged: true}}'},
                    {'action': 'stage', 'plan': plan, 'mounts': ['/var/run/docker.sock:/docker.sock']},
                    {'action': 'upload', 'plan': plan, 'bytes': 1025},
                    {'action': 'upload', 'plan': plan, 'bytes': -1},
                    {'action': 'exec', 'plan': plan},
                ):
                    with self.subTest(bad=list(bad)):
                        with self.assertRaises(ValueError):
                            access.dispatch(bad, policy, BytesIO())
                phase.assert_called_once()
                changed = json.loads(json.dumps(plan))
                changed['target']['target_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Protected approval'):
                    access.dispatch({'action': 'stage', 'plan': changed}, policy, BytesIO())
                changed = json.loads(json.dumps(plan))
                changed['artifact']['config_digest'] = 'sha256:' + 'e' * 64
                with self.assertRaisesRegex(ValueError, 'Protected approval'):
                    access.dispatch({'action': 'stage', 'plan': changed}, policy, BytesIO())
                policy['approved_plan_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Protected approval'):
                    access.dispatch({'action': 'stage', 'plan': plan}, policy, BytesIO())

    def test_upload_is_exclusive_bounded_hash_checked_and_never_a_path(self):
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            stage = Path(policy['target']['stage'])
            stage.mkdir()
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'staged'}))
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)), \
                 patch.object(release_remote, 'main') as phase:
                request = {'action': 'upload', 'plan': plan, 'bytes': 7}
                self.assertEqual(access.dispatch(request, policy, BytesIO(b'archive'))['status'], 'ok')
                self.assertEqual((stage / 'image.tar').read_bytes(), b'archive')
                with self.assertRaises(FileExistsError):
                    access.dispatch(request, policy, BytesIO(b'archive'))
                phase.assert_not_called()
            for body in (b'arch', b'archivexx'):
                stage2 = Path(directory) / ('failed-' + str(len(body)))
                stage2.mkdir()
                (stage2 / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'staged'}))
                with self.assertRaises(ValueError):
                    access.upload(stage2, plan, 7, BytesIO(body))
            symlink_stage = Path(directory) / 'symlink-stage'
            symlink_stage.mkdir()
            (symlink_stage / 'phase.json').write_text(json.dumps({
                'plan_sha256': plan['plan_sha256'], 'phase': 'staged'}))
            protected = Path(directory) / 'protected'
            protected.write_bytes(b'keep')
            (symlink_stage / 'image.tar').symlink_to(protected)
            with self.assertRaises(FileExistsError):
                access.upload(symlink_stage, plan, 7, BytesIO(b'archive'))
            self.assertEqual(protected.read_bytes(), b'keep')

    def test_controller_sends_fixed_command_and_framed_archive_only(self):
        with TemporaryDirectory() as directory:
            archive = Path(directory) / 'image.tar'
            archive.write_bytes(b'archive')
            received = []
            def run(command, **options):
                received.append(options['stdin'].read())
                self.assertEqual(options['timeout'], pipeline.UPLOAD_TIMEOUT)
                return type('Result', (), {'stdout': b'{"status":"ok"}', 'returncode': 0})()
            with patch.object(pipeline.subprocess, 'run', side_effect=run) as launch:
                request = {'action': 'upload', 'plan': {'plan_sha256': 'a' * 64}, 'bytes': 7}
                self.assertEqual(pipeline.remote('synthetic-alias', request, upload=archive), {'status': 'ok'})
            command = launch.call_args.args[0]
            self.assertEqual(command[-2:], ['synthetic-alias', 'kat-release-v1'])
            self.assertIn('-T', command)
            self.assertNotIn('python3', command)
            self.assertNotIn('scp', command)
            header, payload = received[0].split(b'\n', 1)
            self.assertEqual(json.loads(header), request)
            self.assertEqual(payload, b'archive')

    def test_owned_fake_ssh_consuming_and_stalled_upload_have_bounded_outcome(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'ssh'
            archive = root / 'archive.tar'
            archive.write_bytes(b'x' * (4 * 1024 * 1024))
            request = {'action': 'upload', 'plan': {'plan_sha256': 'a' * 64},
                       'bytes': archive.stat().st_size}
            for consume in (True, False):
                binary.write_text('#!/usr/bin/python3\nimport sys,time,json\n'
                    'header=json.loads(sys.stdin.buffer.readline())\n'
                    + ('body=sys.stdin.buffer.read()\nassert len(body)==header["bytes"]\n'
                       'print(json.dumps({"status":"ok"}),flush=True)\n' if consume else 'time.sleep(5)\n'))
                binary.chmod(0o700)
                with self.subTest(consume=consume), \
                     patch.dict(os.environ, {'PATH': str(root) + ':/usr/bin:/bin'}), \
                     patch.object(pipeline, 'UPLOAD_TIMEOUT', 0.25 if not consume else 5):
                    start = monotonic()
                    if consume:
                        self.assertEqual(pipeline.remote('synthetic-alias', request, upload=archive),
                                         {'status': 'ok'})
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'phase failed'):
                            pipeline.remote('synthetic-alias', request, upload=archive)
                    self.assertLess(monotonic() - start, 3)

    def test_policy_rejects_symlink_and_nonroot_writable_ancestors(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'policy.json'
            target.write_text('{}')
            alias = Path(directory) / 'linked.json'
            alias.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'root protected'):
                access.protected(alias)
            with self.assertRaisesRegex(ValueError, 'root protected'):
                access.protected(target)


if __name__ == '__main__':
    unittest.main()
