"""Deliberate person-linked passages with immutable source and append-only note actions."""

from m2.provenance import source_turn_current
from m2.references import PersonalContext


class SavedInsights:
    def __init__(self, store):
        self.store = store

    def _person(self, session, person_id):
        owner = self.store.owner(session)
        if not self.store.db.execute('''
            SELECT 1 FROM people WHERE owner_id=%s AND id=%s
        ''', (owner, self.store._id(person_id))).fetchone():
            raise KeyError('Person not found')
        return owner

    def _source(self, session, conversation_id, turn_id, kind, quote):
        self.store._id(conversation_id)
        self.store._id(turn_id)
        self.store._text(quote, 512)
        if kind not in ('user', 'assistant'):
            raise ValueError('Choose a user or assistant passage')
        turn = self.store.read_turn(session, conversation_id, turn_id)
        if turn['status'] != 'complete' or turn['next_event_offset'] is not None:
            raise ValueError('Complete source must fit the supported save window')
        head = self.store.active_head(session, conversation_id)
        chain = set(self.store.ancestry(session, conversation_id, head)) if head else set()
        if turn_id not in chain or not source_turn_current(
                self.store, session, conversation_id, turn_id,
                {conversation_id: chain}, {}):
            raise ValueError('Source message is no longer current')
        events = [event for event in turn['events'] if event['kind'] == (
            'user' if kind == 'user' else 'assistant_chunk')]
        content = ''.join(str(event['payload'].get('content', '')) for event in events)
        if not events or quote not in content:
            raise ValueError('Passage is not in the attributed source message')
        return events[0]['sequence']

    def save(self, session, person_id, entry_id, conversation_id, turn_id, kind, quote, note):
        owner = self._person(session, person_id)
        self.store._id(entry_id)
        if not isinstance(note, str) or len(note.encode('utf-8')) > 512:
            raise ValueError('Invalid or oversized insight note')
        with self.store.db.transaction():
            existing = self.store.db.execute('''
                SELECT conversation_id,source_turn_id,statement,epistemic_status
                FROM personal_entries WHERE owner_id=%s AND person_id=%s AND id=%s
            ''', (owner, person_id, entry_id)).fetchone()
            status = 'saved_user_passage' if kind == 'user' else 'saved_assistant_passage'
            if existing:
                saved_note = self.store.db.execute('''
                    SELECT note FROM personal_entry_actions WHERE owner_id=%s AND person_id=%s
                      AND entry_id=%s AND id=%s AND action='save'
                ''', (owner, person_id, entry_id, entry_id)).fetchone()
                if (existing['conversation_id'], existing['source_turn_id'], existing['statement'],
                        existing['epistemic_status'], saved_note['note'] if saved_note else None) != (
                        conversation_id, turn_id, quote, status, note):
                    raise ValueError('Insight ID reused with changed content')
                return entry_id
            sequence = self._source(session, conversation_id, turn_id, kind, quote)
            PersonalContext(self.store).add(session, person_id, entry_id, conversation_id,
                                            turn_id, quote, status, sequence)
            self.store.db.execute('''
                INSERT INTO personal_entry_actions(owner_id,person_id,entry_id,id,action,note)
                VALUES (%s,%s,%s,%s,'save',%s)
            ''', (owner, person_id, entry_id, entry_id, note))
        return entry_id

    def change(self, session, person_id, entry_id, action_id, action, note=''):
        owner = self._person(session, person_id)
        self.store._id(entry_id)
        self.store._id(action_id)
        if (action not in ('edit', 'remove') or not isinstance(note, str) or
                len(note.encode('utf-8')) > 512 or (action == 'remove' and note)):
            raise ValueError('Invalid insight action')
        with self.store.db.transaction():
            original = self.store.db.execute('''
                SELECT 1 FROM personal_entries WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, entry_id)).fetchone()
            if not original:
                raise KeyError('Insight not found')
            previous = self.store.db.execute('''
                SELECT action,note FROM personal_entry_actions
                WHERE owner_id=%s AND person_id=%s AND entry_id=%s AND id=%s
            ''', (owner, person_id, entry_id, action_id)).fetchone()
            if previous:
                if previous != {'action': action, 'note': note}:
                    raise ValueError('Insight action ID reused with changed content')
                return
            latest = self.store.db.execute('''
                SELECT action FROM personal_entry_actions WHERE owner_id=%s
                  AND person_id=%s AND entry_id=%s ORDER BY created_at DESC,id DESC LIMIT 1
            ''', (owner, person_id, entry_id)).fetchone()
            if latest and latest['action'] == 'remove':
                raise ValueError('Insight was already removed')
            self.store.db.execute('''
                INSERT INTO personal_entry_actions(owner_id,person_id,entry_id,id,action,note)
                VALUES (%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, entry_id, action_id, action, note))

    def list(self, session, person_id, offset=0, limit=20):
        owner = self._person(session, person_id)
        if type(offset) is not int or not 0 <= offset <= 10000 or not 1 <= limit <= 20:
            raise ValueError('Invalid insight page')
        rows = self.store.db.execute('''
            SELECT p.id,p.conversation_id,p.source_turn_id,p.source_event_sequence,
                   p.statement,p.epistemic_status,p.created_at,a.note
            FROM personal_entries p
            LEFT JOIN LATERAL (
                SELECT action,note FROM personal_entry_actions WHERE owner_id=p.owner_id
                  AND person_id=p.person_id AND entry_id=p.id
                ORDER BY created_at DESC,id DESC LIMIT 1
            ) a ON true
            WHERE p.owner_id=%s AND p.person_id=%s AND COALESCE(a.action,'save')!='remove'
            ORDER BY p.created_at DESC,p.id DESC LIMIT %s OFFSET %s
        ''', (owner, person_id, limit + 1, offset)).fetchall()
        more = len(rows) > limit
        entries = rows[:limit]
        chains, validity = {}, {}
        for row in entries:
            conv_id = row['conversation_id']
            if conv_id not in chains:
                head = self.store.active_head(session, conv_id)
                chains[conv_id] = set(self.store.ancestry(session, conv_id, head)) if head else set()
            row['source_status'] = 'current' if row['source_turn_id'] in chains[conv_id] and source_turn_current(
                self.store, session, conv_id, row['source_turn_id'], chains, validity) else 'historical'
            row['note'] = row['note'] or ''
        return {'entries': entries, 'next_offset': offset + limit if more else None}
