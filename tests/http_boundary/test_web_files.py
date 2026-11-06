"""Person-owned file references survive snapshots and honor later tombstones."""

from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.attachments import Attachments
from m2.archive.backup import backup, restore
from m2.calculation.charts import Charts
from m2.people.people import People
from tests.support.database import DatabaseCase, seed_legacy_person_file


class PersonFileRecoveryTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def test_shared_blob_backup_and_newer_person_file_deletion(self):
        Charts(self.store).add_person(self.alice, 'person', 'Synthetic person')
        self.store.create_conversation(self.alice, 'thread')
        files = Attachments(self.store)
        content = b'%PDF-1.4\nSynthetic chart reference only'
        files.add(self.alice, 'thread', 'conversation-file', 'conversation.pdf', content)
        digest = seed_legacy_person_file(self.store, self.alice, 'person', 'person-file', 'person.pdf', content)
        self.assertEqual(files._content(digest), content)

        self.ledger.delete_attachment(self.store, self.alice, 'thread', 'conversation-file')
        self.assertEqual(files._content(digest), content)
        snapshot = Path(self.directory.name) / 'person-snapshot'
        manifest = backup(self.store, snapshot)
        self.assertEqual(len(manifest['blobs']), 1)

        self.ledger.delete_person_attachment(self.store, self.alice, 'person', 'person-file')
        self.assertTrue(self.ledger.contains_person_attachment('alice', 'person', 'person-file'))
        self.assertIsNone(self.store.db.execute('''
            SELECT 1 FROM person_attachments WHERE owner_id=%s AND person_id=%s AND id=%s
        ''', ('alice', 'person', 'person-file')).fetchone())

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
            self.assertIsNone(restored.db.execute('''
                SELECT 1 FROM person_attachments WHERE owner_id=%s AND person_id=%s AND id=%s
            ''', ('alice', 'person', 'person-file')).fetchone())
            self.assertTrue(self.ledger.contains_person_attachment('alice', 'person', 'person-file'))
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
