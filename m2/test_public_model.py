"""Public model staging reproduces the actual offline CPU model without a user cache."""

import json
import os
from pathlib import Path
import stat
from shutil import copyfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastembed import TextEmbedding
import numpy as np
import onnxruntime as ort

from m2.evidence import LocalEmbedder
from m2.public_model import CACHE_FOLDER, FILES, REVISION, stage_cache


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local/models/fastembed'


class PublicModelTests(unittest.TestCase):
    def test_exact_allowlist_stages_offline_loadable_model(self):
        with TemporaryDirectory(prefix='kat-public-model-test-') as directory:
            target = Path(directory)
            manifest = stage_cache(CACHE, target)
            self.assertEqual(set(manifest['files']), set(FILES))
            files = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}
            self.assertEqual(files, {f'{CACHE_FOLDER}/refs/main'} | {
                f'{CACHE_FOLDER}/snapshots/{REVISION}/{name}' for name in FILES})
            with patch('m2.evidence.ort.disable_telemetry_events',
                       wraps=ort.disable_telemetry_events) as disable:
                self.assertEqual(len(LocalEmbedder(cache_dir=target).query('synthetic offline check')), 384)
                disable.assert_called_once_with()

            (target / CACHE_FOLDER / 'snapshots' / REVISION / 'config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'config.json'):
                stage_cache(target, target / 'changed')

    def test_runtime_ref_tokenizer_and_weights_refuse_before_model_load(self):
        with TemporaryDirectory(prefix='kat-public-model-runtime-') as directory:
            target = Path(directory)
            stage_cache(CACHE, target)
            cache = target / CACHE_FOLDER
            ref = cache / 'refs/main'
            snapshot = cache / 'snapshots' / REVISION
            tokenizer = snapshot / 'tokenizer.json'
            original_tokenizer = tokenizer.read_bytes()
            weights = snapshot / 'model_optimized.onnx'

            with patch('m2.evidence.TextEmbedding', side_effect=AssertionError('model loaded')):
                ref.write_text('1' * 40)
                with self.assertRaisesRegex(ValueError, 'revision'):
                    LocalEmbedder(cache_dir=target)
                ref.write_text(REVISION)

                altered = json.loads(original_tokenizer)
                altered['normalizer']['lowercase'] = False
                tokenizer.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'tokenizer.json'):
                    LocalEmbedder(cache_dir=target)
                tokenizer.write_bytes(original_tokenizer)

                with weights.open('r+b') as stream:
                    first = stream.read(1)
                    stream.seek(0)
                    stream.write(bytes([first[0] ^ 1]))
                with self.assertRaisesRegex(ValueError, 'model_optimized.onnx'):
                    LocalEmbedder(cache_dir=target)

    def test_runtime_binds_verified_snapshot_when_main_moves_after_verification(self):
        with TemporaryDirectory(prefix='kat-public-model-binding-') as directory:
            target = Path(directory)
            stage_cache(CACHE, target)
            cache = target / CACHE_FOLDER
            pinned = cache / 'snapshots' / REVISION
            ref = cache / 'refs/main'
            sentence = 'SATURN AND MERCURY REQUIRE PRECISE CHART INPUTS.'
            expected = LocalEmbedder(cache_dir=target).passage(sentence)

            fake_revision = '1' * 40
            moved = cache / 'snapshots' / fake_revision
            moved.mkdir()
            for name in FILES:
                if name == 'model_optimized.onnx':
                    (moved / name).symlink_to(pinned / name)
                else:
                    copyfile(pinned / name, moved / name)
            tokenizer = moved / 'tokenizer.json'
            altered = json.loads(tokenizer.read_text())
            altered['normalizer']['lowercase'] = False
            tokenizer.write_text(json.dumps(altered))
            changed = next(iter(TextEmbedding('BAAI/bge-small-en-v1.5',
                cache_dir=str(target), specific_model_path=str(moved),
                local_files_only=True, threads=2,
                providers=['CPUExecutionProvider']).embed([sentence])))
            self.assertGreater(np.linalg.norm(np.array(expected) - changed / np.linalg.norm(changed)), 0.01)

            def move_main_before_fastembed_load(*args, **kwargs):
                ref.write_text(fake_revision)
                return TextEmbedding(*args, **kwargs)

            with patch('m2.evidence.TextEmbedding', side_effect=move_main_before_fastembed_load):
                actual = LocalEmbedder(cache_dir=target).passage(sentence)
            self.assertTrue(np.array_equal(expected, actual))
            self.assertEqual(ref.read_text(), fake_revision)

    def test_staged_public_files_are_runtime_readable_under_secure_umask(self):
        with TemporaryDirectory(prefix='kat-public-model-modes-') as directory:
            destination = Path(directory) / 'context'
            source = CACHE / CACHE_FOLDER
            original_modes = {path: stat.S_IMODE(path.stat().st_mode) for path in (
                source / 'refs/main', source / 'snapshots' / REVISION / 'model_optimized.onnx')}
            old_umask = os.umask(0o077)
            try:
                stage_cache(CACHE, destination)
            finally:
                os.umask(old_umask)
            model = destination / CACHE_FOLDER
            directories = (model, model / 'refs', model / 'snapshots',
                           model / 'snapshots' / REVISION)
            files = [model / 'refs/main'] + [model / 'snapshots' / REVISION / name
                                              for name in FILES]
            for path in directories:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755, path.name)
            for path in files:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, path.name)
            for path, mode in original_modes.items():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_missing_snapshot_refuses_without_downloading(self):
        with TemporaryDirectory(prefix='kat-public-model-missing-') as directory:
            with self.assertRaisesRegex(ValueError, 'unavailable offline'):
                stage_cache(directory, Path(directory) / 'staged')
            with self.assertRaises(Exception):
                LocalEmbedder(cache_dir=directory)
