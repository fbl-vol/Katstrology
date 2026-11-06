"""Forced-command boundary: all fixtures are synthetic, no server/SSH contact."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from deploy import release_access as access
from deploy import release_pipeline as pipeline
from deploy import release_remote
from tests.deploy.test_release_pipeline import synthetic_target


def fixture(directory):
    root = Path(directory)
    target = synthetic_target() | {'stage_root': str(root / 'stages')}
    Path(target['stage_root']).mkdir()
    compose = root / 'compose.yaml'
    compose.write_text('synthetic protected compose')
    key = root / 'approval-key'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                   check=True, stdout=subprocess.DEVNULL)
    allowed = root / 'allowed-signers'
    allowed.write_text('kat-approver ' + ' '.join(key.with_suffix('.pub').read_text().split()[:2]) + '\n')
    receipt = {'commit': 'a' * 40, 'tree': 'b' * 40,
               'image_id': 'sha256:' + 'c' * 64, 'config_digest': 'sha256:' + 'd' * 64,
               'image_archive_sha256': sha256(b'archive').hexdigest(),
               'source_offer_sha256': sha256(b'source!').hexdigest()}
    plan = pipeline.plan(receipt, target, 22, compose.read_bytes(), '1' * 32, 7, 7)
    policy = {'contract': 4, 'target': target, 'compose_file': str(compose), 'schema_version': 22,
              'max_archive_bytes': 1024, 'max_source_bytes': 1024, 'approval_principal': 'kat-approver',
              'approval_namespace': access.APPROVAL_NAMESPACE,
              'allowed_signers_file': str(allowed),
              'allowed_signers_sha256': pipeline.digest(allowed)}
    return plan, policy


def signed_request(plan, directory, action, *, key_name='approval-key', namespace=None, **extra):
    approval = {'approved_action': 'release', 'attempt': plan['attempt'],
                'plan_sha256': plan['plan_sha256']}
    payload = (json.dumps(approval, sort_keys=True, separators=(',', ':')) + '\n').encode()
    result = subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign',
            '-f', str(Path(directory) / key_name), '-n', namespace or access.APPROVAL_NAMESPACE],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    return {'action': action, 'plan': plan, 'approval': approval,
            'signature': result.stdout.decode(), **extra}


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
                request = signed_request(plan, directory, 'stage')
                result = access.dispatch(request, policy, BytesIO())
                self.assertEqual(result, {'phase': 'stage', 'status': 'ok'})
                self.assertEqual(release_remote.REQUEST['target'], policy['target'] | {
                    'stage': str(Path(policy['target']['stage_root']) / plan['attempt'])})
                phase.assert_called_once_with()
                for bad in (
                    request | {'command': 'docker ps'},
                    request | {'target': {'stage': '/etc'}},
                    request | {'compose': 'services: {evil: {privileged: true}}'},
                    request | {'mounts': ['/var/run/docker.sock:/docker.sock']},
                    request | {'action': 'upload', 'bytes': 1025},
                    request | {'action': 'upload', 'bytes': -1},
                    request | {'action': 'exec'},
                ):
                    with self.subTest(bad=list(bad)):
                        with self.assertRaises(ValueError):
                            access.dispatch(bad, policy, BytesIO())
                phase.assert_called_once()
                changed = json.loads(json.dumps(plan))
                changed['target']['target_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Protected approval'):
                    access.dispatch(request | {'plan': changed}, policy, BytesIO())
                changed = json.loads(json.dumps(plan))
                changed['artifact']['config_digest'] = 'sha256:' + 'e' * 64
                with self.assertRaisesRegex(ValueError, 'Protected approval'):
                    access.dispatch(request | {'plan': changed}, policy, BytesIO())
                policy['approval_principal'] = 'wrong-approver'
                with self.assertRaisesRegex(ValueError, 'signature differs'):
                    access.dispatch(request, policy, BytesIO())

    def test_upload_is_exclusive_bounded_hash_checked_and_never_a_path(self):
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            stage = Path(policy['target']['stage_root']) / plan['attempt']
            stage.mkdir()
            (Path(policy['target']['stage_root']) / 'active-attempt').write_text(plan['attempt'] + '\n')
            (stage / 'phase.json').write_text(json.dumps({'plan_sha256': plan['plan_sha256'], 'phase': 'staged'}))
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)), \
                 patch.object(release_remote, 'main') as phase:
                request = signed_request(plan, directory, 'upload', bytes=7)
                self.assertEqual(access.dispatch(request, policy, BytesIO(b'archive'))['status'], 'ok')
                self.assertEqual((stage / 'image.tar').read_bytes(), b'archive')
                self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'image_uploaded')
                with self.assertRaisesRegex(ValueError, 'exclusive fresh stage'):
                    access.dispatch(request, policy, BytesIO(b'archive'))
                source_request = signed_request(plan, directory, 'upload_source', bytes=7)
                self.assertEqual(access.dispatch(source_request, policy, BytesIO(b'source!'))['status'], 'ok')
                self.assertEqual((stage / 'source.tar').read_bytes(), b'source!')
                self.assertEqual(json.loads((stage / 'phase.json').read_text())['phase'], 'uploaded')
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
                self.assertEqual(pipeline.remote('synthetic-alias', request, upload=archive,
                                                 ssh_config='/synthetic/client-profile'), {'status': 'ok'})
            command = launch.call_args.args[0]
            self.assertEqual(command[-2:], ['synthetic-alias', 'kat-release-v1'])
            self.assertEqual(command[1:3], ['-F', '/synthetic/client-profile'])
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

    def test_native_signed_exact_approvals_gate_effects_and_support_next_attempt(self):
        with TemporaryDirectory() as directory:
            plan, policy = fixture(directory)
            stage_root = Path(policy['target']['stage_root'])
            other_key = Path(directory) / 'deployment-key'
            subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(other_key)],
                           check=True, stdout=subprocess.DEVNULL)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)):
                valid = signed_request(plan, directory, 'stage')
                invalid = (
                    valid | {'signature': ''},
                    signed_request(plan, directory, 'stage', key_name='deployment-key'),
                    signed_request(plan, directory, 'stage', namespace='wrong-namespace'),
                    valid | {'approval': valid['approval'] | {'attempt': '2' * 32}},
                    valid | {'plan': plan | {'attempt': '2' * 32}},
                    valid | {'plan': plan | {'artifact': plan['artifact'] | {
                        'config_digest': 'sha256:' + 'e' * 64}}},
                    valid | {'plan': plan | {'target': plan['target'] | {'project': 'other'}}},
                    valid | {'bytes': 100},
                )
                other_target = policy['target'] | {'password_file': '/srv/unrelated-secret'}
                other_plan = pipeline.plan(plan['artifact'], other_target, 22,
                    Path(policy['compose_file']).read_bytes(), '3' * 32, 7, 7)
                invalid += (signed_request(other_plan, directory, 'stage'),)
                for request in invalid:
                    with self.subTest(request=list(request), signature=request.get('signature', '')[:35]):
                        with self.assertRaises(ValueError):
                            access.dispatch(request, policy, BytesIO())
                        self.assertEqual(list(stage_root.iterdir()), [])
                self.assertEqual(access.dispatch(valid, policy, BytesIO())['status'], 'ok')
                first = stage_root / plan['attempt']
                self.assertTrue(first.is_dir())
                with self.assertRaisesRegex(ValueError, 'no retry'):
                    access.dispatch(valid, policy, BytesIO())
                later = pipeline.plan(plan['artifact'], policy['target'], 22,
                                      Path(policy['compose_file']).read_bytes(), '2' * 32, 7, 7)
                stale = valid | {'plan': later}
                with self.assertRaises(ValueError):
                    access.dispatch(stale, policy, BytesIO())
                self.assertFalse((stage_root / later['attempt']).exists())
                with self.assertRaises(FileExistsError):
                    access.dispatch(signed_request(later, directory, 'stage'), policy, BytesIO())
                # Simulate explicitly reconciled retirement, never an automatic retry.
                (stage_root / 'active-attempt').unlink()
                self.assertEqual(access.dispatch(signed_request(later, directory, 'stage'),
                                                 policy, BytesIO())['status'], 'ok')
                self.assertTrue((stage_root / later['attempt']).is_dir())

    def test_protected_policy_pins_signer_file_and_existing_stage_root(self):
        with TemporaryDirectory() as directory:
            _, policy = fixture(directory)
            policy['target']['stage_root'] = '/srv/synthetic-protected-kat-stages'
            path = Path(directory) / 'policy.json'
            path.write_text(json.dumps(policy))
            original_lstat = Path.lstat
            def synthetic_root(path, *args, **kwargs):
                if str(path) == '/srv/synthetic-protected-kat-stages':
                    return SimpleNamespace(st_mode=0o40700, st_uid=0)
                info = original_lstat(path, *args, **kwargs)
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0)
            with patch.object(access, 'protected', side_effect=lambda path: Path(path)), \
                 patch.object(Path, 'lstat', synthetic_root):
                self.assertEqual(access.read_policy(path), policy)
                signer = Path(policy['allowed_signers_file'])
                signer.write_text('kat-approver ssh-ed25519 AAAA\n')
                with self.assertRaisesRegex(ValueError, 'signer identity changed'):
                    access.read_policy(path)
                policy['allowed_signers_sha256'] = pipeline.digest(signer)
                signer.write_text(signer.read_text() + 'other ssh-ed25519 AAAA\n')
                policy['allowed_signers_sha256'] = pipeline.digest(signer)
                path.write_text(json.dumps(policy))
                with self.assertRaisesRegex(ValueError, 'signer entry differs'):
                    access.read_policy(path)
                signer.write_text('kat-approver ssh-ed25519 AAAA\n')
                policy['allowed_signers_sha256'] = pipeline.digest(signer)
                policy['target']['stage_root'] = '/srv/synthetic-absent-kat-stages'
                path.write_text(json.dumps(policy))
                with self.assertRaises(FileNotFoundError):
                    access.read_policy(path)

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
