"""Bounded post-completion work references; all methods run on the owning Store.

A provider attempt is marked before leaving Store. Restart never retries an
ambiguous paid attempt. A later completed turn may supply genuinely newer work.
"""
from dataclasses import asdict

from psycopg.types.json import Jsonb

from m2.chat.personal_context import preference

MAX_BACKLOG = 64
MAX_OWNER_BACKLOG = 16
IDLE_SECONDS = 3
OWNER_INTERVAL_SECONDS = 300
GLOBAL_INTERVAL_SECONDS = 30


class MemoryWork:
    def __init__(self, store):
        self.store = store

    def enqueue(self, session, conversation_id, turn_id, initial, origin):
        """Called inside terminal commit; no history/directory/provider analysis."""
        if origin is None:
            return
        owner = self.store.owner(session)
        consent = initial.get('personal_context', {}).get('consent')
        if not consent or not consent['enabled'] or preference(self.store, session) != consent:
            return
        db = self.store.db
        old = db.execute('SELECT turn_id FROM memory_work WHERE owner_id=%s AND conversation_id=%s',
                         (owner, conversation_id)).fetchone()
        if old and old['turn_id'] == turn_id:
            return
        unit = db.execute('''SELECT id FROM memory_source_units
            WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s''',
            (owner, conversation_id, turn_id)).fetchone()
        if unit is None:
            return
        if not old:
            # Terminal receipts are not a permanent queue history. Original turns
            # and context action/source records remain the durable evidence.
            db.execute("DELETE FROM memory_work WHERE state='idle'")
            counts = db.execute('''SELECT count(*) AS total,
                count(*) FILTER (WHERE owner_id=%s) AS owned FROM memory_work''', (owner,)).fetchone()
            if counts['total'] >= MAX_BACKLOG or counts['owned'] >= MAX_OWNER_BACKLOG:
                return  # Backpressure drops optional freshness, never foreground work.
        db.execute('''INSERT INTO memory_work(owner_id,conversation_id,turn_id,
            consent_version,session_digest,account_binding,model_slug,capacity,pending_source_unit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(owner_id,conversation_id) DO UPDATE SET
              turn_id=excluded.turn_id,consent_version=excluded.consent_version,
              session_digest=excluded.session_digest,account_binding=excluded.account_binding,
              model_slug=excluded.model_slug,capacity=excluded.capacity,generation=memory_work.generation+1,
              pending_source_unit=CASE WHEN memory_work.state='idle' OR memory_work.pending_source_unit IS NULL
                THEN excluded.pending_source_unit ELSE memory_work.pending_source_unit END,
              state=CASE WHEN memory_work.state='running' THEN 'running' ELSE 'pending' END,
              queued_at=clock_timestamp()''',
            (owner, conversation_id, turn_id, consent['version'], origin['session_digest'],
             origin['admission'].binding, origin['admission'].slug,
             Jsonb(asdict(origin['admission'].capacity)), unit['id']))

    def recover_interrupted(self):
        self.store.db.execute('''UPDATE memory_work SET
            state=CASE WHEN generation>attempted_generation THEN 'pending' ELSE 'idle' END,
            outcome='abandoned' WHERE state='running' ''')

    def due(self):
        """At most one candidate; timer uses the returned delay, not busy polling."""
        return self.store.db.execute('''SELECT w.*,
            greatest(0,extract(epoch FROM (greatest(
                w.queued_at + make_interval(secs => %s),
                coalesce(b.next_attempt_at,w.queued_at),
                coalesce((SELECT max(next_attempt_at) FROM memory_budget) -
                    make_interval(secs => %s),w.queued_at))-clock_timestamp()))) AS delay
            FROM memory_work w LEFT JOIN memory_budget b ON b.owner_id=w.owner_id
            WHERE w.state='pending' ORDER BY delay,w.queued_at LIMIT 1''',
            (IDLE_SECONDS, OWNER_INTERVAL_SECONDS - GLOBAL_INTERVAL_SECONDS)).fetchone()

    def defer(self, work):
        """Requeue a known preclaim miss behind other work, without spending budget."""
        self.store.db.execute('''UPDATE memory_work SET queued_at=clock_timestamp()
            WHERE owner_id=%s AND conversation_id=%s AND generation=%s AND state='pending' ''',
            (work['owner_id'], work['conversation_id'], work['generation']))

    def claim(self, work):
        """Caller validates identity/source first; no provider retry follows this claim."""
        with self.store.db.transaction():
            claimed = self.store.db.execute('''UPDATE memory_work SET state='running',
                pending_source_unit=(SELECT id+1 FROM memory_source_units u
                    WHERE u.owner_id=memory_work.owner_id AND u.conversation_id=memory_work.conversation_id
                      AND u.turn_id=memory_work.turn_id),
                attempted_generation=generation,outcome=NULL
                WHERE owner_id=%s AND conversation_id=%s AND generation=%s AND state='pending'
                RETURNING generation''',
                (work['owner_id'], work['conversation_id'], work['generation'])).fetchone()
            if not claimed:
                return False
            self.store.db.execute('''INSERT INTO memory_budget(owner_id,next_attempt_at) VALUES
                (%s,clock_timestamp()+make_interval(secs => %s))
                ON CONFLICT(owner_id) DO UPDATE SET next_attempt_at=excluded.next_attempt_at''',
                (work['owner_id'], OWNER_INTERVAL_SECONDS))
        return True

    def finish(self, work, outcome):
        # Claim consumes the range durably before any possible request, including
        # process loss. Only a known fenced/unapplied result may restore it, and
        # only for an already newer generation—not a retry of the same attempt.
        retained = outcome in ('stale', 'superseded_before_request', 'superseded_after_request')
        self.store.db.execute('''UPDATE memory_work SET outcome=%s,
            pending_source_unit=CASE WHEN %s AND generation>%s THEN
                least(pending_source_unit,coalesce(%s,(SELECT id FROM memory_source_units
                    WHERE owner_id=%s AND conversation_id=%s AND turn_id=%s)))
                ELSE pending_source_unit END,
            state=CASE WHEN generation>%s THEN 'pending' ELSE 'idle' END
            WHERE owner_id=%s AND conversation_id=%s
              AND (attempted_generation=%s OR state='pending' AND generation=%s)''',
            (outcome, retained, work['generation'], work.get('pending_source_unit'),
             work['owner_id'], work['conversation_id'], work['turn_id'],
             work['generation'], work['owner_id'], work['conversation_id'],
             work['generation'], work['generation']))
