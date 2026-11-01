from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from capture_probe import Archive, run_turn


class CaptureProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'archive.sqlite'
        self.archive = Archive(self.path)
        self.addCleanup(self.archive.close)

    def test_commit_before_invocation_and_delivery_then_idempotent_replay(self):
        events = [
            {'kind': 'tool_call', 'id': 'tool-1', 'arguments': {'example': True}},
            {'kind': 'tool_result', 'id': 'tool-1', 'result': 'synthetic'},
            {'kind': 'assistant_chunk', 'content': 'Example reply'},
            {'kind': 'complete'},
        ]
        delivered = []

        def source():
            with sqlite3.connect(self.path) as reader:
                self.assertEqual(reader.execute('SELECT prompt FROM turns').fetchone()[0], 'Example')
            return iter(events)

        def deliver(event):
            reader = Archive(self.path)
            try:
                self.assertIn(event, reader.replay('turn-1'))
            finally:
                reader.close()
            delivered.append(event)

        run_turn(self.archive, 'turn-1', 'Example', source, deliver)
        run_turn(self.archive, 'turn-1', 'Example',
                 lambda: self.fail('Retry must not invoke the source'), delivered.append)
        self.assertEqual(delivered, events + events)
        self.assertEqual(len(self.archive.replay('turn-1')), 5)
        self.assertEqual(self.archive.status('turn-1'), 'complete')
        with self.assertRaisesRegex(ValueError, 'different content'):
            run_turn(self.archive, 'turn-1', 'Edited', source, deliver)

    def test_old_local_archive_remains_readable_after_parent_column_upgrade(self):
        path = Path(self.directory.name) / 'previous.sqlite'
        with sqlite3.connect(path) as old:
            old.execute("CREATE TABLE turns (id TEXT PRIMARY KEY, prompt TEXT NOT NULL, status TEXT NOT NULL)")
            old.execute("INSERT INTO turns VALUES ('old', 'Original', 'complete')")
            old.execute("CREATE TABLE events (turn_id TEXT, sequence INTEGER, payload TEXT, PRIMARY KEY(turn_id, sequence))")
            old.execute("INSERT INTO events VALUES ('old', 0, '{\"kind\":\"user\",\"content\":\"Original\"}')")
        upgraded = Archive(path)
        try:
            self.assertEqual(upgraded.replay('old'), [{'kind': 'user', 'content': 'Original'}])
            self.assertEqual(upgraded.ancestry('old'), ['old'])
            self.assertFalse(upgraded.begin('old', 'Original'))
        finally:
            upgraded.close()

    def test_storage_failure_before_invocation(self):
        self.archive.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):
            run_turn(self.archive, 'turn-1', 'Example',
                     lambda: self.fail('Must not invoke before commit'), lambda event: None)
        self.assertEqual(self.archive.replay('turn-1'), [])

    def test_storage_failure_midstream_does_not_deliver_uncommitted_chunk(self):
        delivered = []

        def source():
            yield {'kind': 'assistant_chunk', 'content': 'Saved'}
            self.archive.db.execute('PRAGMA query_only=ON')
            yield {'kind': 'assistant_chunk', 'content': 'Not saved'}

        with self.assertRaises(sqlite3.OperationalError):
            run_turn(self.archive, 'turn-1', 'Example', source, delivered.append)
        self.assertEqual(delivered, [{'kind': 'assistant_chunk', 'content': 'Saved'}])
        self.assertEqual(self.archive.status('turn-1'), 'open')
        self.archive.db.execute('PRAGMA query_only=OFF')
        self.archive.recover()
        self.assertEqual(self.archive.status('turn-1'), 'interrupted')

    def test_missing_terminal_event_is_interrupted_not_complete(self):
        run_turn(self.archive, 'turn-1', 'Example',
                 lambda: iter([{'kind': 'assistant_chunk', 'content': 'Partial'}]), lambda event: None)
        self.assertEqual(self.archive.status('turn-1'), 'interrupted')

    def test_process_kill_preserves_delivered_prefix_and_recovery_never_reruns(self):
        script = '''
import sys, time
from capture_probe import Archive, run_turn
archive = Archive(sys.argv[1])
def source():
    yield {'kind': 'assistant_chunk', 'content': 'Durable prefix'}
    time.sleep(60)
    yield {'kind': 'complete'}
def deliver(event):
    print('delivered', flush=True)
run_turn(archive, 'crashed', 'Synthetic prompt', source, deliver)
'''
        process = subprocess.Popen(
            [sys.executable, '-c', script, str(self.path)],
            cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            import select
            self.assertTrue(select.select([process.stdout], [], [], 10)[0], 'Child failed to deliver')
            self.assertEqual(process.stdout.readline().strip(), 'delivered')
            process.kill()
            process.wait(timeout=5)
            self.archive.recover()
            self.assertEqual(self.archive.status('crashed'), 'interrupted')
            self.assertEqual(self.archive.replay('crashed')[1]['content'], 'Durable prefix')
            run_turn(self.archive, 'crashed', 'Synthetic prompt',
                     lambda: self.fail('Restart must not rerun source'), lambda event: None)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()


if __name__ == '__main__':
    unittest.main()
