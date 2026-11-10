"""Historical mutable-self state, never a supported current API operation."""


def legacy_association(store, session, person_id):
    from m2.people.self_association import association
    owner = store.owner(session)
    version = association(store, session)['version'] + 1
    with store.db.transaction():
        store.ledger.revoke_context_self(store, session, version)
        store.db.execute('''UPDATE personal_context_self SET person_id=%s,version=%s
            WHERE owner_id=%s''', (person_id, version, owner))
        for row in store.db.execute('SELECT id FROM conversations WHERE owner_id=%s', (owner,)).fetchall():
            store._changed(owner, row['id'])
