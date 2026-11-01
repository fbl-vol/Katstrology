"""Single-owner local M1 capture experiment using SQLite and a scripted source.

Not a model adapter, HTTP server, production archive or PostgreSQL durability proof.
Events are committed before delivery. Reconnecting replays; it never re-executes.
"""

import json
import sqlite3


class Archive:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                parent_id TEXT REFERENCES turns(id),
                status TEXT NOT NULL CHECK(status IN ('open', 'complete', 'interrupted', 'error'))
            );
            CREATE TABLE IF NOT EXISTS events (
                turn_id TEXT NOT NULL REFERENCES turns(id),
                sequence INTEGER NOT NULL,
                payload TEXT NOT NULL,
                stored_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                PRIMARY KEY(turn_id, sequence)
            );
        ''')
        # Keep earlier local smoke archives readable when revisiting their evidence.
        if 'parent_id' not in {row[1] for row in self.db.execute('PRAGMA table_info(turns)')}:
            self.db.execute('ALTER TABLE turns ADD COLUMN parent_id TEXT REFERENCES turns(id)')

    def close(self):
        self.db.close()

    def begin(self, turn_id, prompt, parent_id=None):
        with self.db:
            previous = self.db.execute(
                'SELECT prompt, parent_id FROM turns WHERE id=?', (turn_id,)
            ).fetchone()
            if previous:
                if previous != (prompt, parent_id):
                    raise ValueError('Turn ID reused with different content or ancestry')
                return False
            if parent_id and self.db.execute(
                'SELECT status FROM turns WHERE id=?', (parent_id,)
            ).fetchone() != ('complete',):
                raise ValueError('Parent turn must be complete')
            self.db.execute("INSERT INTO turns VALUES (?, ?, ?, 'open')",
                            (turn_id, prompt, parent_id))
            self.db.execute('INSERT INTO events(turn_id, sequence, payload) VALUES (?, 0, ?)',
                            (turn_id, json.dumps({'kind': 'user', 'content': prompt})))
        return True

    def append(self, turn_id, event):
        kind = event['kind']
        if kind not in {'assistant_chunk', 'tool_call', 'tool_result', 'context', 'complete', 'interrupted', 'error'}:
            raise ValueError(f'Unsupported event kind: {kind}')
        terminal = kind in {'complete', 'interrupted', 'error'}
        with self.db:
            status = self.db.execute('SELECT status FROM turns WHERE id=?', (turn_id,)).fetchone()
            if status != ('open',):
                raise ValueError('Only an open turn can accept events')
            self.db.execute('''
                INSERT INTO events(turn_id, sequence, payload)
                SELECT ?, COALESCE(MAX(sequence), -1) + 1, ? FROM events WHERE turn_id=?
            ''', (turn_id, json.dumps(event), turn_id))
            if terminal:
                self.db.execute('UPDATE turns SET status=? WHERE id=?', (kind, turn_id))

    def replay(self, turn_id):
        return [json.loads(row[0]) for row in self.db.execute(
            'SELECT payload FROM events WHERE turn_id=? ORDER BY sequence', (turn_id,)
        )]

    def status(self, turn_id):
        return self.db.execute('SELECT status FROM turns WHERE id=?', (turn_id,)).fetchone()[0]

    def ancestry(self, parent_id):
        """Only the selected completed parent chain enters active continuity."""
        chain = []
        seen = set()
        while parent_id:
            if parent_id in seen:
                raise ValueError('Cyclic ancestry')
            seen.add(parent_id)
            row = self.db.execute(
                'SELECT parent_id, status FROM turns WHERE id=?', (parent_id,)
            ).fetchone()
            if not row or row[1] != 'complete':
                raise ValueError('Incomplete or missing ancestor')
            chain.append(parent_id)
            parent_id = row[0]
        return list(reversed(chain))

    def recover(self):
        # Only at startup with exclusive ownership; never race a live generator.
        ids = [row[0] for row in self.db.execute("SELECT id FROM turns WHERE status='open'")]
        for turn_id in ids:
            self.append(turn_id, {'kind': 'interrupted', 'reason': 'owner restarted'})


def run_turn(archive, turn_id, prompt, source, deliver, parent_id=None):
    if not archive.begin(turn_id, prompt, parent_id):
        for event in archive.replay(turn_id)[1:]:
            deliver(event)
        return

    # Factory invocation must occur AFTER begin() commits the user's message.
    # Any source/delivery/storage exception propagates. The durable open turn
    # remains visibly incomplete until exclusive-owner recovery; no fake success.
    stream = iter(source())
    try:
        for event in stream:
            archive.append(turn_id, event)
            deliver(event)
            if event['kind'] in {'complete', 'interrupted', 'error'}:
                return
        archive.append(turn_id, {'kind': 'interrupted', 'reason': 'source ended without completion'})
        deliver(archive.replay(turn_id)[-1])
    finally:
        if hasattr(stream, 'close'):
            stream.close()
