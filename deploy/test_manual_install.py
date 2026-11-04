"""Installer mechanics against owned synthetic files; no actual root access."""

from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy import install_manual_transition as installer
from deploy.test_manual_transition import LANE


class InstallFixture:
    def __init__(self, root):
        self.root = root
        self.bundle, self.destination, self.stage = (root / name for name in ('bundle', 'installed', 'stages'))
        for path in (self.bundle, self.destination, self.stage):
            path.mkdir()
        self.policy_path = root / 'policy.json'
        compose = root / 'compose.yaml'
        compose.write_text('synthetic compose')
        self.policy = {'contract': 4, 'schema_version': 23, 'compose_file': str(compose),
                       'target': {'stage_root': str(self.stage), 'origin': 'https://example.invalid'},
                       'approval_principal': 'unchanged-signer', 'allowed_signers_sha256': 'f' * 64}
        self.policy_path.write_text(json.dumps(self.policy))
        self.before = self.policy_path.read_bytes()
        old = {'release_access.py': b'old synthetic access', 'release_remote.py': b'old synthetic phase'}
        for name, body in old.items():
            (self.destination / name).write_bytes(body)
        new = {'release_access.py': b'import json\ndef read_policy(path): return json.loads(path.read_text())\n',
               'release_remote.py': b'# new synthetic phase\n', 'release_pipeline.py': b'# new controller\n'}
        for name, body in new.items():
            (self.bundle / name).write_bytes(body)
        manifest = {'contract': 1, 'expected_policy_sha256': sha256(self.before).hexdigest(),
                    'expected_old_helpers': {name: sha256(body).hexdigest() for name, body in old.items()},
                    'new_helpers': {name: sha256(body).hexdigest() for name, body in new.items()},
                    'compose_sha256': sha256(compose.read_bytes()).hexdigest(),
                    'manual_transition_lane': LANE, 'writes': 'bounded synthetic fixture'}
        (self.bundle / 'install-manifest.json').write_text(json.dumps(manifest))
        self.manifest_hash = sha256((self.bundle / 'install-manifest.json').read_bytes()).hexdigest()

    def protected(self, path, *, directory=False):
        if self.root not in path.parents or path.is_symlink() or not (path.is_dir() if directory else path.is_file()):
            raise AssertionError('Installer test attempted a foreign destination')
        return path

    def install(self, *, execute=True):
        with ExitStack() as stack:
            stack.enter_context(patch.object(installer, 'POLICY', self.policy_path))
            stack.enter_context(patch.object(installer, 'protected', side_effect=self.protected))
            stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
            return installer.install(self.bundle, self.manifest_hash, self.destination, execute=execute)


class ManualInstallTests(unittest.TestCase):
    def test_plan_mode_never_reads_root_or_requires_root_identity(self):
        with TemporaryDirectory() as directory:
            fixture = InstallFixture(Path(directory))
            with patch.object(installer, 'protected', side_effect=AssertionError('root read')), \
                    patch.object(installer.os, 'geteuid', side_effect=AssertionError('root identity')):
                result = installer.install(fixture.bundle, fixture.manifest_hash, Path('/not-an-installed-directory'))
            self.assertEqual(result['status'], 'plan-only')
            self.assertFalse(result['root_access'])
            self.assertEqual(fixture.policy_path.read_bytes(), fixture.before)

    def test_exact_install_preserves_all_policy_fields_and_refuses_replay(self):
        with TemporaryDirectory() as directory:
            fixture = InstallFixture(Path(directory))
            result = fixture.install()
            after = json.loads(fixture.policy_path.read_text())
            self.assertEqual(after.pop('manual_transitions'), [LANE])
            self.assertEqual(after, fixture.policy)
            self.assertEqual((Path(result['retained_before']) / 'policy.json').read_bytes(), fixture.before)
            self.assertEqual(result['status'], 'installed-not-released')
            self.assertFalse(result['app_or_database_actions'])
            with self.assertRaisesRegex(ValueError, 'policy changed'):
                fixture.install()

    def test_changed_pins_or_active_attempt_refuse_before_replacement(self):
        for changed in ('manifest', 'bundle', 'policy', 'helper', 'controller', 'active-attempt'):
            with self.subTest(changed=changed), TemporaryDirectory() as directory:
                fixture = InstallFixture(Path(directory))
                if changed == 'manifest':
                    fixture.manifest_hash = '0' * 64
                elif changed == 'bundle':
                    (fixture.bundle / 'release_remote.py').write_text('tampered')
                elif changed == 'policy':
                    fixture.policy_path.write_bytes(fixture.before + b' ')
                elif changed == 'helper':
                    (fixture.destination / 'release_remote.py').write_text('other version')
                elif changed == 'controller':
                    (fixture.destination / 'release_pipeline.py').write_text('unidentified existing controller')
                else:
                    (fixture.stage / 'active-attempt').write_text('existing-attempt')
                before = {path: path.read_bytes() for path in fixture.destination.iterdir()}
                policy_before = fixture.policy_path.read_bytes()
                with self.assertRaises(ValueError):
                    fixture.install()
                self.assertEqual({path: path.read_bytes() for path in fixture.destination.iterdir()}, before)
                self.assertEqual(fixture.policy_path.read_bytes(), policy_before)

    def test_partial_install_retains_originals_and_has_no_automatic_retry_or_rollback(self):
        with TemporaryDirectory() as directory:
            fixture = InstallFixture(Path(directory))
            original_replace = os.replace
            calls = []
            def lost_write(source, destination):
                calls.append(destination)
                if len(calls) == 2:
                    raise OSError('synthetic persistence failure')
                original_replace(source, destination)
            with patch.object(installer.os, 'replace', side_effect=lost_write), self.assertRaises(OSError):
                fixture.install()
            backup = next(fixture.destination.glob('manual-transition-before-*'))
            self.assertEqual((backup / 'policy.json').read_bytes(), fixture.before)
            self.assertEqual(fixture.policy_path.read_bytes(), fixture.before)
            self.assertEqual((fixture.destination / 'release_remote.py').read_bytes(),
                             (fixture.bundle / 'release_remote.py').read_bytes())
            with self.assertRaisesRegex(ValueError, 'helper changed'):
                fixture.install()

    def test_non_root_execution_and_unprotected_paths_are_rejected(self):
        with TemporaryDirectory() as directory:
            fixture = InstallFixture(Path(directory))
            with patch.object(installer.os, 'geteuid', return_value=1000), self.assertRaises(ValueError):
                installer.install(fixture.bundle, fixture.manifest_hash, fixture.destination, execute=True)
            if os.geteuid() != 0:
                with self.assertRaises(ValueError):
                    installer.protected(fixture.policy_path)


if __name__ == '__main__':
    unittest.main()
