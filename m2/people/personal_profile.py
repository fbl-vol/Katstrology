"""User-controlled stable details and directional links to existing owned identities."""
from psycopg.types.json import Jsonb
from m2.people.person_records import _person
from m2.people.personal_context import ContextConflict
from m2.people.picker_labels import OWNED_CHOICES_CTE, picker_label

FIELDS = ('pronouns', 'home', 'occupation', 'about')


class PersonalProfile:
    def __init__(self, store):
        self.store = store

    def get(self, session, person_id):
        store = self.store
        owner = _person(store, session, person_id)
        details = store.db.execute('SELECT version,details FROM personal_details WHERE owner_id=%s AND person_id=%s',
                                   (owner, person_id)).fetchone()
        rows = store.db.execute(OWNED_CHOICES_CTE + '''
            SELECT l.id,l.other_person_id,l.label,l.dates,l.version,
                p.name,p.created_at,p.details,p.name_count,p.name_number
            FROM person_links l JOIN person_choices p ON p.id=l.other_person_id
            WHERE l.owner_id=%s AND l.person_id=%s ORDER BY p.name,l.id''',
            (owner, owner, person_id)).fetchall()
        links = [{'id': row['id'], 'other_person_id': row['other_person_id'],
                  'label': row['label'], 'dates': row['dates'], 'version': row['version'],
                  'name': row['name'], 'picker_label': picker_label(row)} for row in rows]
        return {**(details or {'version': 0, 'details': dict.fromkeys(FIELDS, '')}), 'links': links}

    def change(self, session, person_id, operation_id, request):
        store = self.store
        owner = _person(store, session, person_id)
        store._id(operation_id)
        if not isinstance(request, dict) or request.get('kind') not in ('details', 'link', 'unlink'):
            raise ValueError('Invalid profile change')
        version = request.get('expected_version')
        if type(version) is not int or version < 0:
            raise ValueError('Expected version required')
        with store.db.transaction():
            previous = store.db.execute('''SELECT request,result FROM personal_profile_actions
                WHERE owner_id=%s AND person_id=%s AND id=%s''', (owner, person_id, operation_id)).fetchone()
            if previous:
                if previous['request'] != request:
                    raise ContextConflict('Operation identity changed')
                return previous['result']
            if request['kind'] == 'details':
                if set(request) != {'kind', 'expected_version', 'details'} or not isinstance(request['details'], dict) or set(request['details']) != set(FIELDS):
                    raise ValueError('Invalid stable details')
                if any(not isinstance(value, str) or len(value.encode('utf-8')) > 1024 for value in request['details'].values()):
                    raise ValueError('Personal details are too long')
                if self.get(session, person_id)['version'] != version:
                    raise ContextConflict('Details changed')
                store.db.execute('''INSERT INTO personal_details VALUES (%s,%s,%s,%s)
                    ON CONFLICT(owner_id,person_id) DO UPDATE SET version=excluded.version,details=excluded.details''',
                    (owner, person_id, version + 1, Jsonb(request['details'])))
            else:
                keys = {'kind', 'expected_version', 'id'}
                if request['kind'] == 'link':
                    keys |= {'other_person_id', 'label', 'dates'}
                if set(request) != keys:
                    raise ValueError('Invalid relationship fields')
                link_id = store._id(request['id'])
                if store.ledger.contains_person_record(owner, person_id, link_id, 'person_link'):
                    if request['kind'] == 'unlink':
                        return {'version': version + 1}
                    raise ContextConflict('Removed relationship identity cannot be reused')
                row = store.db.execute('''SELECT version FROM person_links
                    WHERE owner_id=%s AND person_id=%s AND id=%s''', (owner, person_id, link_id)).fetchone()
                if (row['version'] if row else 0) != version:
                    raise ContextConflict('Relationship changed')
                if request['kind'] == 'unlink':
                    if not row:
                        raise KeyError('Relationship not found')
                    store.ledger.delete_person_record(store, session, person_id, link_id, 'person_link')
                else:
                    _person(store, session, request['other_person_id'])
                    if request['other_person_id'] == person_id:
                        raise ValueError('Cannot link a person to themselves')
                    label = request['label']
                    if not isinstance(label, str) or not label.strip() or len(label.encode('utf-8')) > 128:
                        raise ValueError('Enter a relationship label')
                    label = label.strip()
                    if not isinstance(request['dates'], str) or len(request['dates'].encode('utf-8')) > 256:
                        raise ValueError('Dates are too long')
                    duplicate = store.db.execute('''SELECT 1 FROM person_links WHERE owner_id=%s AND person_id=%s
                        AND other_person_id=%s AND lower(label)=lower(%s) AND id<>%s''',
                        (owner, person_id, request['other_person_id'], label, link_id)).fetchone()
                    if duplicate:
                        raise ContextConflict('This relationship already exists')
                    store.db.execute('''INSERT INTO person_links(owner_id,person_id,id,other_person_id,label,dates,version)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,person_id,id)
                        DO UPDATE SET other_person_id=excluded.other_person_id,label=excluded.label,
                            dates=excluded.dates,version=excluded.version''',
                        (owner, person_id, link_id, request['other_person_id'], label, request['dates'], version + 1))
            if request['kind'] == 'details':
                for conversation in store.db.execute('SELECT id FROM conversations WHERE owner_id=%s', (owner,)).fetchall():
                    store._changed(owner, conversation['id'])
            result = {'version': version + 1}
            store.db.execute('INSERT INTO personal_profile_actions VALUES (%s,%s,%s,%s,%s)',
                             (owner, person_id, operation_id, Jsonb(request), Jsonb(result)))
        return result
