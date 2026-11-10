"""Bounded original-user sources and owned targets for deferred consolidation.

Runs on the single Store worker, without provider calls. Interpretation happens
later; the result is only a fenced, untrusted evidence snapshot.
"""
import json
import re

from m2.chat.personal_context import preference
from m2.people.self_association import association

MAX_ANCESTRY = 2000
MAX_MESSAGES = 8
MAX_INPUT_BYTES = 24_000
MAX_PEOPLE = 8
MAX_ENTRIES = 32


def original_messages(store, session, conversation_id, turn_id, consent):
    owner = store.owner(session)
    rows = store.db.execute('''WITH RECURSIVE chain AS (
        SELECT t.id,t.parent_id,t.parent_revision,t.status,0 AS depth FROM turns t
        WHERE t.owner_id=%s AND t.conversation_id=%s AND t.id=%s
        UNION ALL SELECT t.id,t.parent_id,t.parent_revision,t.status,c.depth+1
        FROM turns t JOIN chain c ON t.id=c.parent_id
        WHERE t.owner_id=%s AND t.conversation_id=%s AND c.depth<%s
    ), checked AS (
        SELECT c.*,coalesce((SELECT max(sequence) FROM corrections r
            WHERE r.owner_id=%s AND r.conversation_id=%s AND r.source_turn_id=c.id),0) AS revision
        FROM chain c
    ), valid AS (
        SELECT bool_and(c.status='complete' AND c.depth<%s AND
            (c.parent_id IS NULL OR p.id IS NOT NULL AND
             coalesce(c.parent_revision,0)=p.revision)) AS current
        FROM checked c LEFT JOIN checked p ON p.id=c.parent_id
    ) SELECT c.id,c.depth,u.id AS source_unit,e.payload FROM checked c
      JOIN valid ON valid.current JOIN events e ON e.owner_id=%s
        AND e.conversation_id=%s AND e.turn_id=c.id AND e.sequence=0
      JOIN memory_source_units u ON u.owner_id=e.owner_id
        AND u.conversation_id=e.conversation_id AND u.turn_id=e.turn_id
      WHERE c.depth<%s AND c.revision=0 ORDER BY c.depth''',
        (owner, conversation_id, turn_id, owner, conversation_id, MAX_ANCESTRY,
         owner, conversation_id, MAX_ANCESTRY, owner, conversation_id, MAX_MESSAGES)).fetchall()
    messages = []
    size = 0
    for row in rows:
        payload = row['payload']
        text = payload['content']
        if payload.get('personal_context', {}).get('consent') != consent:
            continue
        length = len(text.encode())
        if length > 8192 or size + length > MAX_INPUT_BYTES:
            continue  # Never trim a trailing qualifier/retraction to make text fit.
        size += length
        messages.append({'conversation_id': conversation_id, 'turn_id': row['id'],
                         'source_unit': row['source_unit'], 'text': text,
                         'clock_anchor': payload.get('clock_anchor')})
    return list(reversed(messages))


def owned_targets(store, session, messages, speaker):
    """Bound candidate strings/results; duplicates remain ambiguous, never pick-first."""
    owner = store.owner(session)
    names = set()
    for message in reversed(messages):
        words = list(re.finditer(r"[\w]+(?:[’'-][\w]+)*", message['text']))[:128]
        for start in range(len(words)):
            for length in range(1, min(4, len(words) - start) + 1):
                names.add(message['text'][words[start].start():words[start + length - 1].end()].lower())
                if len(names) >= 512:
                    break
            if len(names) >= 512:
                break
        if len(names) >= 512:
            break
    rows = store.db.execute('''SELECT id,name,count(*) OVER (PARTITION BY lower(name)) AS same_name
        FROM people WHERE owner_id=%s AND (lower(name)=ANY(%s) OR id=%s)
        ORDER BY id LIMIT %s''', (owner, sorted(names), speaker['person_id'], MAX_PEOPLE + 1)).fetchall()
    if len(rows) > MAX_PEOPLE:
        return []
    return [{'id': row['id'], 'name': row['name'],
             'named_eligible': row['name'].lower() in names and row['same_name'] == 1,
             'associated_self': row['id'] == speaker['person_id']} for row in rows]


def snapshot(store, auth, work):
    session, _, _ = auth.resolve_digest(work['session_digest'])
    owner = store.owner(session)
    if owner != work['owner_id']:
        raise PermissionError('Memory owner differs')
    consent = preference(store, session)
    if consent != {'enabled': True, 'version': work['consent_version']}:
        return None
    conversation = store._conversation(owner, work['conversation_id'])
    if conversation['active_head'] != work['turn_id']:
        return None
    messages = original_messages(store, session, work['conversation_id'], work['turn_id'], consent)
    if not messages or messages[-1]['turn_id'] != work['turn_id']:
        return None
    speaker = association(store, session)
    targets = owned_targets(store, session, messages, speaker)
    people = []
    for person in targets:
        barrier = store.db.execute('''SELECT source_before FROM memory_source_suppressions
            WHERE owner_id=%s AND person_id=%s''', (owner, person['id'])).fetchone()
        cutoff = barrier['source_before'] if barrier else 0
        eligible = [item['turn_id'] for item in messages if item['source_unit'] > cutoff]
        if work['turn_id'] not in eligible:
            continue
        entries = store.db.execute('''SELECT id,version,content,source,lifecycle FROM personal_context
            WHERE owner_id=%s AND person_id=%s ORDER BY id LIMIT %s''',
            (owner, person['id'], MAX_ENTRIES + 1)).fetchall()
        if len(entries) > MAX_ENTRIES:
            continue  # Hidden records could be semantic duplicates; do not append blindly.
        people.append({**person, 'source_before': cutoff, 'eligible_turns': eligible, 'entries': entries})
    result = {'conversation_id': work['conversation_id'], 'turn_id': work['turn_id'],
              'epoch': conversation['epoch'], 'consent': consent, 'self_association': speaker,
              'messages': messages, 'people': people}
    if not people or len(json.dumps(result, ensure_ascii=False).encode()) > 32_000:
        return None
    return result
