"""Public model staging reproduces the actual offline CPU model without a user cache."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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
            self.assertEqual(len(LocalEmbedder(cache_dir=target).query('synthetic offline check')), 384)

            (target / CACHE_FOLDER / 'snapshots' / REVISION / 'config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'config.json'):
                stage_cache(target, target / 'changed')

    def test_missing_snapshot_refuses_without_downloading(self):
        with TemporaryDirectory(prefix='kat-public-model-missing-') as directory:
            with self.assertRaisesRegex(ValueError, 'unavailable offline'):
                stage_cache(directory, Path(directory) / 'staged')
            with self.assertRaises(Exception):
                LocalEmbedder(cache_dir=directory)
