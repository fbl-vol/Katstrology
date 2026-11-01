"""Authenticated real ASGI transit view; no live distribution or listener."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient

from m2.birth_flow import BirthFlow
from m2.deletion import Tombstones
from m2.local_fixture import ROOT
from m2.people import People
from m2.store import Store
from m2.test_support import test_fixture_dsn
from m2.web_server import create_app


class TransitHttpTests(unittest.TestCase):
    def setUp(self):
        self.admin_dsn = test_fixture_dsn()
        self.name = 'kat_web_test_' + uuid4().hex[:12]
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        self.dsn = make_conninfo(self.admin_dsn, dbname=self.name)
        self.directory = TemporaryDirectory(prefix='kat-transit-http-', dir=ROOT / '.local')
        self.files = Path(self.directory.name) / 'files'
        self.ledger = Path(self.directory.name) / 'journal.jsonl'
        self.dist = Path(self.directory.name) / 'dist'
        self.dist.mkdir()
        (self.dist / 'index.html').write_text('<title>isolated test</title>')
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            store.register_local('alice', 'synthetic-password-alice')
            store.register_local('bob', 'synthetic-password-bob')
            session = store.authenticate('alice', 'synthetic-password-alice')
            people = People(store)
            people.charts.add_person(session, 'one', 'Owned person')
            self.chart_id = BirthFlow(store).generate(session, 'one', {
                'request_id': 'synthetic-generation', 'birth_date': '2001-06-21',
                'birth_time': '04:00', 'time_unknown': False,
                'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
                'provisional': True, 'zone_override': None, 'latitude_override': None,
                'longitude_override': None, 'fold': None, 'settings': None,
            })['chart']['id']
            people.charts.add_person(session, 'legacy', 'Historical chart only')
            legacy_birth = people.add_birth(session, 'legacy', {'mode': 'exact', 'zone': 'UTC',
                                                                'wall_time': '2001-06-21T04:00:00'})
            self.legacy_id = people.create_chart(session, 'legacy', legacy_birth,
                                                 'natal-default', 1)['id']

    def tearDown(self):
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.name)))
        self.directory.cleanup()

    def test_advanced_return_is_owner_scoped_persisted_and_not_a_model_send(self):
        payload = {'id': 'synthetic-return-http', 'person_id': 'one',
                   'technique': 'solar_return',
                   'parameters': {'year': 2026, 'latitude': 55.68, 'longitude': 12.57}}
        with TestClient(create_app(self.dsn, self.files, self.ledger, self.dist),
                        base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(client.post('/api/advanced-results', json=payload,
                headers={'Origin': 'http://127.0.0.1:8765'}).status_code, 401)
            bob = client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                json={'username': 'bob', 'password': 'synthetic-password-bob'}).json()
            headers = {'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': bob['csrf']}
            self.assertEqual(client.post('/api/advanced-results', json=payload,
                                         headers=headers).status_code, 404)
            alice = client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                json={'username': 'alice', 'password': 'synthetic-password-alice'}).json()
            headers['X-Kat-CSRF'] = alice['csrf']
            self.assertEqual(client.post('/api/advanced-results', json=payload).status_code, 403)
            saved = client.post('/api/advanced-results', json=payload, headers=headers)
            self.assertEqual(saved.status_code, 201)
            self.assertEqual(saved.json()['status'], 'supported')
            self.assertEqual(client.post('/api/advanced-results', json=payload,
                                         headers=headers).status_code, 200)
            self.assertEqual(client.get('/api/advanced-results/synthetic-return-http').json()['result']['events'],
                             saved.json()['events'])
            self.assertEqual(client.post('/api/advanced-results', json={**payload,
                'parameters': {**payload['parameters'], 'year': 2027}},
                headers=headers).status_code, 400)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns').fetchone()['n'], 0)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM advanced_results').fetchone()['n'], 1)

    def test_clock_endpoint_is_authenticated_read_only_and_zone_qualified(self):
        instant = datetime(2026, 1, 1, 1, 15, 42, tzinfo=timezone.utc)
        with TestClient(create_app(self.dsn, self.files, self.ledger, self.dist,
                                   clock=lambda: instant),
                        base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(client.get('/api/clock?zone=UTC').status_code, 401)
            client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                        json={'username': 'alice', 'password': 'synthetic-password-alice'})
            result = client.get('/api/clock?zone=America%2FLos_Angeles')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['instant_utc'], instant.isoformat())
            self.assertEqual(result.json()['reporting']['date'], '2025-12-31')
            self.assertEqual(result.json()['reporting']['time'], '17:15:42')
            self.assertIn('not_verified_location', result.json()['reporting']['zone_source'])
            self.assertEqual(client.get('/api/clock?zone=???').status_code, 400)
            self.assertEqual(client.get('/api/clock?zone=UTC&zone=UTC').status_code, 400)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns').fetchone()['n'], 0)

    def test_real_get_owner_fence_bad_inputs_and_no_archive_write(self):
        query = {'date': '2024-03-20', 'time': '03:06', 'zone': 'Europe/Copenhagen',
                 'occurrence': 'unspecified', 'mode': 'natal_transits', 'person_id': 'one'}
        with TestClient(create_app(self.dsn, self.files, self.ledger, self.dist),
                        base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(client.get('/api/transit-view', params=query).status_code, 401)
            client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                        json={'username': 'bob', 'password': 'synthetic-password-bob'})
            self.assertEqual(client.get('/api/transit-view', params=query).status_code, 404)
            client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                        json={'username': 'alice', 'password': 'synthetic-password-alice'})
            supported = client.get('/api/transit-view', params=query)
            self.assertEqual(supported.status_code, 200)
            self.assertEqual(supported.json()['chart_id'], self.chart_id)
            self.assertEqual(supported.json()['status'], 'supported')
            self.assertEqual(client.get('/api/transit-view', params={**query, 'mode': 'sky'}).status_code, 400)
            self.assertEqual(client.get('/api/transit-view', params={**query, 'chart_id': self.legacy_id}).status_code, 400)
            self.assertEqual(client.get('/api/transit-view', params={**query, 'person_id': 'legacy'}).json()['status'],
                             'no_active_natal')
            self.assertEqual(client.get('/api/transit-view', params={**query, 'zone': '???'}).status_code, 400)
            self.assertEqual(client.get('/api/transit-view', params={**query, 'date': '2100-01-01'}).status_code, 400)
            sky = {key: value for key, value in query.items() if key != 'person_id'}
            sky['mode'] = 'sky'
            gap = client.get('/api/transit-view', params={**sky, 'date': '2024-03-31', 'time': '02:30'})
            self.assertEqual(gap.json(), {'error': 'nonexistent_local_time'})
            repeated = {**sky, 'date': '2024-10-27', 'time': '02:30'}
            self.assertEqual(client.get('/api/transit-view', params=repeated).json(),
                             {'error': 'choose_dst_occurrence'})
            earlier = client.get('/api/transit-view', params={**repeated, 'occurrence': 'earlier'}).json()
            later = client.get('/api/transit-view', params={**repeated, 'occurrence': 'later'}).json()
            self.assertEqual((earlier['instant_utc'], later['instant_utc']),
                             ('2024-10-27T00:30:00+00:00', '2024-10-27T01:30:00+00:00'))
            self.assertEqual(client.get('/api/transit-view?date=x&date=y').status_code, 400)
            self.assertEqual(client.get('/api/transit-view', params=query,
                                        headers={'Host': 'foreign.example'}).status_code, 403)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            owner = store.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns WHERE owner_id=%s',
                                              (store.owner(owner),)).fetchone()['n'], 0)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM charts WHERE owner_id=%s',
                                              (store.owner(owner),)).fetchone()['n'], 2)
