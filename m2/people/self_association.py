"""Explicit, versioned speaker identity; never inferred from chart selection."""
from m2.people.personal_context import ContextConflict
from m2.people.person_records import _person


def association(store, session):
    owner = store.owner(session)
    return store.db.execute('''SELECT person_id,version FROM personal_context_self
        WHERE owner_id=%s''', (owner,)).fetchone() or {'person_id': None, 'version': 0}


def set_association(store, session, person_id, expected_version):
    owner = store.owner(session)
    if type(expected_version) is not int or not 0 <= expected_version < 2147483647:
        raise ValueError('Expected self-association version required')
    if person_id is not None:
        store._id(person_id)
        _person(store, session, person_id)
    with store.db.transaction():
        current = association(store, session)
        desired = {'person_id': person_id, 'version': expected_version + 1}
        if person_id is not None and current['person_id'] == person_id and expected_version in (
                current['version'], current['version'] - 1):
            return current  # Same-choice acknowledgement recovery, not a new generation.
        if current['version']:
            # Deletion/older restore may clear the ID, but never consume the choice twice.
            raise ContextConflict('Your self association has already been chosen')
        if expected_version != 0:
            raise ContextConflict('Self association changed; refresh the saved choice')
        if person_id is None:
            raise ValueError('Choose an owned person for your one-time self association')
        # Journal only the authority generation, never a name or replacement
        # identity. An older restored database retains a consumed choice, not a new identity.
        store.ledger.revoke_context_self(store, session, desired['version'])
        store.db.execute('''INSERT INTO personal_context_self VALUES (%s,%s,%s)
            ON CONFLICT(owner_id) DO UPDATE SET person_id=excluded.person_id,version=excluded.version''',
            (owner, person_id, desired['version']))
        # Cached replies may use 'you' under the previous explicit association.
        # Keep originals and stored facts; rebuild only derived continuity.
        for row in store.db.execute('SELECT id FROM conversations WHERE owner_id=%s', (owner,)).fetchall():
            store._changed(owner, row['id'])
    return desired
