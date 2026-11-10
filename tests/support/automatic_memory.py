"""Committed synthetic background-memory UI state; no provider/network request."""
from m2.archive.conversations import Conversations
from m2.chat.memory_work import MemoryWork
from m2.chat.personal_context import set_preference
from m2.operations.product_policy import MODEL
from m2.people.people import People
from m2.people.personal_context import PersonalContext
from m2.provider.model_capacity import CatalogAdmission, resolve_capacity


def seed_memory_views(store):
    for view in ('desktop', 'mobile', 'short-mobile', 'reflow'):
        owner = 'reader-memory-' + view
        store.register_local(owner, 'synthetic-browser-password')
        session = store.authenticate(owner, 'synthetic-browser-password')
        People(store).charts.add_person(session, 'frederik', 'Frederik')
        set_preference(store, session, True, 0)
        Conversations(store).create(session, 'memory-reading', 'Garden conversation')
        store.memory_origins[(owner, 'memory-reading', 'remembered')] = {
            'session_digest': 'synthetic-expired-session',
            'admission': CatalogAdmission(owner, MODEL, 'synthetic-binding',
                                          resolve_capacity({'slug': MODEL}))}
        statement = 'Frederik enjoys gardening.'
        store.begin(session, 'memory-reading', 'remembered', statement, None,
                    selected_people=[], model_provider='chatgpt_plan', model_slug=MODEL)
        store.append(session, 'memory-reading', 'remembered', 'assistant_chunk',
                     {'content': 'Gardening can be a rewarding creative practice.'})
        store.append(session, 'memory-reading', 'remembered', 'complete', {})
        store.memory_origins.pop((owner, 'memory-reading', 'remembered'))
        unit = store.db.execute('''SELECT id FROM memory_source_units WHERE owner_id=%s
            AND conversation_id='memory-reading' AND turn_id='remembered' ''', (owner,)).fetchone()['id']
        source = {'kind': 'conversation', 'conversation_id': 'memory-reading',
                  'turn_id': 'remembered', 'revision': 0, 'source_unit': unit, 'statement': statement}
        PersonalContext(store).save(session, 'frederik', 'remembered-interest', 'synthetic-background', 0,
            {'group': 'interests', 'title': statement, 'notes': '', 'state': None,
             'date': {'text': '', 'precision': 'unknown', 'start': None, 'end': None}},
            {**source, 'sources': [source]})
        work = store.db.execute('SELECT * FROM memory_work WHERE owner_id=%s', (owner,)).fetchone()
        MemoryWork(store).claim(work)
        MemoryWork(store).finish(work, 'saved')
        set_preference(store, session, False, 1)
