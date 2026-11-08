from pathlib import Path
from hashlib import sha256
from m2.release_schema import migrate
from tests.support.personal_context_schema import remove_personal_context_schema
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from m2.archive.backup import backup, restore
from m2.people.people import People
from m2.people.personal_context import PersonalContext, ContextConflict, content_checked
from tests.support.database import DatabaseCase


def fact(group='coming_up', title='Tentative move'):
    return {'group': group, 'title': title, 'notes': 'Considering options',
            'state': 'tentative' if group == 'coming_up' else None,
            'date': {'text': 'next summer, perhaps', 'precision': 'unknown', 'start': None, 'end': None}}


class PersonalContextTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        People(self.store).charts.add_person(self.alice, 'one', 'Same name')
        People(self.store).charts.add_person(self.bob, 'one', 'Same name')
        self.context = PersonalContext(self.store)

    def test_http_search_mutations_and_conflicts_use_authenticated_owner(self):
        from starlette.testclient import TestClient
        from m2.http_boundary.app import create_app
        self.context.save(self.alice, 'one', 'entry', 'create', 0, fact())
        People(self.store).charts.add_person(self.alice, 'alice-only', 'Casey')
        self.store.close()
        dist = Path(self.directory.name) / 'dist'
        dist.mkdir(); (dist / 'index.html').write_text('<title>Synthetic context test</title>')
        # ASGI transport only, not a connection to the live listener.
        origin = 'http://127.0.0.1:8765'
        with TestClient(create_app(self.dsn, self.store.files, self.ledger.path, dist), base_url=origin) as client:
            self.assertEqual(client.get('/api/people/one/context').status_code, 401)
            self.assertEqual(client.get('/api/personal-context-self').status_code, 401)
            for owner in ('bob', 'alice'):
                client.post('/api/login', headers={'Origin': origin},
                            json={'username': owner, 'password': f'synthetic-password-{owner}'})
                csrf = client.get('/api/session').json()['csrf']
                headers = {'Origin': origin, 'X-Kat-CSRF': csrf}
                result = client.post('/api/people/one/context/search', headers=headers,
                                     json={'group': None, 'query': 'move', 'offset': 0})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(len(result.json()['entries']), 1 if owner == 'alice' else 0)
                self.assertEqual(client.post('/api/people/one/context', headers=headers, json={
                    'id': 'entry', 'operation_id': 'stale', 'expected_version': 9, 'content': fact()}).status_code, 409)
                self.assertEqual(client.post('/api/people/one/context/search', headers={'Origin': origin},
                    json={'group': None, 'query': 'move', 'offset': 0}).status_code, 403)
                self.assertEqual(client.get('/api/people/one/context?query=private').status_code, 400)
                self.assertEqual(client.get('/api/personal-context-self').json(), {'person_id': None, 'version': 0})
                if owner == 'bob':
                    self.assertEqual(client.post('/api/personal-context-self', headers=headers,
                        json={'person_id': 'alice-only', 'expected_version': 0}).status_code, 404)
                self.assertEqual(client.post('/api/personal-context-self', headers={'Origin': origin},
                    json={'person_id': 'one', 'expected_version': 0}).status_code, 403)
                self.assertEqual(client.post('/api/personal-context-self', headers=headers,
                    json={'person_id': 'one', 'expected_version': 0, 'owner': 'alice'}).status_code, 400)
                self.assertEqual(client.post('/api/personal-context-self', headers=headers,
                    json={'person_id': 'one', 'expected_version': 0}).json(), {'person_id': 'one', 'version': 1})
                self.assertEqual(client.post('/api/personal-context-self', headers=headers,
                    json={'person_id': None, 'expected_version': 0}).status_code, 409)
                self.assertFalse(client.get('/api/personal-context-preference').json()['enabled'])

    def test_collection_paging_and_only_user_date_fields_are_searchable(self):
        for group in ('coming_up', 'life_now', 'interests', 'goals'):
            for index in range(23):
                content = fact(group, f'{group} item {index}')
                content['notes'] = 'orchard' if index == 0 else ''
                content['date'] = {'text': 'Spring festival', 'precision': 'month', 'start': '2027-04', 'end': None}
                self.context.save(self.alice, 'one', f'{group}-{index}', f'{group}-{index}', 0, content)
        page = self.context.list(self.alice, 'one', 'life')
        self.assertEqual(page['counts'], {'coming_up': 23, 'life_now': 23})
        entries = page['entries']
        while page['next_offset'] is not None:
            page = self.context.list(self.alice, 'one', 'life', offset=page['next_offset'])
            entries += page['entries']
        self.assertEqual(len({item['id'] for item in entries}), 46)
        self.assertEqual(self.context.list(self.alice, 'one', 'life', 'orchard')['counts'], {'coming_up': 1, 'life_now': 1})
        for query in ('Spring festival', '2027-04'):
            self.assertEqual(sum(self.context.list(self.alice, 'one', query=query)['counts'].values()), 92)
        for query in ('precision', 'month', 'start', 'end', 'text', 'unknown'):
            self.assertEqual(self.context.list(self.alice, 'one', query=query)['counts'], {}, query)

    def test_schema24_to32_preserves_existing_people_in_additive_lane(self):
        self.store.create_conversation(self.alice, 'retained')
        self.store.close()
        with psycopg.connect(self.dsn) as db:
            remove_personal_context_schema(db)
        migrations = Path(__file__).resolve().parents[2] / 'm2/migrations'
        paths = [path for path in sorted(migrations.glob('*.sql')) if int(path.name.split('_')[0]) >= 25]
        lane = {'from': 24, 'to': 32,
                'migrations': {path.name: sha256(path.read_bytes()).hexdigest() for path in paths},
                'added_tables': ['personal_context', 'personal_context_actions', 'personal_details',
                                 'person_links', 'personal_profile_actions', 'context_update_stages',
                                 'personal_context_consent', 'personal_context_self'], 'added_columns': {}}
        self.assertEqual(migrate(self.dsn, lane), {'schema': 32, 'status': 'migrated'})
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM people').fetchone(), (2,))
            self.assertEqual(db.execute('SELECT id FROM conversations').fetchall(), [('retained',)])
            self.assertEqual(db.execute('SELECT count(*) FROM personal_context_consent').fetchone(), (0,))
            self.assertEqual(db.execute('SELECT count(*) FROM personal_context_self').fetchone(), (0,))
        with self.assertRaisesRegex(ValueError, 'no replay'):
            migrate(self.dsn, lane)

    def test_versions_operations_owner_and_removed_identity(self):
        service = self.context
        self.assertEqual(service.save(self.alice, 'one', 'entry', 'create', 0, fact())['version'], 1)
        self.assertEqual(service.save(self.alice, 'one', 'entry', 'create', 0, fact())['version'], 1)
        self.assertEqual(service.list(self.bob, 'one')['entries'], [])
        with self.assertRaises(ContextConflict):
            service.save(self.bob, 'one', 'entry', 'edit', 1, fact())
        with self.assertRaises(ContextConflict):
            service.save(self.alice, 'one', 'entry', 'create', 0, fact(title='Changed retry'))
        service.save(self.alice, 'one', 'entry', 'edit', 1, fact(title='User correction'))
        with self.assertRaises(ContextConflict):
            service.save(self.alice, 'one', 'entry', 'stale', 1, fact())
        with self.assertRaises(ContextConflict):
            service.remove(self.alice, 'one', 'entry', 1)
        service.remove(self.alice, 'one', 'entry', 2)
        service.remove(self.alice, 'one', 'entry', 2)
        with self.assertRaises(ContextConflict):
            service.save(self.alice, 'one', 'entry', 'create', 0, fact())
        self.assertEqual(service.list(self.alice, 'one')['entries'], [])
        self.assertTrue(self.store.ledger.contains_person_record('alice', 'one', 'entry', 'context_entry'))

    def test_complete_summary_literal_search_and_pages(self):
        for group in ('coming_up', 'goals'):
            for index in range(25):
                key = f'{group}-{index}'
                self.context.save(self.alice, 'one', key, key, 0, fact(group, f'Item {index}'))
        summary = self.context.list(self.alice, 'one')
        self.assertEqual(summary['counts'], {'coming_up': 25, 'goals': 25})
        self.assertEqual(len(summary['entries']), 4)
        page = self.context.list(self.alice, 'one', 'goals')
        tail = self.context.list(self.alice, 'one', 'goals', offset=page['next_offset'])
        self.assertEqual(len(page['entries']) + len(tail['entries']), 25)
        self.assertIsNone(tail['next_offset'])
        self.assertEqual(self.context.list(self.alice, 'one', query='%')['entries'], [])
        self.assertEqual(self.context.list(self.alice, 'one', query='Item 24')['counts'],
                         {'coming_up': 1, 'goals': 1})

    def test_independent_removal_survives_old_database_restore(self):
        self.context.save(self.alice, 'one', 'entry', 'create', 0, fact())
        from m2.chat.personal_context import set_preference, preference
        set_preference(self.store, self.alice, True, 0)
        from m2.people.self_association import association, set_association
        set_association(self.store, self.alice, 'one', 0)
        snapshot = Path(self.directory.name) / 'context-snapshot'
        backup(self.store, snapshot)
        set_association(self.store, self.alice, None, 1)
        set_preference(self.store, self.alice, False, 1)
        self.context.remove(self.alice, 'one', 'entry', 1)
        target = 'kat_person_restore_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(snapshot, dsn, Path(self.directory.name) / 'restored', self.ledger)
            session = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(PersonalContext(restored).list(session, 'one')['entries'], [])
            self.assertEqual(preference(restored, session), {'enabled': False, 'version': 2})
            self.assertEqual(association(restored, session), {'person_id': None, 'version': 2})
            with self.assertRaises(ContextConflict):
                PersonalContext(restored).save(session, 'one', 'entry', 'retry', 0, fact())
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))

    def test_uncertain_dates_do_not_invent_bounds(self):
        value = fact()
        value['date']['start'] = '2026-06-01'
        with self.assertRaises(ValueError):
            content_checked(value)
        value['date'] = {'text': 'about June', 'precision': 'month', 'start': '2026-06', 'end': None}
        self.assertEqual(content_checked(value)['date']['start'], '2026-06')
        value['date']['start'] = '2026-06-01'
        with self.assertRaises(ValueError):
            content_checked(value)
