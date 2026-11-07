"""Offline CLI/tool boundary only; real restore semantics use owned PG fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo

from m2.archive.backup import backup, deployment_pg_command, deployment_snapshot_source
from tests.support.database import DatabaseCase


class DeploymentSnapshotTests(DatabaseCase):
    fixture_requires_fresh_migration = True

    def test_refuses_active_owner_before_any_backup(self):
        destination = Path(self.directory.name) / 'active-snapshot'
        with self.assertRaisesRegex(RuntimeError, 'owner already active'):
            with deployment_snapshot_source(self.dsn, self.store.files, self.ledger.path) as source:
                backup(source, destination)
        self.assertFalse(destination.exists())

    def test_missing_journal_cannot_be_invented_by_backup(self):
        self.store.close()
        absent = Path(self.directory.name) / 'absent/deletions.jsonl'
        destination = Path(self.directory.name) / 'missing-journal-snapshot'
        with self.assertRaisesRegex(ValueError, 'journal/tip required'):
            with deployment_snapshot_source(self.dsn, self.store.files, absent) as source:
                backup(source, destination)
        self.assertFalse(absent.parent.exists())
        self.assertFalse(destination.exists())

    def test_old_schema_refusal_does_not_migrate_or_create_snapshot(self):
        self.store.close()
        with psycopg.connect(self.dsn, autocommit=True) as db:
            with db.transaction():
                db.execute('ALTER TABLE reference_sources DROP CONSTRAINT reference_sources_one_previous_check')
                db.execute('ALTER TABLE reference_sources DROP COLUMN supersedes_deleted_source_id')
                db.execute('DROP TABLE reference_book_locations, reference_book_sources')
                db.execute('DELETE FROM schema_migrations WHERE version>=22')
        journal = self.ledger.path.read_bytes()
        tip_path = self.ledger.path.with_name(self.ledger.path.name + '.tip')
        tip = tip_path.read_bytes()
        destination = Path(self.directory.name) / 'old-schema-snapshot'
        with self.assertRaisesRegex(RuntimeError, 'current migrated schema'):
            with deployment_snapshot_source(self.dsn, self.store.files, self.ledger.path) as source:
                backup(source, destination)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0], 21)
            self.assertIsNone(db.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name='reference_sources' AND column_name='supersedes_deleted_source_id'
            """).fetchone())
        self.assertEqual(self.ledger.path.read_bytes(), journal)
        self.assertEqual(tip_path.read_bytes(), tip)
        self.assertFalse(destination.exists())

    def test_current_schema_snapshots_read_only_with_existing_journal(self):
        self.store.close()
        destination = Path(self.directory.name) / 'current-snapshot'
        before = self.ledger.path.read_bytes()

        def synthetic_dump(_dsn, path):
            path.write_bytes(b'synthetic non-restorable pg dump')

        with deployment_snapshot_source(self.dsn, self.store.files, self.ledger.path) as source:
            manifest = backup(source, destination, dump_database=synthetic_dump)
        self.assertEqual(manifest['schema_version'], 31)
        self.assertTrue((destination / 'manifest.json').is_file())
        self.assertEqual(self.ledger.path.read_bytes(), before)


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

                with patch('m2.archive.backup.subprocess.run', side_effect=observe) as executed:
                    deployment_pg_command(dsn, target, restore_mode=restore_mode)
                    executed.assert_called_once()

    def test_non_private_db_is_rejected_before_process(self):
        dsn = make_conninfo(host='127.0.0.1', port=5432, dbname='kat', user='kat', password='synthetic')
        with patch('m2.archive.backup.subprocess.run') as executed:
            with self.assertRaises(ValueError):
                deployment_pg_command(dsn, '/tmp/not-created')
            executed.assert_not_called()
