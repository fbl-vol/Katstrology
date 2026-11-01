"""Single-owner PostgreSQL conversation archive and authenticated resource boundary.

CLI authentication is password-based and local only. Direct Python execution with
DB/file access is trusted code, not a production identity or sandbox boundary.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import psycopg
from psycopg.rows import dict_row

from m2.app_clock import reporting_zone as checked_reporting_zone, snapshot


ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
EVENT_KINDS = {'assistant_chunk', 'tool_call', 'tool_result', 'context',
               'compaction', 'usage', 'complete', 'interrupted', 'error'}
TERMINAL = {'complete', 'interrupted', 'error'}
MAX_MESSAGE = 4096
MAX_EVENT_BYTES = 16384
# Four bounded source matches can carry more UTF-8 metadata than their concise
# model projection. Keep exact read results; all other event kinds stay at 16 KiB.
MAX_TOOL_RESULT_BYTES = 64 * 1024
MAX_ANCESTORS = 2000
UNCHANGED = object()


@dataclass(frozen=True)
class Session:
    owner_id: str


class Store:
    def __init__(self, dsn, files, ledger):
        if ledger is None:
            raise ValueError('Independent deletion journal required')
        self._dsn = dsn  # used only for owned local pg_dump; never log it
        self.db = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self.files = Path(files)
        self.files.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sessions = {}
        self._blocked = False
        self.password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
        # Acquire exclusive ownership BEFORE migrations or startup recovery.
        # Separate read-only connections may inspect committed state.
        try:
            locked = self.db.execute(
                'SELECT pg_try_advisory_lock(hashtext(current_database()), 20261028) AS acquired'
            ).fetchone()['acquired']
            if not locked:
                raise RuntimeError('Conversation owner already active')
            self._migrate()
            self.ledger = ledger
            ledger.reconcile(self)
            from m2.title_work import TitleWork
            TitleWork(self).recover_interrupted()
        except BaseException:
            self.close()
            raise

    def _migrate(self):
        self.db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY)')
        migrations = sorted((Path(__file__).parent / 'migrations').glob('[0-9]*.sql'))
        for path in migrations:
            number = int(path.name.split('_')[0])
            with self.db.transaction():
                if not self.db.execute('SELECT 1 FROM schema_migrations WHERE version=%s', (number,)).fetchone():
                    self.db.execute(path.read_text(), prepare=False)
                    self.db.execute('INSERT INTO schema_migrations VALUES (%s)', (number,))

    def close(self):
        self.sessions.clear()
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError('Invalid identifier')
        return value

    @staticmethod
    def _text(value, limit=MAX_MESSAGE):
        if not isinstance(value, str) or not value or len(value.encode('utf-8')) > limit:
            raise ValueError('Invalid or oversized text')
        return value

    def register_local(self, owner_id, password):
        """Local workstation enrollment, not an unauthenticated network endpoint."""
        self._id(owner_id)
        self._text(password, 1024)
        if len(password) < 12:
            raise ValueError('Password too short')
        hashed = self.password_hasher.hash(password)
        self.db.execute('INSERT INTO accounts VALUES (%s, %s)', (owner_id, hashed))

    def authenticate(self, owner_id, password):
        row = self.db.execute('SELECT password_hash FROM accounts WHERE id=%s', (owner_id,)).fetchone()
        if row:
            try:
                if self.password_hasher.verify(row['password_hash'], password):
                    session = Session(owner_id)
                    self.sessions[id(session)] = session
                    return session
            except VerifyMismatchError:
                pass
        raise PermissionError('Invalid credentials')

    def owner(self, session):
        if self._blocked:
            raise RuntimeError('Deletion reconciliation required before serving')
        if session is None or self.sessions.get(id(session)) is not session:
            raise PermissionError('Authentication required')
        return session.owner_id

    def _conversation(self, owner, conv_id, lock=False):
        query = 'SELECT * FROM conversations WHERE owner_id=%s AND id=%s'
        if lock:
            query += ' FOR UPDATE'
        row = self.db.execute(query, (owner, self._id(conv_id))).fetchone()
        if not row:
            raise KeyError('Conversation not found')
        return row

    def create_conversation(self, session, conv_id):
        owner = self.owner(session)
        self._id(conv_id)
        if self.ledger.contains(owner, conv_id):
            raise ValueError('Deleted conversation identity cannot be reused')
        self.db.execute('INSERT INTO conversations(owner_id, id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
                        (owner, conv_id))
        return self._conversation(owner, conv_id)

    def list_conversations(self, session, limit=20):
        owner = self.owner(session)
        if not 1 <= limit <= 20:
            raise ValueError('Conversation list limit 1..20')
        return self.db.execute('''
            SELECT id, created_at, active_head FROM conversations
            WHERE owner_id=%s ORDER BY created_at DESC, id DESC LIMIT %s
        ''', (owner, limit)).fetchall()

    def active_head(self, session, conv_id):
        return self._conversation(self.owner(session), conv_id)['active_head']

    def begin(self, session, conv_id, turn_id, prompt, parent_id=None,
              source='gateway', attachment_ids=(), revision_kind='normal', replaces_turn_id=None,
              selected_people=(), model_provider='local', model_slug=None, chart_file=None,
              clock=None, reporting_zone=None):
        owner = self.owner(session)
        zone, _ = checked_reporting_zone(reporting_zone)
        self._id(turn_id)
        self._text(prompt)
        if parent_id is not None:
            self._id(parent_id)
        if source != 'gateway' or len(attachment_ids) > 8:
            raise ValueError('Unsupported source or attachment count')
        if model_provider not in ('local', 'chatgpt_plan') or (model_provider == 'local' and model_slug is not None) or (model_provider == 'chatgpt_plan' and (not isinstance(model_slug, str) or len(model_slug) > 80)):
            raise ValueError('Unsupported model source')
        if revision_kind not in ('normal', 'edit', 'regenerate'):
            raise ValueError('Unsupported revision kind')
        if revision_kind == 'normal' and replaces_turn_id is not None:
            raise ValueError('Normal turn cannot replace a revision')
        if revision_kind != 'normal':
            self._id(replaces_turn_id)
        attachment_ids = list(attachment_ids)
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError('Duplicate attachment reference')
        for item in attachment_ids:
            self._id(item)
        if not isinstance(selected_people, (tuple, list)) or len(selected_people) > 8:
            raise ValueError('Select up to eight people')
        selection = []
        for item in selected_people:
            if not isinstance(item, dict) or set(item) != {'person_id', 'chart_id'}:
                raise ValueError('Invalid selected person/chart version')
            person_id, chart_id = self._id(item['person_id']), item['chart_id']
            if chart_id is not None:
                self._id(chart_id)
            selection.append((person_id, chart_id))
        if len({person_id for person_id, _ in selection}) != len(selection):
            raise ValueError('Duplicate person in turn selection')
        selection.sort()
        if chart_file is not None:
            if (not isinstance(chart_file, dict) or set(chart_file) !=
                    {'person_id', 'attachment_id', 'consent'} or chart_file['consent'] is not True):
                raise ValueError('Explicit per-turn file consent required')
            file_person = self._id(chart_file['person_id'])
            file_id = self._id(chart_file['attachment_id'])
            if file_person not in {person_id for person_id, _ in selection}:
                raise ValueError('File person must be selected for this turn')
            if model_provider != 'chatgpt_plan':
                raise ValueError('Local model cannot view uploaded chart files')
        else:
            file_person = file_id = None
        with self.db.transaction():
            self._conversation(owner, conv_id, lock=True)
            existing = self.db.execute('''
                SELECT prompt, parent_id, source, revision_kind, replaces_turn_id FROM turns
                WHERE owner_id=%s AND conversation_id=%s AND id=%s
            ''', (owner, conv_id, turn_id)).fetchone()
            if existing:
                old = self.db.execute('''
                    SELECT payload->'attachments' AS attachments,
                           COALESCE(payload->>'model_provider', 'local') AS model_provider,
                           payload->>'model_slug' AS model_slug,
                           payload->'chart_file' AS chart_file,
                           payload->'clock_anchor' AS clock_anchor FROM events
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND sequence=0
                ''', (owner, conv_id, turn_id)).fetchone()
                expected = {'prompt': prompt, 'parent_id': parent_id, 'source': source,
                            'revision_kind': revision_kind, 'replaces_turn_id': replaces_turn_id}
                recorded = self.db.execute('''
                    SELECT person_id,chart_id,attachment_id FROM turn_people
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
                    ORDER BY person_id
                ''', (owner, conv_id, turn_id)).fetchall()
                if (existing != expected or old['attachments'] != attachment_ids or
                        old['model_provider'] != model_provider or old['model_slug'] != model_slug or
                        old['chart_file'] != chart_file or
                        (old['clock_anchor'] is not None and
                         old['clock_anchor']['reporting']['zone'] != zone.key) or
                        [(row['person_id'], row['chart_id']) for row in recorded] != selection or
                        any(row['attachment_id'] != (file_id if row['person_id'] == file_person else None)
                            for row in recorded)):
                    raise ValueError('Turn ID reused with changed input, ancestry or people')
                return False
            for item in attachment_ids:
                if not self.db.execute('''
                    SELECT 1 FROM attachments WHERE owner_id=%s AND conversation_id=%s AND id=%s
                ''', (owner, conv_id, item)).fetchone():
                    raise ValueError('Attachment reference not found')
            parent_revision = 0
            if parent_id:
                parent = self.db.execute('''
                    SELECT t.status, (SELECT COALESCE(MAX(c.sequence), 0) FROM corrections c
                      WHERE c.owner_id=t.owner_id AND c.conversation_id=t.conversation_id
                        AND c.source_turn_id=t.id) AS revision
                    FROM turns t WHERE t.owner_id=%s AND t.conversation_id=%s AND t.id=%s
                ''', (owner, conv_id, parent_id)).fetchone()
                if not parent or parent['status'] != 'complete':
                    raise ValueError('Parent must be a complete turn in this conversation')
                parent_revision = parent['revision']
            if replaces_turn_id:
                replaced = self.db.execute('''
                    SELECT parent_id, prompt, status FROM turns
                    WHERE owner_id=%s AND conversation_id=%s AND id=%s
                ''', (owner, conv_id, replaces_turn_id)).fetchone()
                if (not replaced or replaced['status'] != 'complete'
                        or replaced['parent_id'] != parent_id):
                    raise ValueError('Replacement must target a complete sibling revision')
                if revision_kind == 'regenerate' and replaced['prompt'] != prompt:
                    raise ValueError('Regeneration must reuse its source user input')
            clock_anchor = snapshot(clock, reporting_zone) if clock is not None else None
            self.db.execute('''
                INSERT INTO turns(owner_id, conversation_id, id, parent_id, prompt, source, status,
                                  revision_kind, replaces_turn_id, parent_revision)
                VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s, %s)
            ''', (owner, conv_id, turn_id, parent_id, prompt, source,
                  revision_kind, replaces_turn_id, parent_revision))
            self.db.execute('''
                INSERT INTO events(owner_id, conversation_id, turn_id, sequence, kind, payload)
                VALUES (%s, %s, %s, 0, 'user', %s)
            ''', (owner, conv_id, turn_id, psycopg.types.json.Jsonb({'content': prompt, 'source': source,
                                                   'attachments': attachment_ids,
                                                   'model_provider': model_provider,
                                                   'model_slug': model_slug,
                                                   'chart_file': chart_file,
                                                   'clock_anchor': clock_anchor,
                                                   'revision_kind': revision_kind,
                                                   'replaces_turn_id': replaces_turn_id})))
            for person_id, chart_id in selection:
                person = self.db.execute('''
                    SELECT 1 FROM people WHERE owner_id=%s AND id=%s
                ''', (owner, person_id)).fetchone()
                if not person:
                    raise KeyError('Selected person not found')
                draft = self.db.execute('''
                    SELECT MAX(revision) AS revision FROM person_drafts
                    WHERE owner_id=%s AND person_id=%s
                ''', (owner, person_id)).fetchone()['revision']
                chart = None
                if chart_id:
                    chart = self.db.execute('''
                        SELECT birth_id,profile_id,profile_revision FROM charts
                        WHERE owner_id=%s AND person_id=%s AND id=%s
                    ''', (owner, person_id, chart_id)).fetchone()
                    if not chart:
                        raise KeyError('Selected chart does not belong to person')
                    from m2.charts import Charts
                    if Charts(self).get_chart(session, chart_id)['source_status'] != 'current':
                        raise ValueError('Selected chart source is superseded')
                if person_id == file_person and not self.db.execute('''
                    SELECT 1 FROM person_attachments
                    WHERE owner_id=%s AND person_id=%s AND id=%s
                ''', (owner, person_id, file_id)).fetchone():
                    raise KeyError('Selected file does not belong to person')
                self.db.execute('''
                    INSERT INTO turn_people(owner_id,conversation_id,turn_id,person_id,
                                            draft_revision,chart_id,birth_id,profile_id,profile_revision,
                                            attachment_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (owner, conv_id, turn_id, person_id, draft, chart_id,
                      chart['birth_id'] if chart else None,
                      chart['profile_id'] if chart else None,
                      chart['profile_revision'] if chart else None,
                      file_id if person_id == file_person else None))
                self.db.execute('''
                    INSERT INTO conversation_people(owner_id,conversation_id,person_id)
                    VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
                ''', (owner, conv_id, person_id))
        return True

    def append(self, session, conv_id, turn_id, kind, payload):
        owner = self.owner(session)
        self._id(turn_id)
        limit = MAX_TOOL_RESULT_BYTES if kind == 'tool_result' else MAX_EVENT_BYTES
        if kind not in EVENT_KINDS or len(str(payload).encode('utf-8')) > limit:
            raise ValueError('Unsupported or oversized event')
        with self.db.transaction():
            turn = self.db.execute('''
                SELECT status FROM turns WHERE owner_id=%s AND conversation_id=%s AND id=%s FOR UPDATE
            ''', (owner, conv_id, turn_id)).fetchone()
            if not turn or turn['status'] != 'open':
                raise ValueError('Only an open owned turn accepts events')
            next_sequence = self.db.execute('''
                SELECT COALESCE(MAX(sequence), -1)+1 AS value FROM events
                WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
            ''', (owner, conv_id, turn_id)).fetchone()['value']
            self.db.execute('''
                INSERT INTO events(owner_id, conversation_id, turn_id, sequence, kind, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (owner, conv_id, turn_id, next_sequence, kind,
                  psycopg.types.json.Jsonb(payload)))
            if kind == 'tool_result' and isinstance(payload, dict) and 'chart_id' in payload:
                chart_id = self._id(payload['chart_id'])
                if not self.db.execute('''
                    SELECT 1 FROM charts WHERE owner_id=%s AND id=%s
                ''', (owner, chart_id)).fetchone():
                    raise KeyError('Referenced chart not found')
                self.db.execute('''
                    INSERT INTO chart_evidence(owner_id,conversation_id,turn_id,chart_id,event_sequence)
                    VALUES (%s,%s,%s,%s,%s)
                ''', (owner, conv_id, turn_id, chart_id, next_sequence))
            if (kind == 'tool_result' and isinstance(payload, dict) and
                    payload.get('name') == 'compare_selected_charts' and
                    isinstance(payload.get('result'), dict) and
                    'chart_a_id' in payload['result'] and 'chart_b_id' in payload['result']):
                for chart_id in (payload['result']['chart_a_id'],
                                 payload['result']['chart_b_id']):
                    chart_id = self._id(chart_id)
                    if not self.db.execute('''
                        SELECT 1 FROM charts WHERE owner_id=%s AND id=%s
                    ''', (owner, chart_id)).fetchone():
                        raise KeyError('Referenced chart not found')
                    self.db.execute('''
                        INSERT INTO chart_evidence(owner_id,conversation_id,turn_id,chart_id,event_sequence)
                        VALUES (%s,%s,%s,%s,%s)
                    ''', (owner, conv_id, turn_id, chart_id, next_sequence))
            if kind == 'tool_result' and isinstance(payload, dict):
                for item in payload.get('results', []):
                    if item.get('kind') == 'reference_passage':
                        self.db.execute('''
                            INSERT INTO reference_evidence(owner_id,conversation_id,turn_id,
                                                           event_sequence,source_id,passage_id)
                            VALUES (%s,%s,%s,%s,%s,%s)
                        ''', (owner, conv_id, turn_id, next_sequence,
                              self._id(item['source_id']), self._id(item['passage_id'])))
            if kind in TERMINAL:
                self.db.execute('''
                    UPDATE turns SET status=%s WHERE owner_id=%s AND conversation_id=%s AND id=%s
                ''', (kind, owner, conv_id, turn_id))
                if kind == 'complete':
                    self._changed(owner, conv_id, turn_id, invalidate_compaction=False)
        return next_sequence

    def _changed(self, owner, conv_id, active_head=UNCHANGED, invalidate_dependents=True,
                 invalidate_compaction=True):
        """Call inside the write transaction; old derivatives cannot pass epoch checks."""
        revision = int(invalidate_compaction)
        if active_head is UNCHANGED:
            row = self.db.execute('''
                UPDATE conversations SET epoch=epoch+1,
                    compaction_revision=compaction_revision+%s
                WHERE owner_id=%s AND id=%s RETURNING epoch
            ''', (revision, owner, conv_id)).fetchone()
        else:
            row = self.db.execute('''
                UPDATE conversations SET epoch=epoch+1, active_head=%s,
                    compaction_revision=compaction_revision+%s
                WHERE owner_id=%s AND id=%s RETURNING epoch
            ''', (active_head, revision, owner, conv_id)).fetchone()
        epoch = row['epoch']
        self.db.execute('DELETE FROM summaries WHERE owner_id=%s AND conversation_id=%s', (owner, conv_id))
        self.db.execute('DELETE FROM history_vectors WHERE owner_id=%s AND conversation_id=%s',
                        (owner, conv_id))
        self.db.execute('''
            DELETE FROM reference_vectors WHERE owner_id=%s AND source_id IN
              (SELECT id FROM reference_sources WHERE owner_id=%s AND source_conversation_id=%s)
        ''', (owner, owner, conv_id))
        self.db.execute('''
            INSERT INTO rebuild_queue VALUES (%s, %s, %s)
            ON CONFLICT (owner_id, conversation_id) DO UPDATE SET epoch=EXCLUDED.epoch
        ''', (owner, conv_id, epoch))
        if invalidate_dependents:
            # A dependent conversation may itself source evidence used elsewhere.
            # Invalidate the whole reachable set once in this transaction; cycles
            # cannot repeatedly bump epochs or leave a partially updated graph.
            seen, frontier = {conv_id}, [conv_id]
            while frontier:
                source = frontier.pop()
                linked = self.db.execute('''
                    SELECT DISTINCT e.conversation_id AS id FROM chart_evidence e
                    JOIN charts c ON (c.owner_id=e.owner_id AND c.id=e.chart_id)
                    JOIN birth_records b ON (b.owner_id=c.owner_id AND b.person_id=c.person_id
                                             AND b.id=c.birth_id)
                    WHERE e.owner_id=%s AND b.source_conversation_id=%s
                    UNION
                    SELECT DISTINCT e.conversation_id AS id FROM reference_evidence e
                    JOIN reference_sources s ON (s.owner_id=e.owner_id AND s.id=e.source_id)
                    WHERE e.owner_id=%s AND s.source_conversation_id=%s
                ''', (owner, source, owner, source)).fetchall()
                for item in linked:
                    if item['id'] not in seen:
                        if len(seen) >= MAX_ANCESTORS:
                            raise ValueError('Dependent conversation limit exceeded')
                        seen.add(item['id'])
                        self._changed(owner, item['id'], invalidate_dependents=False)
                        frontier.append(item['id'])

    def read_turns(self, session, conv_id, turn_ids, event_limit=256):
        """Read up to 20 owned turns in a fixed number of archive queries."""
        owner = self.owner(session)
        self._conversation(owner, conv_id)
        if not 1 <= len(turn_ids) <= 20 or not 1 <= event_limit <= 256:
            raise ValueError('Turn batch must contain 1..20 IDs and event limit 1..256')
        ids = [self._id(turn_id) for turn_id in turn_ids]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate turn in batch')
        rows = self.db.execute('''
            SELECT id, parent_id, parent_revision, status, source, revision_kind,
                   replaces_turn_id, created_at FROM turns
            WHERE owner_id=%s AND conversation_id=%s AND id=ANY(%s::text[])
        ''', (owner, conv_id, ids)).fetchall()
        if len(rows) != len(ids):
            raise KeyError('Turn not found')
        by_id = {row['id']: row for row in self._read_turns(owner, conv_id, rows, event_limit)}
        return [by_id[turn_id] for turn_id in ids]

    def _read_turns(self, owner, conv_id, rows, event_limit):
        if not rows:
            return []
        ids = [row['id'] for row in rows]
        scope = (owner, conv_id, ids)
        counts = self.db.execute('''
            SELECT turn_id, COUNT(*) AS count FROM events
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=ANY(%s::text[])
            GROUP BY turn_id
        ''', scope).fetchall()
        event_counts = {row['turn_id']: row['count'] for row in counts}
        events = self.db.execute('''
            SELECT turn_id, sequence, kind, payload, stored_at FROM (
                SELECT turn_id, sequence, kind, payload, stored_at,
                       row_number() OVER (PARTITION BY turn_id ORDER BY sequence) AS page_row
                FROM events WHERE owner_id=%s AND conversation_id=%s
                  AND turn_id=ANY(%s::text[])
            ) numbered WHERE page_row <= %s ORDER BY turn_id, sequence
        ''', (*scope, event_limit)).fetchall()
        selected = self.db.execute('''
            SELECT turn_id, person_id, draft_revision, chart_id, birth_id,
                   profile_id, profile_revision, attachment_id FROM turn_people
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=ANY(%s::text[])
            ORDER BY turn_id, person_id
        ''', scope).fetchall()
        corrections = self.db.execute('''
            SELECT source_turn_id, id, action, replacement, created_at, sequence, parent_revision
            FROM corrections WHERE owner_id=%s AND conversation_id=%s
              AND source_turn_id=ANY(%s::text[])
            ORDER BY source_turn_id, sequence
        ''', scope).fetchall()
        by_id = {row['id']: row for row in rows}
        for row in rows:
            count = event_counts.get(row['id'], 0)
            row.update(event_count=count, events=[], selected_people=[], corrections=[],
                       next_event_offset=event_limit if count > event_limit else None)
        for event in events:
            by_id[event['turn_id']]['events'].append({key: value for key, value in event.items()
                                                      if key != 'turn_id'})
        for person in selected:
            by_id[person['turn_id']]['selected_people'].append({key: value for key, value in person.items()
                                                                if key != 'turn_id'})
        for correction in corrections:
            by_id[correction['source_turn_id']]['corrections'].append({key: value for key, value in correction.items()
                                                                       if key != 'source_turn_id'})
        return rows

    def read_turn(self, session, conv_id, turn_id, event_offset=0, event_limit=256):
        owner = self.owner(session)
        self._conversation(owner, conv_id)
        row = self.db.execute('''
            SELECT id, parent_id, parent_revision, status, source, revision_kind, replaces_turn_id,
                   created_at FROM turns
            WHERE owner_id=%s AND conversation_id=%s AND id=%s
        ''', (owner, conv_id, self._id(turn_id))).fetchone()
        if not row:
            raise KeyError('Turn not found')
        if not 0 <= event_offset or not 1 <= event_limit <= 256:
            raise ValueError('Event page must have nonnegative offset and limit 1..256')
        row['event_count'] = self.db.execute('''
            SELECT count(*) AS value FROM events
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
        ''', (owner, conv_id, turn_id)).fetchone()['value']
        row['events'] = self.db.execute('''
            SELECT sequence, kind, payload, stored_at FROM events
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
            ORDER BY sequence LIMIT %s OFFSET %s
        ''', (owner, conv_id, turn_id, event_limit, event_offset)).fetchall()
        row['next_event_offset'] = (event_offset + len(row['events'])
                                    if event_offset + len(row['events']) < row['event_count'] else None)
        row['selected_people'] = self.db.execute('''
            SELECT person_id,draft_revision,chart_id,birth_id,profile_id,profile_revision,attachment_id
            FROM turn_people WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
            ORDER BY person_id
        ''', (owner, conv_id, turn_id)).fetchall()
        row['corrections'] = self.db.execute('''
            SELECT id, action, replacement, created_at, sequence, parent_revision FROM corrections
            WHERE owner_id=%s AND conversation_id=%s AND source_turn_id=%s ORDER BY sequence
        ''', (owner, conv_id, turn_id)).fetchall()
        return row

    def read_event(self, session, conv_id, turn_id, sequence):
        owner = self.owner(session)
        row = self.db.execute('''
            SELECT sequence, kind, payload, stored_at FROM events
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s AND sequence=%s
        ''', (owner, self._id(conv_id), self._id(turn_id), sequence)).fetchone()
        if not row:
            raise KeyError('Event not found')
        return row

    def ancestry(self, session, conv_id, head_id):
        owner = self.owner(session)
        self._conversation(owner, conv_id)
        if not head_id:
            return []
        rows = self.db.execute('''
            WITH RECURSIVE ancestors AS (
                SELECT id, parent_id, status, 1 AS depth, ARRAY[id] AS visited, false AS cycle
                FROM turns WHERE owner_id=%s AND conversation_id=%s AND id=%s
                UNION ALL
                SELECT parent.id, parent.parent_id, parent.status, child.depth + 1,
                       child.visited || parent.id, parent.id = ANY(child.visited)
                FROM ancestors child JOIN turns parent
                  ON parent.owner_id=%s AND parent.conversation_id=%s AND parent.id=child.parent_id
                WHERE NOT child.cycle AND child.depth <= %s
            )
            SELECT id, parent_id, status, cycle FROM ancestors ORDER BY depth
        ''', (owner, conv_id, self._id(head_id), owner, conv_id, MAX_ANCESTORS)).fetchall()
        if any(row['cycle'] for row in rows) or len(rows) > MAX_ANCESTORS:
            raise ValueError('Unsupported ancestry depth or cycle')
        if not rows or rows[-1]['parent_id'] is not None or any(
                row['status'] != 'complete' for row in rows):
            raise ValueError('Incomplete or absent ancestor')
        return [row['id'] for row in reversed(rows)]

    def recover_open(self):
        """Exclusive owner startup; never rerun any generator or tool."""
        rows = self.db.execute("SELECT owner_id, conversation_id, id FROM turns WHERE status='open'").fetchall()
        for row in rows:
            with self.db.transaction():
                seq = self.db.execute('''
                    SELECT COALESCE(MAX(sequence), -1)+1 AS value FROM events
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s
                ''', (row['owner_id'], row['conversation_id'], row['id'])).fetchone()['value']
                self.db.execute('''
                    INSERT INTO events(owner_id, conversation_id, turn_id, sequence, kind, payload)
                    VALUES (%s, %s, %s, %s, 'interrupted', '{"reason":"owner restarted"}'::jsonb)
                ''', (row['owner_id'], row['conversation_id'], row['id'], seq))
                self.db.execute('''
                    UPDATE turns SET status='interrupted'
                    WHERE owner_id=%s AND conversation_id=%s AND id=%s AND status='open'
                ''', (row['owner_id'], row['conversation_id'], row['id']))
        return len(rows)
