"""Isolated browser-route parity with authoritative owner-scoped two-chart geometry."""

from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.testclient import TestClient

from m2.birth_flow import BirthFlow
from m2.people import People
from m2.synastry import Synastry
from m2.test_support import DatabaseCase
from m2.web_server import create_app


class ManualSynastryTests(DatabaseCase):
    def test_two_active_sources_match_agent_geometry_without_archiving_or_model_calls(self):
        people = People(self.store)
        flow = BirthFlow(self.store)
        charts = {}
        for person_id, time, longitude in (
            ('a', '04:00', -0.17), ('b', '09:15', -73.9), ('unknown', '', 12.5)):
            people.charts.add_person(self.alice, person_id, f'Synthetic {person_id}')
            data = flow.generate(self.alice, person_id, {
                'request_id': f'generate-{person_id}', 'birth_date': '2001-06-21',
                'birth_time': time, 'time_unknown': not bool(time),
                'birthplace': f'Synthetic place {person_id}', 'place_id': None,
                'provisional': True, 'zone_override': 'UTC',
                'latitude_override': 51.5, 'longitude_override': longitude,
                'fold': None, 'settings': None,
            })
            charts[person_id] = data['chart']['id']
        people.charts.add_person(self.alice, 'missing', 'Synthetic missing natal')
        people.charts.add_person(self.bob, 'bob-only', 'Other owner')
        expected = Synastry(self.store).compare(self.alice, charts['a'], charts['b'],
                                                {charts['a'], charts['b']})
        self.assertEqual(expected['status'], 'supported')
        before = self.store.db.execute('SELECT count(*) AS n FROM turns').fetchone()['n']
        self.store.close()
        with TemporaryDirectory(prefix='kat-manual-pair-') as directory:
            dist = Path(directory) / 'synthetic-dist'
            dist.mkdir()
            (dist / 'index.html').write_text('<!doctype html><title>synthetic pair</title>')
            app = create_app(self.dsn, Path(directory) / 'files', Path(directory) / 'ledger', dist)
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                login = client.post('/api/login', json={'username': 'alice',
                             'password': 'synthetic-password-alice'},
                            headers={'Origin': 'http://127.0.0.1:8765'})
                def view(a, b, **extra):
                    return client.get('/api/synastry', params={
                        'person_a_id': a, 'person_b_id': b, **extra})
                self.assertEqual(view('a', 'a').status_code, 400)
                self.assertEqual(view('a', 'bob-only').status_code, 404)
                self.assertEqual(view('a', 'b', chart_a_id=charts['unknown']).status_code, 400)
                self.assertEqual(view('a', 'missing').json()['status'], 'no_active_natal')
                self.assertEqual(view('a', 'unknown').json()['status'],
                                 'unsupported_uncertain_birth_time_or_non_natal_chart')
                result = view('a', 'b')
                self.assertEqual(result.status_code, 200)
                comparison = result.json()
                for key, value in expected.items():
                    self.assertEqual(comparison[key], value, key)
                self.assertEqual([item['id'] for item in comparison['positions_a'][:3]],
                                 ['sun', 'moon', 'mercury'])
                self.assertGreaterEqual(len(comparison['positions_b']), 10)
                saved = client.post('/api/advanced-results', json={
                    'id': 'manual-overlay', 'person_id': 'a', 'technique': 'synastry_overlay',
                    'parameters': {'person_b_id': 'b'}}, headers={
                    'Origin': 'http://127.0.0.1:8765', 'X-Kat-CSRF': login.json()['csrf']})
                self.assertEqual(saved.status_code, 201)
                self.assertEqual(saved.json()['house_overlays'], comparison['house_overlays'])
                self.assertEqual(client.get('/api/advanced-results', params={
                    'person_id': 'a', 'technique': 'synastry_overlay'}).json()['results'][0]['id'],
                    'manual-overlay')
                def regenerate(store, _):
                    session = store.authenticate('alice', 'synthetic-password-alice')
                    return BirthFlow(store).generate(session, 'a', {
                        'request_id': 'generate-a-replacement', 'birth_date': '2002-06-21',
                        'birth_time': '04:00', 'time_unknown': False,
                        'birthplace': 'Synthetic replacement', 'place_id': None,
                        'provisional': True, 'zone_override': 'UTC',
                        'latitude_override': 51.5, 'longitude_override': -0.17,
                        'fold': None, 'settings': None,
                    })
                new = client.portal.call(app.state.runtime.call, regenerate)
                latest = view('a', 'b').json()
                self.assertEqual(latest['chart_a_id'], new['chart']['id'])
                self.assertNotEqual(latest['chart_a_id'], comparison['chart_a_id'])
                self.assertEqual(latest['chart_b_id'], comparison['chart_b_id'])
                self.assertNotEqual(latest['positions_a'], comparison['positions_a'])
                archived = client.get('/api/advanced-results/manual-overlay').json()
                self.assertEqual(archived['source_status'], 'historical')
                self.assertEqual(archived['result']['house_overlays'], comparison['house_overlays'])
                self.assertEqual(comparison['chart_a_id'], charts['a'])  # Old snapshot is immutable.
                self.assertEqual(client.post('/api/synastry', json={}, headers={
                    'Origin': 'http://127.0.0.1:8765',
                    'X-Kat-CSRF': login.json()['csrf']}).status_code, 405)
                self.assertEqual(app.state.runtime.store.db.execute(
                    'SELECT count(*) AS n FROM turns').fetchone()['n'], before)
