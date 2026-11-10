"""Real owned PG additive transition tests; no real settings migration is invented."""

from hashlib import sha256
from pathlib import Path
import shutil

import psycopg

from m2.release_schema import migrate
from tests.support.database import DatabaseCase


class ReleaseSchemaTests(DatabaseCase):
    def lane(self, statement, *, tables=(), columns=None):
        directory = Path(self.directory.name) / 'synthetic-migrations'
        shutil.copytree(Path(__file__).resolve().parents[2] / 'm2/migrations', directory)
        path = directory / '037_synthetic_release_fixture.sql'
        path.write_text(statement)
        return directory, {'from': 36, 'to': 37,
                           'migrations': {path.name: sha256(path.read_bytes()).hexdigest()},
                           'added_tables': list(tables), 'added_columns': columns or {}}

    def test_additive_empty_table_preserves_archive_and_refuses_replay(self):
        self.store.create_conversation(self.alice, 'retained')
        self.store.close()
        directory, lane = self.lane('CREATE TABLE synthetic_release_note (id text PRIMARY KEY);',
                                    tables=['synthetic_release_note'])
        self.assertEqual(migrate(self.dsn, lane, directory), {'schema': 37, 'status': 'migrated'})
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT id FROM conversations').fetchall(), [('retained',)])
            self.assertEqual(db.execute('SELECT count(*) FROM synthetic_release_note').fetchone(), (0,))
        with self.assertRaisesRegex(ValueError, 'no replay'):
            migrate(self.dsn, lane, directory)

    def test_nullable_column_does_not_backfill_existing_accounts(self):
        self.store.close()
        directory, lane = self.lane('ALTER TABLE accounts ADD COLUMN synthetic_release_note text;',
                                    columns={'accounts': ['synthetic_release_note']})
        migrate(self.dsn, lane, directory)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM accounts WHERE synthetic_release_note IS NULL').fetchone(), (2,))

    def test_unqualified_hash_destructive_ddl_and_wrong_projection_leave_old_schema(self):
        self.store.close()
        directory, lane = self.lane('DROP TABLE conversations;')
        with self.assertRaisesRegex(ValueError, 'narrow additive'):
            migrate(self.dsn, lane, directory)
        path = directory / '037_synthetic_release_fixture.sql'
        path.write_text('CREATE TABLE unapproved_table (id text);')
        with self.assertRaisesRegex(ValueError, 'allowlist'):
            migrate(self.dsn, lane, directory)
        lane['migrations'][path.name] = sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'added/removed tables'):
            migrate(self.dsn, lane, directory)
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT max(version) FROM schema_migrations').fetchone(), (36,))
            self.assertIsNone(db.execute("SELECT to_regclass('public.unapproved_table')").fetchone()[0])
