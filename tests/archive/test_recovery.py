import json
from pathlib import Path
import tempfile
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.attachments import Attachments
from m2.archive.backup import backup, restore
from m2.archive.deletion import Tombstones
from m2.chat.recall import rebuild_one, rebuild_pending, search
from m2.references.references import References
from tests.support.database import DatabaseCase


class RecoveryTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def complete(self, conv, turn, prompt):
        self.store.begin(self.alice, conv, turn, prompt)
        self.store.append(self.alice, conv, turn, 'complete', {})

    def test_delete_fences_pending_rebuild_and_preserves_shared_blob(self):
        for name in ('one', 'two'):
            self.store.create_conversation(self.alice, name)
        files = Attachments(self.store)
        data = b'synthetic shared reference'
        digest = files.add(self.alice, 'one', 'a', 'synthetic.txt', data)
        files.add(self.alice, 'two', 'b', 'synthetic.txt', data)
        self.complete('one', 'turn', 'secretword to delete')
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'secretword')['results'][0]['conversation_id'], 'one')
        self.ledger.delete_attachment(self.store, self.alice, 'one', 'a')
        self.assertEqual(files.read(self.alice, 'two', 'b'), data)
        self.assertTrue((files.directory / digest).exists())
        with self.assertRaises(KeyError):
            files.read(self.alice, 'one', 'a')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            files.add(self.alice, 'one', 'a', 'synthetic.txt', data)
        self.complete('one', 'pending', 'queuedword')
        queued_epoch = self.store._conversation('alice', 'one')['epoch']
        self.ledger.delete_conversation(self.store, self.alice, 'one')
        with self.assertRaises(KeyError):
            rebuild_one(self.store, self.alice, 'one', queued_epoch)
        self.assertEqual(search(self.store, self.alice, 'secretword')['results'], [])
        with self.assertRaises(KeyError):
            self.store.read_turn(self.alice, 'one', 'turn')
        with self.assertRaisesRegex(ValueError, 'cannot be reused'):
            self.store.create_conversation(self.alice, 'one')
        self.assertEqual(files.read(self.alice, 'two', 'b'), data)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM rebuild_queue').fetchone()['n'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM summaries').fetchone()['n'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM search_entries').fetchone()['n'], 0)
        self.assertEqual(rebuild_pending(self.store, self.alice), 0)
        self.ledger.delete_conversation(self.store, self.alice, 'two')
        self.assertFalse((files.directory / digest).exists())

    def test_journal_committed_before_db_refusal_blocks_serving_until_reconciled(self):
        self.store.create_conversation(self.alice, 'doomed')
        self.complete('doomed', 'turn', 'synthetic sensitive')
        self.store.db.execute('SET default_transaction_read_only = on')
        try:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                self.ledger.delete_conversation(self.store, self.alice, 'doomed')
            with self.assertRaisesRegex(RuntimeError, 'reconciliation required'):
                self.store.read_turn(self.alice, 'doomed', 'turn')
            self.assertIn('doomed', self.ledger.path.read_text())
        finally:
            self.store.db.execute('SET default_transaction_read_only = off')
        self.ledger.reconcile(self.store)
        with self.assertRaises(KeyError):
            self.store.read_turn(self.alice, 'doomed', 'turn')

    def test_snapshot_refuses_corrupt_inline_reference_before_dump(self):
        text = 'Original synthetic notebook page.'
        References(self.store).ingest_edition(self.alice, {
            'source_id': 'original', 'author': 'Synthetic author', 'title': 'Synthetic page',
            'edition': 'v1', 'tradition': 'invented_fixture', 'technique': 'aspects',
            'provenance': 'Synthetic fixture only', 'rights_basis': 'synthetic_fixture',
            'rights_evidence': 'Synthetic fixture only', 'language': 'en',
            'extraction_note': 'Synthetic text only'}, text,
            [{'id': 'one', 'section': 'part', 'content': text}])
        self.store.db.execute("UPDATE reference_originals SET original_text='altered' WHERE source_id='original'")
        target = Path(self.directory.name) / 'rejected-snapshot'
        with self.assertRaisesRegex(RuntimeError, 'Stored reference checksum mismatch'):
            backup(self.store, target)
        self.assertFalse(target.exists())

    def test_restore_backup_predating_deletion_replays_newer_ledger_before_access(self):
        self.store.create_conversation(self.alice, 'deleted')
        self.store.create_conversation(self.alice, 'retained')
        files = Attachments(self.store)
        content = b'private-looking but synthetic bytes'
        digest = files.add(self.alice, 'deleted', 'file', 'synthetic.txt', content)
        files.add(self.alice, 'retained', 'file', 'synthetic.txt', content)
        self.complete('deleted', 'old', 'restoresecret')
        rebuild_pending(self.store, self.alice)
        self.complete('deleted', 'pending', 'pendingword')  # queued, not indexed in backup
        snapshot = Path(self.directory.name) / 'snapshot'
        backup(self.store, snapshot)
        self.assertEqual((snapshot / 'blobs' / digest).read_bytes(), content)

        self.ledger.delete_conversation(self.store, self.alice, 'deleted')
        self.assertEqual(files.read(self.alice, 'retained', 'file'), content)
        target_name = 'kat_m2_restored_' + uuid4().hex[:12]
        target_dsn = make_conninfo(self.admin_dsn, dbname=target_name)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target_name)))
        restored = None
        try:
            with self.assertRaisesRegex(RuntimeError, 'journal is missing or diverged'):
                restore(snapshot, target_dsn, Path(self.directory.name) / 'unsafe-restore',
                        Tombstones(Path(self.directory.name) / 'wrong-ledger.jsonl'))
            self.assertFalse((Path(self.directory.name) / 'unsafe-restore').exists())
            (snapshot / 'blobs' / digest).write_bytes(b'corrupted synthetic snapshot')
            with self.assertRaisesRegex(RuntimeError, 'blob checksum mismatch'):
                restore(snapshot, target_dsn, Path(self.directory.name) / 'corrupt-restore',
                        self.ledger)
            self.assertFalse((Path(self.directory.name) / 'corrupt-restore').exists())
            (snapshot / 'blobs' / digest).write_bytes(content)
            # Legacy format-1 backups lacked an explicit schema revision. The
            # normal local restore still accepts them with newer deletion authority.
            manifest_path = snapshot / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest.pop('schema_version')
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Unsupported backup manifest'):
                restore(snapshot, target_dsn, Path(self.directory.name) / 'legacy-rejected',
                        self.ledger, require_current_schema=True)
            self.assertFalse((Path(self.directory.name) / 'legacy-rejected').exists())
            restored = restore(snapshot, target_dsn,
                               Path(self.directory.name) / 'restored-files', self.ledger)
            user = restored.authenticate('alice', 'synthetic-password-alice')
            with self.assertRaises(KeyError):
                restored.read_turn(user, 'deleted', 'old')
            self.assertEqual(search(restored, user, 'restoresecret')['results'], [])
            self.assertEqual(search(restored, user, 'pendingword')['results'], [])
            self.assertEqual(rebuild_pending(restored, user), 0)
            self.assertEqual(Attachments(restored).read(user, 'retained', 'file'), content)
            self.assertEqual(restored.db.execute('SELECT count(*) AS n FROM attachments').fetchone()['n'], 1)
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target_name)))


if __name__ == '__main__':
    import unittest
    unittest.main()
