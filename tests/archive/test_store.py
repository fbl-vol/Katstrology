import json
from pathlib import Path
import unittest

import psycopg

from m2.archive.attachments import Attachments
from tests.support.database import DatabaseCase
from m2.archive.store import Store


class ArchiveTests(DatabaseCase):
    fixture_requires_fresh_migration = True  # Enrollment and lock/restart behavior stay on the original path.
    def test_authenticated_colliding_ids_and_committed_event_order(self):
        with self.assertRaises(PermissionError):
            self.store.authenticate('alice', 'wrong password')
        with self.assertRaises(PermissionError):
            self.store.create_conversation(None, 'same')
        self.store.create_conversation(self.alice, 'same')
        self.store.create_conversation(self.bob, 'same')
        for session, word in ((self.alice, 'Alice content'), (self.bob, 'Bob content')):
            def check_committed():
                with psycopg.connect(self.dsn) as reader:
                    row = reader.execute('''
                        SELECT payload->>'content' FROM events
                        WHERE owner_id=%s AND conversation_id='same' AND turn_id='turn' AND sequence=0
                    ''', (session.owner_id,)).fetchone()
                    self.assertEqual(row[0], word)
            self.assertTrue(self.store.begin(session, 'same', 'turn', word))
            check_committed()  # the point where inference is permitted to start
            self.store.append(session, 'same', 'turn', 'tool_call', {'id': 'call', 'name': 'synthetic'})
            self.store.append(session, 'same', 'turn', 'tool_result', {'id': 'call', 'result': word})
            self.store.append(session, 'same', 'turn', 'assistant_chunk', {'content': word})
            self.store.append(session, 'same', 'turn', 'complete', {})
            self.assertFalse(self.store.begin(session, 'same', 'turn', word))
            self.assertEqual(self.store.active_head(session, 'same'), 'turn')
            events = self.store.read_turn(session, 'same', 'turn')['events']
            self.assertEqual([e['sequence'] for e in events], list(range(5)))
            self.assertTrue(all(e['stored_at'].tzinfo for e in events))
            self.assertEqual(events[0]['payload']['content'], word)
        self.assertEqual(self.store.read_turn(self.alice, 'same', 'turn')['events'][3]['payload']['content'],
                         'Alice content')
        self.assertEqual(self.store.read_turn(self.bob, 'same', 'turn')['events'][3]['payload']['content'],
                         'Bob content')
        with self.assertRaises(KeyError):
            self.store.read_turn(self.bob, 'missing', 'turn')
        with self.assertRaises(ValueError):
            self.store.begin(self.alice, 'same', 'turn', 'Changed')

    def test_incomplete_recovery_does_not_reexecute_and_branches_are_distinct(self):
        self.store.create_conversation(self.alice, 'story')
        self.store.begin(self.alice, 'story', 'root', 'Original')
        self.store.append(self.alice, 'story', 'root', 'assistant_chunk', {'content': 'first'})
        self.store.append(self.alice, 'story', 'root', 'complete', {})
        self.store.begin(self.alice, 'story', 'old', 'Abandoned', 'root')
        self.store.append(self.alice, 'story', 'old', 'complete', {})
        self.store.begin(self.alice, 'story', 'edit', 'Selected edit', 'root',
                         revision_kind='edit', replaces_turn_id='old')
        self.store.append(self.alice, 'story', 'edit', 'complete', {})
        self.store.begin(self.alice, 'story', 'regen', 'Selected edit', 'root',
                         revision_kind='regenerate', replaces_turn_id='edit')
        self.store.append(self.alice, 'story', 'regen', 'complete', {})
        self.assertEqual(self.store.ancestry(self.alice, 'story', 'regen'), ['root', 'regen'])
        self.assertEqual(self.store.read_turn(self.alice, 'story', 'regen')['replaces_turn_id'], 'edit')
        self.assertEqual(self.store.read_turn(self.alice, 'story', 'edit')['revision_kind'], 'edit')
        with self.assertRaisesRegex(ValueError, 'reuse its source user input'):
            self.store.begin(self.alice, 'story', 'bad-regen', 'Changed', 'root',
                             revision_kind='regenerate', replaces_turn_id='edit')
        self.assertEqual(self.store.ancestry(self.alice, 'story', 'edit'), ['root', 'edit'])
        self.assertEqual(self.store.read_turn(self.alice, 'story', 'old')['status'], 'complete')
        self.assertEqual(self.store.active_head(self.alice, 'story'), 'regen')
        with self.assertRaises(ValueError):
            self.store.begin(self.alice, 'story', 'edit', 'Selected edit', 'old',
                             revision_kind='edit', replaces_turn_id='old')
        self.store.begin(self.alice, 'story', 'partial', 'Unfinished', 'edit')
        self.store.append(self.alice, 'story', 'partial', 'assistant_chunk', {'content': 'durable partial'})
        self.store.close()
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.assertEqual(self.store.recover_open(), 1)
        self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
        self.assertEqual(self.store.read_turn(self.alice, 'story', 'partial')['status'], 'interrupted')
        self.assertEqual(self.store.read_turn(self.alice, 'story', 'partial')['events'][1]['payload'],
                         {'content': 'durable partial'})
        self.assertFalse(self.store.begin(self.alice, 'story', 'partial', 'Unfinished', 'edit'))
        self.assertEqual(self.store.active_head(self.alice, 'story'), 'regen')

    def test_missing_referenced_file_prevents_apparently_complete_restart(self):
        self.store.create_conversation(self.alice, 'one')
        files = Attachments(self.store)
        content = b'synthetic bytes'
        digest = files.add(self.alice, 'one', 'file', 'synthetic.txt', content)
        self.store.close()
        path = Path(self.directory.name) / 'files' / 'blobs' / digest
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing or corrupt'):
            Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        path.write_bytes(content)
        self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
        self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
        self.assertEqual(Attachments(self.store).read(self.alice, 'one', 'file'), content)

    def test_owned_attachment_refs_and_cross_owner_denial(self):
        self.store.create_conversation(self.alice, 'one')
        self.store.create_conversation(self.alice, 'two')
        self.store.create_conversation(self.bob, 'one')
        files = Attachments(self.store)
        data = b'synthetic attachment only'
        digest = files.add(self.alice, 'one', 'same-id', 'synthetic.txt', data)
        self.assertEqual(files.add(self.alice, 'two', 'same-id', 'synthetic.txt', data), digest)
        files.add(self.bob, 'one', 'same-id', 'different.txt', b'other')
        self.assertEqual(files.read(self.alice, 'one', 'same-id'), data)
        self.assertEqual(files.read(self.bob, 'one', 'same-id'), b'other')
        with self.assertRaises(KeyError):
            files.read(self.bob, 'two', 'same-id')
        self.store.begin(self.alice, 'one', 'with-file', 'Read', attachment_ids=['same-id'])
        self.assertEqual(self.store.read_turn(self.alice, 'one', 'with-file')['events'][0]['payload']['attachments'],
                         ['same-id'])
        with self.assertRaises(ValueError):
            self.store.begin(self.bob, 'one', 'not-mine', 'Read', attachment_ids=['foreign-id'])
        with self.assertRaises(ValueError):
            self.store.begin(self.alice, 'one', 'with-file', 'Read', attachment_ids=[])
        with self.assertRaises(ValueError):
            files.add(self.alice, 'one', 'bad', '../unsafe', data)
        self.assertEqual(files.prune_unreferenced(), 0)


if __name__ == '__main__':
    unittest.main()
