"""Versioned personal facts, separate from journals and calculated interpretations."""
from datetime import date

from psycopg.types.json import Jsonb

from m2.people.person_records import _person

GROUPS = ('coming_up', 'life_now', 'past_moments', 'interests', 'goals',
          'astrology_knowledge', 'guidance_preferences')
LIFE = GROUPS[:3]


class ContextConflict(ValueError):
    pass


def content_checked(value):
    if not isinstance(value, dict) or set(value) != {'group', 'title', 'notes', 'state', 'date'}:
        raise ValueError('Invalid context fields')
    if value['group'] not in GROUPS:
        raise ValueError('Choose a context group')
    for key, maximum in (('title', 256), ('notes', 2048)):
        if not isinstance(value[key], str) or len(value[key].encode('utf-8')) > maximum:
            raise ValueError('Context text is too long')
    if not value['title'].strip():
        raise ValueError('Enter a title')
    states = ('planned', 'tentative', 'ongoing', 'completed', 'cancelled', None)
    if value['state'] not in states or (value['group'] not in LIFE and value['state'] is not None):
        raise ValueError('Choose a life-event state, not learning progress')
    dates = value['date']
    if not isinstance(dates, dict) or set(dates) != {'text', 'precision', 'start', 'end'}:
        raise ValueError('Invalid context date')
    if not isinstance(dates['text'], str) or len(dates['text'].encode('utf-8')) > 256:
        raise ValueError('Date description is too long')
    precision = dates['precision']
    if precision not in ('unknown', 'exact', 'month', 'year', 'range'):
        raise ValueError('Choose date precision')
    start, end = dates['start'], dates['end']
    if precision == 'unknown':
        if start is not None or end is not None:
            raise ValueError('An unknown date has no normalized bounds')
    else:
        try:
            if precision == 'month':
                parsed = date.fromisoformat(start + '-01')
                valid = parsed.strftime('%Y-%m') == start and end is None
            elif precision == 'year':
                parsed = date(int(start), 1, 1)
                valid = f'{parsed.year:04d}' == start and end is None
            else:
                parsed = date.fromisoformat(start)
                valid = parsed.isoformat() == start
                if precision == 'range':
                    last = date.fromisoformat(end)
                    valid = valid and last.isoformat() == end and last >= parsed
                else:
                    valid = valid and end is None
            if not valid:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError('Date must match the chosen precision') from None
    return value


class PersonalContext:
    def __init__(self, store):
        self.store = store

    def save(self, session, person_id, entry_id, operation_id, expected_version, content,
             source=None):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(entry_id); store._id(operation_id)
        content_checked(content)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('Invalid expected version')
        source = source or {'kind': 'manual'}
        if store.ledger.contains_person_record(owner, person_id, entry_id, 'context_entry'):
            raise ContextConflict('This entry was removed')
        with store.db.transaction():
            old = store.db.execute('''
                SELECT entry_id,expected_version,content,source,version FROM personal_context_actions
                WHERE owner_id=%s AND person_id=%s AND id=%s
            ''', (owner, person_id, operation_id)).fetchone()
            if old:
                if (old['entry_id'], old['expected_version'], old['content'], old['source']) != (
                        entry_id, expected_version, content, source):
                    raise ContextConflict('Operation identity reused with changed input')
                return {'id': entry_id, 'version': old['version']}
            row = store.db.execute('''
                SELECT version,lifecycle FROM personal_context WHERE owner_id=%s AND person_id=%s AND id=%s FOR UPDATE
            ''', (owner, person_id, entry_id)).fetchone()
            if row and row['lifecycle'] != 'active' and source['kind'] != 'manual':
                raise ContextConflict('Original source no longer eligible')
            if (row['version'] if row else 0) != expected_version:
                raise ContextConflict('Entry changed. Reopen the saved entry before editing again')
            version = expected_version + 1
            store.db.execute('''
                INSERT INTO personal_context(owner_id,person_id,id,version,content,source)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,person_id,id)
                DO UPDATE SET version=excluded.version,content=excluded.content,
                    source=excluded.source,lifecycle='active',updated_at=now()
            ''', (owner, person_id, entry_id, version, Jsonb(content), Jsonb(source)))
            store.db.execute('''
                INSERT INTO personal_context_actions(owner_id,person_id,entry_id,id,
                    expected_version,content,source,version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ''', (owner, person_id, entry_id, operation_id, expected_version,
                  Jsonb(content), Jsonb(source), version))
            if source['kind'] == 'manual':
                for conversation in store.db.execute('SELECT id FROM conversations WHERE owner_id=%s', (owner,)).fetchall():
                    store._changed(owner, conversation['id'])
        return {'id': entry_id, 'version': version}

    def list(self, session, person_id, group=None, query='', offset=0):
        store = self.store
        owner = _person(store, session, person_id)
        if group is not None and group not in GROUPS:
            raise ValueError('Invalid context group')
        if type(offset) is not int or offset < 0 or offset > 100000:
            raise ValueError('Invalid context page')
        if not isinstance(query, str) or len(query) > 256:
            raise ValueError('Search is too long')
        # strpos treats user search literally, including SQL wildcard characters.
        where = '''owner_id=%s AND person_id=%s AND lifecycle='active'
            AND (%s::text IS NULL OR content->>'group'=%s)
            AND strpos(lower((content->>'title') || ' ' || (content->>'notes') || ' ' ||
                (content->'date')::text),lower(%s))>0'''
        args = (owner, person_id, group, group, query)
        counts = store.db.execute(f'''SELECT content->>'group' AS group,count(*) AS total
            FROM personal_context WHERE {where} GROUP BY content->>'group' ''', args).fetchall()
        if group is None:
            rows = store.db.execute(f'''SELECT * FROM (
                SELECT id,version,content,source,created_at,updated_at,
                  row_number() OVER (PARTITION BY content->>'group' ORDER BY updated_at DESC,id) AS rank
                FROM personal_context WHERE {where}) ranked WHERE rank<=2
                ORDER BY content->>'group',rank''', args).fetchall()
        else:
            rows = store.db.execute(f'''SELECT id,version,content,source,created_at,updated_at
                FROM personal_context WHERE {where} ORDER BY updated_at DESC,id LIMIT 21 OFFSET %s''',
                (*args, offset)).fetchall()
        return {'entries': [{key: value.isoformat() if key.endswith('_at') else value
                             for key, value in row.items() if key != 'rank'}
                            for row in (rows[:20] if group else rows)],
                'counts': {row['group']: row['total'] for row in counts},
                'next_offset': offset + 20 if group and len(rows) > 20 else None}

    def remove(self, session, person_id, entry_id, expected_version):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(entry_id)
        if store.ledger.contains_person_record(owner, person_id, entry_id, 'context_entry'):
            return
        row = store.db.execute('''SELECT version FROM personal_context
            WHERE owner_id=%s AND person_id=%s AND id=%s''', (owner, person_id, entry_id)).fetchone()
        if not row:
            raise KeyError('Context entry not found')
        if type(expected_version) is not int or row['version'] != expected_version:
            raise ContextConflict('Entry changed. Reopen before removing it')
        store.ledger.delete_person_record(store, session, person_id, entry_id, 'context_entry')
