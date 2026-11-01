"""Offline CLI/tool boundary only; real restore semantics use owned PG fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from psycopg.conninfo import make_conninfo

from m2.backup import deployment_pg_command


class PgCommandTests(TestCase):
    def test_db_secret_is_not_in_process_arguments_or_environment(self):
        secret = 'synthetic:password\\with-escape'
        dsn = make_conninfo(host='db', port=5432, dbname='kat', user='kat', password=secret)
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'snapshot.dump'
            for restore_mode in (False, True):
                if restore_mode:
                    target.write_bytes(b'synthetic-format')

                def observe(argv, **kwargs):
                    self.assertEqual(argv[0], 'pg_restore' if restore_mode else 'pg_dump')
                    self.assertNotIn(secret, repr(argv))
                    self.assertNotIn(secret, repr(kwargs['env']))
                    passfile = Path(kwargs['env']['PGPASSFILE'])
                    self.assertEqual(passfile.stat().st_mode & 0o077, 0)
                    self.assertIn('synthetic\\:password\\\\with-escape', passfile.read_text())
                    return type('Result', (), {'returncode': 0})()

                with patch('m2.backup.subprocess.run', side_effect=observe) as executed:
                    deployment_pg_command(dsn, target, restore_mode=restore_mode)
                    executed.assert_called_once()

    def test_non_private_db_is_rejected_before_process(self):
        dsn = make_conninfo(host='127.0.0.1', port=5432, dbname='kat', user='kat', password='synthetic')
        with patch('m2.backup.subprocess.run') as executed:
            with self.assertRaises(ValueError):
                deployment_pg_command(dsn, '/tmp/not-created')
            executed.assert_not_called()
