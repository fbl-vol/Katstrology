"""Owned run-local schema clone cannot share archive, session or deletion authority."""

import os
from pathlib import Path
from unittest.mock import patch

import psycopg

from m2.test_support import DatabaseCase


class TemplateIsolationTests(DatabaseCase):
    def test_clones_have_independent_archive_ledger_files_and_store_sessions(self):
        if not os.environ.get('KAT_ISOLATED_TEST_TEMPLATE'):
            self.skipTest('Run-local template is only created by the isolated validator')
        other = DatabaseCase('runTest')
        other.setUp()
        try:
            self.assertNotEqual(self.database, other.database)
            self.assertNotEqual(self.ledger.journal_id, other.ledger.journal_id)
            self.assertNotEqual(self.ledger.path, other.ledger.path)
            self.assertNotEqual(self.store.files, other.store.files)
            self.assertEqual(self.store.list_conversations(self.alice), [])
            self.assertEqual(other.store.list_conversations(other.alice), [])
            self.store.create_conversation(self.alice, 'first')
            self.assertEqual(other.store.list_conversations(other.alice), [])
            with self.assertRaises(PermissionError):
                other.store.owner(self.alice)
            with self.assertRaises(PermissionError):
                self.store.owner(other.alice)
            self.assertEqual(self.store.authenticate('alice', 'synthetic-password-alice').owner_id, 'alice')
        finally:
            other.doCleanups()

    def test_setup_failure_removes_cloned_db_and_independent_directory(self):
        failed = DatabaseCase('runTest')
        with patch('m2.test_support.Store', side_effect=RuntimeError('Synthetic setup failure')):
            try:
                with self.assertRaisesRegex(RuntimeError, 'Synthetic setup failure'):
                    failed.setUp()
            finally:
                failed.doCleanups()
        self.assertFalse(Path(failed.directory.name).exists())
        with psycopg.connect(self.admin_dsn) as admin:
            self.assertIsNone(admin.execute('SELECT 1 FROM pg_database WHERE datname=%s',
                                            (failed.database,)).fetchone())


class FreshMigrationFixtureTests(DatabaseCase):
    fixture_requires_fresh_migration = True

    def test_fresh_schema_enrolls_and_authenticates_on_real_store_path(self):
        self.assertEqual(self.store.authenticate('bob', 'synthetic-password-bob').owner_id, 'bob')
        with self.assertRaises(PermissionError):
            self.store.authenticate('alice', 'wrong-synthetic-password')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM schema_migrations')
                         .fetchone()['n'], len(list((Path(__file__).parent / 'migrations').glob('[0-9]*.sql'))))
