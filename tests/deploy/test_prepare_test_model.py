"""Cold-runner prerequisites must be real, integrity-checked and test-only."""

from hashlib import sha256
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy import prepare_ci_inputs, prepare_test_model as model


class PublicTokenizerPreparationTests(unittest.TestCase):
    def test_cold_download_and_warm_cache_both_verify_exact_bytes(self):
        content = b'public synthetic tokenizer fixture'
        opener = Mock()
        opener.open.return_value = io.BytesIO(content)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(model, 'MODEL_SIZE', len(content)), \
                patch.object(model, 'MODEL_SHA256', sha256(content).hexdigest()), \
                patch.object(model, 'build_opener', return_value=opener):
            path = Path(directory) / 'models' / 'fixture.gguf'
            model.prepare_model(path)
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(list(path.parent.iterdir()), [path])
            opener.open.assert_called_once_with(model.MODEL_URL, timeout=60)
            model.prepare_model(path)
            opener.open.assert_called_once()  # Valid warm cache does not fetch.
            path.write_bytes(b'x' * len(content))
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                model.prepare_model(path)
            self.assertEqual(path.read_bytes(), b'x' * len(content))
            opener.open.assert_called_once()  # Corrupt cache is not silently replaced.

    def test_short_oversized_corrupt_and_interrupted_downloads_never_publish(self):
        expected = b'public model'
        for received in (b'short', b'x' * 100, b'x' * len(expected), None):
            with self.subTest(received=received), tempfile.TemporaryDirectory() as directory, \
                    patch.object(model, 'MODEL_SIZE', len(expected)), \
                    patch.object(model, 'MODEL_SHA256', sha256(expected).hexdigest()), \
                    patch.object(model, 'build_opener') as build:
                path = Path(directory) / 'fixture.gguf'
                if received is None:
                    build.return_value.open.side_effect = TimeoutError('synthetic download timeout')
                else:
                    build.return_value.open.return_value = io.BytesIO(received)
                with self.assertRaises((ValueError, TimeoutError)):
                    model.prepare_model(path)
                self.assertFalse(path.exists())
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_symlink_cache_is_rejected_without_modifying_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'owned-target'
            target.write_bytes(b'keep')
            path = Path(directory) / 'fixture.gguf'
            path.symlink_to(target)
            with patch.object(model, 'build_opener') as build, self.assertRaises(ValueError):
                model.prepare_model(path)
            build.assert_not_called()
            self.assertEqual(target.read_bytes(), b'keep')

    def test_installer_uses_pinned_cpu_wheel_and_preserves_failure(self):
        with patch.object(model.sys, 'prefix', '/synthetic-venv'), \
                patch.object(model.sys, 'base_prefix', '/synthetic-base'), \
                patch.object(model.subprocess, 'run') as run:
            model.install_binding()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:3], [model.sys.executable, '-m', 'pip'])
            self.assertIn('--isolated', argv)
            self.assertIn('--only-binary=:all:', argv)
            self.assertIn(str(model.ROOT / 'probes/requirements-model.txt'), argv)
            self.assertTrue(argv[-1].startswith('https://github.com/abetlen/llama-cpp-python/releases/'))
            self.assertIn('#sha256=', argv[-1])
            self.assertTrue(run.call_args.kwargs['check'])
            failure = subprocess.CalledProcessError(1, argv)
            run.side_effect = failure
            with patch.object(model, 'prepare_model') as prepare, \
                    self.assertRaises(subprocess.CalledProcessError) as caught:
                model.main()
            self.assertIs(caught.exception, failure)
            prepare.assert_not_called()
        with patch.object(model.sys, 'prefix', '/base'), patch.object(model.sys, 'base_prefix', '/base'), \
                patch.object(model.subprocess, 'run') as run, self.assertRaises(ValueError):
            model.install_binding()
        run.assert_not_called()

    def test_existing_ci_input_entrypoint_prepares_the_tokenizer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ephe = root / '.local/ephe'
            ephe.mkdir(parents=True)
            (ephe / 'synthetic.se1').write_bytes(b'public ephemeris')
            with patch.object(prepare_ci_inputs, '__file__', str(root / 'deploy/prepare_ci_inputs.py')), \
                    patch.object(prepare_ci_inputs, 'FILES', {
                        'synthetic.se1': sha256(b'public ephemeris').hexdigest()}), \
                    patch.object(prepare_ci_inputs.prepare_test_model, 'main') as prepare:
                prepare_ci_inputs.main()
            prepare.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
