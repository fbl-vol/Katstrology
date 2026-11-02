"""One owner-scoped conversation with cumulative people and immutable turn scopes."""

class Conversations:
    def __init__(self, store):
        self.store = store

    def create(self, session, conv_id, title, people=()):
        owner = self.store.owner(session)
        self.store._id(conv_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise ValueError('Conversation title must be 1..80 characters')
        if (not isinstance(people, (list, tuple)) or len(people) > 8 or
                any(not isinstance(person, str) for person in people) or
                len(set(people)) != len(people)):
            raise ValueError('Select up to eight distinct people')
        people = sorted(self.store._id(person) for person in people)
        with self.store.db.transaction():
            existing = self.store.db.execute('''
                SELECT title FROM conversations WHERE owner_id=%s AND id=%s FOR UPDATE
            ''', (owner, conv_id)).fetchone()
            if existing:
                selected = self.store.db.execute('''
                    SELECT person_id FROM conversation_people
                    WHERE owner_id=%s AND conversation_id=%s ORDER BY person_id
                ''', (owner, conv_id)).fetchall()
                if existing['title'] != title.strip() or [row['person_id'] for row in selected] != people:
                    raise ValueError('Conversation ID reused with changed scope')
                return self.get(session, conv_id)
            self.store.create_conversation(session, conv_id)
            self.store.db.execute('''
                UPDATE conversations SET title=%s, title_origin=%s, title_status=%s
                WHERE owner_id=%s AND id=%s
            ''', (title.strip(), 'placeholder' if title.strip() == 'New conversation' else 'manual',
                  'waiting' if title.strip() == 'New conversation' else 'untouched', owner, conv_id))
            for person_id in people:
                if not self.store.db.execute('''
                    SELECT 1 FROM people WHERE owner_id=%s AND id=%s
                ''', (owner, person_id)).fetchone():
                    raise KeyError('Selected person not found')
                self.store.db.execute('''
                    INSERT INTO conversation_people(owner_id,conversation_id,person_id)
                    VALUES (%s,%s,%s)
                ''', (owner, conv_id, person_id))
        return self.get(session, conv_id)

    def rename(self, session, conv_id, title):
        owner = self.store.owner(session)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise ValueError('Conversation title must be 1..80 characters')
        with self.store.db.transaction():
            self.store._conversation(owner, conv_id, lock=True)
            self.store.db.execute('''
                UPDATE conversations SET title=%s, title_origin='manual', title_status='untouched'
                WHERE owner_id=%s AND id=%s
            ''', (title.strip(), owner, conv_id))
        return self.get(session, conv_id)

    def get(self, session, conv_id):
        owner = self.store.owner(session)
        row = self.store._conversation(owner, conv_id)
        row['people'] = self.store.db.execute('''
            SELECT cp.person_id, p.name FROM conversation_people cp
            JOIN people p ON p.owner_id=cp.owner_id AND p.id=cp.person_id
            WHERE cp.owner_id=%s AND cp.conversation_id=%s ORDER BY p.name,cp.person_id
        ''', (owner, conv_id)).fetchall()
        return row

    def list(self, session, person_id=None, query=None, offset=0, limit=20):
        owner = self.store.owner(session)
        if not isinstance(offset, int) or not 0 <= offset <= 10000 or not 1 <= limit <= 20:
            raise ValueError('Invalid conversation page')
        if person_id is not None:
            self.store._id(person_id)
            if not self.store.db.execute('SELECT 1 FROM people WHERE owner_id=%s AND id=%s',
                                         (owner, person_id)).fetchone():
                raise KeyError('Person not found')
        if query is not None and (not isinstance(query, str) or not 1 <= len(query) <= 256):
            raise ValueError('Invalid conversation search')
        rows = self.store.db.execute('''
            SELECT c.id,c.title,c.title_origin,c.title_status,c.created_at,c.active_head,
                   (SELECT COUNT(*) FROM turns t WHERE t.owner_id=c.owner_id
                    AND t.conversation_id=c.id) AS turn_count,
                   (SELECT jsonb_agg(jsonb_build_object('id',p.id,'name',p.name) ORDER BY p.name)
                    FROM conversation_people cp JOIN people p
                      ON p.owner_id=cp.owner_id AND p.id=cp.person_id
                    WHERE cp.owner_id=c.owner_id AND cp.conversation_id=c.id) AS people
            FROM conversations c WHERE c.owner_id=%s
              AND (%s::text IS NULL OR EXISTS (
                  SELECT 1 FROM conversation_people cp WHERE cp.owner_id=c.owner_id
                  AND cp.conversation_id=c.id AND cp.person_id=%s))
              AND (%s::text IS NULL OR position(lower(%s) in lower(c.title)) > 0 OR EXISTS (
                  SELECT 1 FROM search_entries e WHERE e.owner_id=c.owner_id
                  AND e.conversation_id=c.id AND e.epoch=c.epoch
                  AND to_tsvector('simple',e.content) @@ plainto_tsquery('simple',%s)))
            ORDER BY c.created_at DESC,c.id DESC LIMIT %s OFFSET %s
        ''', (owner, person_id, person_id, query, query, query, limit + 1, offset)).fetchall()
        more = len(rows) > limit
        page = rows[:limit]
        if page:
            ids = [row['id'] for row in page]
            # The search index contains only the selected branch at its exact epoch.
            # Never fetch whole turns just to fill the navigation preview.
            previews = self.store.db.execute('''
                SELECT DISTINCT ON (e.conversation_id) e.conversation_id, e.speaker,
                       left(regexp_replace(left(e.content, 240), '[[:space:]]+', ' ', 'g'), 144) AS excerpt
                FROM search_entries e JOIN conversations c
                  ON c.owner_id=e.owner_id AND c.id=e.conversation_id AND c.epoch=e.epoch
                LEFT JOIN turns t ON t.owner_id=e.owner_id AND t.conversation_id=e.conversation_id
                  AND t.id=e.source_id
                LEFT JOIN corrections correction ON correction.owner_id=e.owner_id
                  AND correction.conversation_id=e.conversation_id AND correction.id=e.source_id
                WHERE e.owner_id=%s AND e.conversation_id=ANY(%s::text[])
                ORDER BY e.conversation_id,
                  CASE WHEN %s::text IS NOT NULL AND
                    to_tsvector('simple',e.content) @@ plainto_tsquery('simple',%s) THEN 0 ELSE 1 END,
                  COALESCE(correction.created_at,t.created_at) DESC,
                  CASE e.speaker WHEN 'correction' THEN 0 WHEN 'user' THEN 1 ELSE 2 END, e.source_id DESC
            ''', (owner, ids, query, query)).fetchall()
            by_id = {item['conversation_id']: item for item in previews}
            queued = self.store.db.execute('''
                SELECT conversation_id FROM rebuild_queue
                WHERE owner_id=%s AND conversation_id=ANY(%s::text[])
            ''', (owner, ids)).fetchall()
            pending = {item['conversation_id'] for item in queued}
            for row in page:
                row['people'] = row['people'] or []
                match = by_id.get(row['id'])
                row['preview'] = match['excerpt'] if match else None
                row['preview_speaker'] = match['speaker'] if match else None
                row['preview_pending'] = row['id'] in pending
        return {'conversations': page, 'next_offset': offset + limit if more else None,
                'search_pending': self.store.db.execute('''
                    SELECT count(*) AS n FROM rebuild_queue WHERE owner_id=%s
                ''', (owner,)).fetchone()['n'] if query else 0}

    def turns(self, session, conv_id, offset=0, limit=20):
        owner = self.store.owner(session)
        conversation = self.store._conversation(owner, conv_id)
        if not isinstance(offset, int) or not 0 <= offset <= 10000 or not 1 <= limit <= 20:
            raise ValueError('Invalid turn page')
        rows = self.store.db.execute('''
            SELECT id, parent_id, parent_revision, status, source, revision_kind,
                   replaces_turn_id, created_at FROM turns
            WHERE owner_id=%s AND conversation_id=%s
            ORDER BY created_at,id LIMIT %s OFFSET %s
        ''', (owner, conv_id, limit + 1, offset)).fetchall()
        page = rows[:limit]
        active = (set(self.store.ancestry(session, conv_id, conversation['active_head']))
                  if conversation['active_head'] else set())
        turns = self.store._read_turns(owner, conv_id, page, event_limit=32)
        for turn in turns:
            turn['on_active_branch'] = turn['id'] in active
        return {'turns': turns, 'next_offset': offset + limit if len(rows) > limit else None}
