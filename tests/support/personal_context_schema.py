"""Explicit rollback of only the new empty tables for historical migration fixtures."""

def remove_personal_context_schema(db):
    db.execute('''DROP TABLE memory_source_suppressions, memory_source_units,
        memory_budget, memory_work, personal_context_actions, personal_profile_actions,
        context_update_stages, personal_context_consent, personal_context_self, personal_details,
        person_links, personal_context''')
    db.execute('DELETE FROM schema_migrations WHERE version>=25')
