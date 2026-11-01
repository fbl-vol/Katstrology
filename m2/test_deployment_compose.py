"""Check effective Compose config, not just the YAML source spelling."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class ComposeConfigTests(TestCase):
    def test_tmpfs_is_one_qualified_mount(self):
        with TemporaryDirectory(prefix='kat-compose-config-') as directory:
            secret = Path(directory) / 'synthetic-password'
            secret.write_text('synthetic-only\n')
            ephe = Path(directory) / 'ephe'
            ephe.mkdir()
            env = {**os.environ, 'KAT_APP_IMAGE': 'sha256:' + 'a' * 64,
                   'KAT_DB_PASSWORD_FILE': str(secret), 'KAT_EPHE_DIR': str(ephe)}
            output = subprocess.check_output(
                ['docker', 'compose', '-f', str(ROOT / 'deploy/compose.yaml'),
                 'config', '--format', 'json'], env=env, text=True)
        config = json.loads(output)
        self.assertEqual(config['services']['app']['tmpfs'],
                         ['/tmp:rw,noexec,nosuid,size=64m'])
        self.assertIn('/opt/kat/web/dist', config['services']['app']['command'])
