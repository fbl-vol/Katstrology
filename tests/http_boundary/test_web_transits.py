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

from m2.people.birth_flow import BirthFlow
from m2.archive.deletion import Tombstones
from m2.operations.local_fixture import ROOT
from m2.people.people import People
from m2.calculation.periods import Periods
from m2.chat.selected_results import selected_evidence
from m2.people.saved_timing import source_event
from m2.archive.revisions import correct
from m2.archive.store import Store
from tests.support.database import test_fixture_dsn
from m2.http_boundary.app import create_app


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

    def test_exploration_is_owned_read_only_and_uses_saved_profile(self):
        from unittest.mock import patch
        from m2.calculation.charts import Charts
        from tests.calculation.test_exploration import saved_chart
        from tests.calculation.test_natal import SETTINGS

        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            session = store.authenticate('alice', 'synthetic-password-alice')
            charts = Charts(store)
            chart = charts.get_chart(session, self.chart_id)
            result = chart['result']
            result['natal'] = saved_chart({'sun': 0, 'moon': 90, 'mars': 180,
                                         'saturn': 270})['result']['natal']
            store.db.execute('UPDATE charts SET result=%s WHERE id=%s',
                             (psycopg.types.json.Jsonb(result), self.chart_id))
            charts.add_profile(session, chart['profile_id'], {
                **SETTINGS, 'aspects': ['conjunction'], 'orbs': {'conjunction': 1}})
            store.db.execute("UPDATE charts SET result=result - 'natal' WHERE id=%s",
                             (self.legacy_id,))
            before = store.db.execute('SELECT result::text FROM charts WHERE id=%s',
                                      (self.chart_id,)).fetchone()['result']
        # TestClient's base URL is only ASGI host validation, never a live listener.
        with TestClient(create_app(self.dsn, self.files, self.ledger, self.dist),
                        base_url='http://127.0.0.1:8765') as client:
            url = f'/api/charts/{self.chart_id}/exploration'
            self.assertEqual(client.get(url).status_code, 401)
            for owner, expected in (('bob', 404), ('alice', 200)):
                client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                    json={'username': owner, 'password': f'synthetic-password-{owner}'})
                with patch('swisseph.calc_ut', side_effect=AssertionError('read recalculated')):
                    response = client.get(url)
                self.assertEqual(response.status_code, expected)
            self.assertEqual(len(response.json()['patterns']), 5)
            self.assertEqual(client.get(f'/api/charts/{self.legacy_id}/exploration').json()['reason'],
                             'legacy_chart')
            self.assertEqual(client.post(url, json={}, headers={
                'Origin': 'http://127.0.0.1:8765',
                'X-Kat-CSRF': client.get('/api/session').json()['csrf']}).status_code, 405)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            self.assertEqual(store.db.execute('SELECT result::text FROM charts WHERE id=%s',
                (self.chart_id,)).fetchone()['result'], before)
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns').fetchone()['n'], 0)

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

    def test_period_pages_all_saved_sources_and_never_claims_complete_ephemeris_coverage(self):
        payload = {'person_id': 'one', 'technique': 'solar_return',
                   'parameters': {'year': 2026, 'latitude': 55.68, 'longitude': 12.57}}
        query = {'person_id': 'one', 'chart_id': self.chart_id,
                 'start': '2026-01-01', 'end': '2027-01-01', 'offset': '0'}
        with TestClient(create_app(self.dsn, self.files, self.ledger, self.dist),
                        base_url='http://127.0.0.1:8765') as client:
            self.assertEqual(client.get('/api/advanced-results/period', params=query).status_code, 401)
            client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                        json={'username': 'bob', 'password': 'synthetic-password-bob'})
            self.assertEqual(client.get('/api/advanced-results/period', params=query).status_code, 404)
            client.post('/api/login', headers={'Origin': 'http://127.0.0.1:8765'},
                        json={'username': 'alice', 'password': 'synthetic-password-alice'})
            empty = client.get('/api/advanced-results/period', params=query).json()
            self.assertEqual(empty['coverage'], 'no_saved_calculations')
            self.assertEqual(client.get('/api/advanced-results/period', params={
                **query, 'end': '2028-01-01'}).status_code, 400)
            for index in range(16):
                saved = client.post('/api/advanced-results', json={**payload, 'id': f'return-{index}'},
                    headers={'Origin': 'http://127.0.0.1:8765',
                             'X-Kat-CSRF': client.get('/api/session').json()['csrf']})
                self.assertEqual(saved.status_code, 201)
            first = client.get('/api/advanced-results/period', params=query).json()
            self.assertEqual(len(first['entries']), 10)
            self.assertEqual(first['coverage'], 'partial_saved_results')
            second = client.get('/api/advanced-results/period', params={
                **query, 'offset': str(first['next_offset'])}).json()
            self.assertEqual(len(second['entries']), 6)
            self.assertIsNone(second['next_offset'])
            self.assertEqual(len({row['id'] for row in first['entries'] + second['entries']}), 16)
            self.assertEqual(client.get('/api/advanced-results/period', params={
                **query, 'chart_id': self.legacy_id}).status_code, 404)
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns').fetchone()['n'], 0)

    def test_half_open_saved_windows_do_not_displace_overlapping_periods(self):
        from m2.calculation.advanced import Advanced
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            alice = store.authenticate('alice', 'synthetic-password-alice')
            advanced = Advanced(store)
            for identifier, start, end in (
                ('ends-at-start', '2026-01-01', '2026-03-01'),
                ('overlapping', '2026-03-01', '2026-04-01'),
                ('starts-at-end', '2026-04-01', '2026-05-01'),
            ):
                saved = advanced.save(alice, identifier, 'one', 'lunar_return', {
                    'start_utc': f'{start}T00:00:00+00:00',
                    'end_utc': f'{end}T00:00:00+00:00',
                    'latitude': 55.68, 'longitude': 12.57})
                self.assertEqual(saved['status'], 'supported')
            page = Periods(store).read(alice, 'one', self.chart_id,
                                       '2026-03-01', '2026-04-01')
            self.assertEqual([entry['id'] for entry in page['entries']], ['overlapping'])
            self.assertEqual(page['coverage'], 'saved_results_only')
            self.assertIsNone(page['next_offset'])
            self.assertTrue(all('2026-03-01' <= event['instant_utc'][:10] < '2026-04-01'
                                for event in page['entries'][0]['events']))

    def test_persisted_lunations_maxima_and_symbolic_dates_keep_distinct_locators(self):
        from m2.calculation.advanced import Advanced
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            alice = store.authenticate('alice', 'synthetic-password-alice')
            advanced = Advanced(store)
            sky = advanced.save(alice, 'saved-sky', 'one', 'actual_lunations_eclipses', {
                'start_utc': '2024-03-01T00:00:00+00:00',
                'end_utc': '2024-06-01T00:00:00+00:00',
                'natal_target': 'sun', 'aspect': 'conjunction'})
            arc = advanced.save(alice, 'saved-arc', 'one', 'true_solar_arc', {
                'effective_utc': '2024-04-05T00:00:00+00:00'})
            progression = advanced.save(alice, 'saved-progressed', 'one', 'secondary_progression', {
                'effective_utc': '2024-04-05T00:00:00+00:00'})
            self.assertEqual((sky['status'], arc['status'], progression['status']),
                             ('supported', 'supported', 'supported'))
            self.assertTrue(sky['lunations'])
            self.assertTrue(sky['eclipses'])
            period = Periods(store).read(
                alice, 'one', self.chart_id, '2024-04-01', '2024-05-01')
            entries = {row['id']: row for row in period['entries']}
            sky_points = entries['saved-sky']['events']
            self.assertEqual(len(sky_points), sum('2024-04-01' <= item['instant_utc'][:10] < '2024-05-01'
                for item in sky['lunations']) + sum('2024-04-01' <= item['maximum_utc'][:10] < '2024-05-01'
                for item in sky['eclipses']))
            maxima = [item for item in sky_points if item['kind'] == 'eclipse']
            self.assertTrue(maxima)
            maximum = maxima[0]
            self.assertEqual(source_event('actual_lunations_eclipses', sky, maximum['index'])[1]['maximum_utc'],
                             maximum['instant_utc'])
            self.assertNotEqual(maximum['instant_utc'], maximum['linked_syzygy_utc'])
            self.assertEqual(entries['saved-arc']['events'][0]['index'], None)
            self.assertEqual(entries['saved-progressed']['events'][0]['instant_utc'],
                             '2024-04-05T00:00:00+00:00')
            store.create_conversation(alice, 'sky-discussion')
            self.assertTrue(store.begin(alice, 'sky-discussion', 'selected-maximum', 'What does this mean?',
                selected_people=[{'person_id': 'one', 'chart_id': self.chart_id}],
                selected_result={'result_id': 'saved-sky', 'event_index': maximum['index']}))
            facts = selected_evidence(store, alice, 'sky-discussion', 'selected-maximum')
            self.assertEqual(facts['point_kind'], 'eclipse')
            self.assertEqual(facts['facts']['maximum_utc'], maximum['instant_utc'])
            self.assertEqual(facts['facts']['natal_target'], 'sun')

    def test_selected_saved_crossing_is_owner_fenced_and_committed_exactly_at_ack(self):
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            alice = store.authenticate('alice', 'synthetic-password-alice')
            bob = store.authenticate('bob', 'synthetic-password-bob')
            from m2.calculation.advanced import Advanced
            result = Advanced(store).save(alice, 'selected-return', 'one', 'solar_return',
                {'year': 2026, 'latitude': 55.68, 'longitude': 12.57})
            self.assertEqual(result['status'], 'supported')
            selection = [{'person_id': 'one', 'chart_id': self.chart_id}]
            store.create_conversation(alice, 'selected-thread')
            choice = {'result_id': 'selected-return', 'event_index': 0}
            self.assertRaises(KeyError, store.begin, bob, 'selected-thread', 'foreign-turn',
                              'What does this crossing mean?', selected_people=selection,
                              selected_result=choice)
            self.assertRaises(ValueError, store.begin, alice, 'selected-thread', 'bad-index',
                              'Meaning?', selected_people=selection,
                              selected_result={**choice, 'event_index': 100})
            self.assertTrue(store.begin(alice, 'selected-thread', 'selected-turn',
                'What does this crossing mean?', selected_people=selection,
                selected_result=choice))
            evidence = selected_evidence(store, alice, 'selected-thread', 'selected-turn')
            self.assertEqual(evidence['source_chart_ids'], [self.chart_id])
            self.assertEqual(evidence['facts']['instant_utc'], result['events'][0]['instant_utc'])
            self.assertEqual(store.read_turn(alice, 'selected-thread', 'selected-turn')['events'][0]
                             ['payload']['selected_result'], choice)
            self.assertFalse(store.begin(alice, 'selected-thread', 'selected-turn',
                'What does this crossing mean?', selected_people=selection,
                selected_result=choice))
            self.assertRaises(ValueError, store.begin, alice, 'selected-thread', 'selected-turn',
                              'What does this crossing mean?', selected_people=selection,
                              selected_result={**choice, 'event_index': None})
            self.assertRaises(KeyError, selected_evidence, store, bob,
                              'selected-thread', 'selected-turn')

    def test_selected_result_rejects_invalidated_birth_source_before_ack(self):
        from m2.calculation.advanced import Advanced
        with Store(self.dsn, self.files, Tombstones(self.ledger)) as store:
            alice = store.authenticate('alice', 'synthetic-password-alice')
            store.create_conversation(alice, 'birth-source')
            store.begin(alice, 'birth-source', 'birth-details', 'Synthetic birth details')
            store.append(alice, 'birth-source', 'birth-details', 'complete', {})
            saved = Advanced(store).save(alice, 'saved-linked', 'one',
                'solar_return', {'year': 2026, 'latitude': 55.68, 'longitude': 12.57})
            self.assertEqual(saved['status'], 'supported')
            # Simulate a legacy turn-sourced birth on an otherwise generated
            # synthetic chart; its immutable calculation is never recomputed.
            store.db.execute('''
                UPDATE charts SET result=jsonb_set(jsonb_set(result,
                    '{birth,source_conversation_id}',to_jsonb(%s::text)),
                    '{birth,source_turn_id}',to_jsonb(%s::text))
                WHERE owner_id=%s AND id=%s
            ''', ('birth-source', 'birth-details', alice.owner_id, self.chart_id))
            correct(store, alice, 'birth-source', 'corrected-birth', 'birth-details',
                    'correct', 'This birth time is no longer reliable.')
            store.create_conversation(alice, 'discussion')
            with self.assertRaisesRegex(ValueError, 'invalidated source'):
                store.begin(alice, 'discussion', 'not-acknowledged', 'Discuss this crossing',
                    selected_people=[{'person_id': 'one', 'chart_id': self.chart_id}],
                    selected_result={'result_id': 'saved-linked', 'event_index': 0})
            self.assertEqual(store.db.execute('SELECT count(*) AS n FROM turns '
                "WHERE id='not-acknowledged'").fetchone()['n'], 0)

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
