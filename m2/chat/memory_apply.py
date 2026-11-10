"""Short owner-serialized commit after deferred interpretation has finished."""
from hashlib import sha256
import json

from m2.chat.memory_evidence import snapshot
from m2.people.personal_context import PersonalContext


def apply(store, auth, bridge, work, evidence, actions):
    # Never reserve Store waiting for credential refresh/account switching. With
    # the guard acquired, a switch cannot race the final validation/transaction.
    with bridge.background_guard(work['owner_id'], work['account_binding']):
        with store.db.transaction():
            if snapshot(store, auth, work) != evidence:
                return 'stale'
            current = store.db.execute('''SELECT generation,state FROM memory_work
                WHERE owner_id=%s AND conversation_id=%s''',
                (work['owner_id'], work['conversation_id'])).fetchone()
            if current != {'generation': work['generation'], 'state': 'running'}:
                return 'stale'
            session, _, _ = auth.resolve_digest(work['session_digest'])
            for action in actions:
                identity = json.dumps([work['owner_id'], work['conversation_id'], work['turn_id'],
                    action['person_id'], action['entry_id'] or action['content']['group']], separators=(',', ':'))
                operation = 'memory-' + sha256(identity.encode()).hexdigest()
                PersonalContext(store).save(session, action['person_id'], action['entry_id'] or operation,
                    operation, action['expected_version'], action['content'], action['source'])
            if actions:
                store.db.execute('''UPDATE memory_budget SET context_revision=context_revision+1
                    WHERE owner_id=%s''', (work['owner_id'],))
    return 'saved' if actions else 'unchanged'
