"""Person-owned file references survive snapshots and honor later tombstones."""

from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.attachments import Attachments
from m2.backup import backup, restore
from m2.charts import Charts
from m2.people import People
from m2.test_support import DatabaseCase


class PersonFileRecoveryTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def test_shared_blob_backup_and_newer_person_file_deletion(self):
        Charts(self.store).add_person(self.alice, 'person', 'Synthetic person')
        self.store.create_conversation(self.alice, 'thread')
        files = Attachments(self.store)
        content = b'%PDF-1.4\nSynthetic chart reference only'
        files.add(self.alice, 'thread', 'conversation-file', 'conversation.pdf', content)
        files.add_person(self.alice, 'person', 'person-file', 'person.pdf', content)
        with self.assertRaises(KeyError):
            files.read_person(self.bob, 'person', 'person-file')

        self.ledger.delete_attachment(self.store, self.alice, 'thread', 'conversation-file')
        self.assertEqual(files.read_person(self.alice, 'person', 'person-file')[1], content)
        snapshot = Path(self.directory.name) / 'person-snapshot'
        manifest = backup(self.store, snapshot)
        self.assertEqual(len(manifest['blobs']), 1)

        self.ledger.delete_person_attachment(self.store, self.alice, 'person', 'person-file')
        with self.assertRaises(ValueError):
            files.add_person(self.alice, 'person', 'person-file', 'person.pdf', content)
        with self.assertRaises(KeyError):
            files.read_person(self.alice, 'person', 'person-file')

        target = 'kat_person_restore_' + uuid4().hex[:12]
        target_dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(snapshot, target_dsn, Path(self.directory.name) / 'restored-files',
                               self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(People(restored).get(alice, 'person')['name'], 'Synthetic person')
            with self.assertRaises(KeyError):
                Attachments(restored).read_person(alice, 'person', 'person-file')
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
