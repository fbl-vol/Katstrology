"""Directory identities, complete ranking/history and owner isolation on synthetic storage."""
from unittest.mock import patch

from psycopg.types.json import Jsonb

from m2.calculation.advanced import Advanced
from m2.people.birth_flow import BirthFlow
from m2.people.chart_library import ChartLibrary, TECHNIQUES, preview
from m2.people.people import People
from tests.support.database import DatabaseCase


class ChartLibraryTests(DatabaseCase):
    def fixture(self):
        for session in (self.alice, self.bob):
            People(self.store).charts.add_person(session, 'one', 'Synthetic library')
        for pid in ('one', 'two'):
            if pid == 'two':
                People(self.store).charts.add_person(self.alice, pid, 'Synthetic partner')
            BirthFlow(self.store).generate(self.alice, pid, {
                'request_id': 'source-' + pid, 'birth_date': '2001-06-21',
                'birth_time': '04:00', 'time_unknown': False,
                'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
                'provisional': True, 'zone_override': None, 'latitude_override': None,
                'longitude_override': None, 'fold': None, 'settings': None})
        self.library = ChartLibrary(self.store)
        self.owner = self.store.owner(self.alice)
        self.chart = People(self.store).active_chart_id(self.alice, 'one')
        self.partner_chart = People(self.store).active_chart_id(self.alice, 'two')

    def insert_result(self, result_id, technique='planetary_return', body='venus', pair=False):
        self.store.db.execute('''INSERT INTO advanced_results
            (owner_id,id,technique,chart_a_id,chart_b_id,method_version,parameters,result,created_at)
            VALUES (%s,%s,%s,%s,%s,'synthetic-library-v1',%s,%s,'2026-01-01T00:00:00Z')''',
            (self.owner, result_id, technique, self.chart, self.partner_chart if pair else None,
             Jsonb({'body': body}), Jsonb({'status': 'supported', 'positions': [], 'events': [],
                 'window_utc': ['2030-01-01T00:00:00Z', '2030-02-01T00:00:00Z']})))

    def test_complete_summary_ties_variants_and_keyset_history(self):
        self.fixture()
        for index in range(43):
            self.insert_result(f'result-{index:03d}', body='saturn' if index % 2 else 'venus')
        self.insert_result('earlier-type', 'mc_transit')
        with patch.object(Advanced, 'calculate', side_effect=AssertionError('directory calculated')):
            entries = {e['technique']: e for e in self.library.summary(self.alice, 'one')['entries']}
            self.assertEqual(set(entries), {'natal', 'planetary_return', 'mc_transit'})
            self.assertEqual(entries['planetary_return']['count'], 43)
            self.assertEqual(entries['planetary_return']['variants'], 2)
            self.assertEqual(entries['planetary_return']['representative']['id'], 'result-042')
            ids, before = [], None
            while True:
                page = self.library.history(self.alice, 'one', 'planetary_return', before)
                self.assertLessEqual(len(page['entries']), 20)
                ids.extend(e['id'] for e in page['entries'])
                before = page['next_before']
                if not before:
                    break
            self.assertEqual(ids, [f'result-{index:03d}' for index in reversed(range(43))])
        self.assertEqual(self.library.summary(self.bob, 'one')['entries'], [])
        with self.assertRaises(KeyError):
            self.library.history(self.bob, 'one', 'planetary_return', 'result-020')
        with self.assertRaises(KeyError):
            self.library.history(self.alice, 'one', 'mc_transit', 'result-020')
        with self.assertRaises(ValueError):
            self.library.history(self.alice, 'one', 'invented')

    def test_active_natal_is_not_latest_chart_page_and_sources_stay_immutable(self):
        self.fixture()
        original = self.store.db.execute('SELECT result FROM charts WHERE owner_id=%s AND id=%s',
                                         (self.owner, self.chart)).fetchone()['result']
        for index in range(25):
            self.store.db.execute('''INSERT INTO charts
                (owner_id,id,person_id,birth_id,profile_id,profile_revision,result,engine_version)
                SELECT owner_id,%s,person_id,birth_id,profile_id,profile_revision,result,engine_version
                FROM charts WHERE owner_id=%s AND id=%s''', (f'newer-{index:03d}', self.owner, self.chart))
        person = People(self.store).get(self.alice, 'one')
        self.assertEqual(len(person['charts']), 21)
        self.assertNotIn(self.chart, [c['id'] for c in person['charts'][:20]])
        self.assertEqual(person['charts'][-1]['id'], self.chart)
        self.assertEqual(person['charts'][-1]['result'], original)
        natal = self.library.summary(self.alice, 'one')['entries'][0]
        self.assertEqual(natal['count'], 26)
        self.assertEqual(natal['representative']['id'], self.chart)
        self.assertEqual(natal['representative']['date'], original['birth']['wall_time'])
        self.assertEqual(natal['representative']['preview']['positions'][0]['longitude_degrees'],
                         original['natal']['positions'][0]['longitude_degrees'])
        first = self.library.history(self.alice, 'one', 'natal')
        second = self.library.history(self.alice, 'one', 'natal', first['next_before'])
        self.assertEqual(len(first['entries']) + len(second['entries']), 26)
        self.assertIsNone(second['next_before'])
        self.assertEqual(self.store.db.execute('SELECT result FROM charts WHERE owner_id=%s AND id=%s',
                        (self.owner, self.chart)).fetchone()['result'], original)
        self.assertEqual(People(self.store).active_chart_id(self.alice, 'one'), self.chart)

    def test_all_persisted_techniques_and_both_relationship_participants(self):
        self.fixture()
        for technique in TECHNIQUES:
            self.insert_result('saved-' + technique, technique,
                               pair=technique in ('midpoint_composite', 'uncorrected_davison'))
        entries = self.library.summary(self.alice, 'one')['entries']
        self.assertEqual({e['technique'] for e in entries}, {'natal', *TECHNIQUES})
        partner_entries = self.library.summary(self.alice, 'two')['entries']
        self.assertEqual({e['technique'] for e in partner_entries},
                         {'natal', 'midpoint_composite', 'uncorrected_davison'})
        pair = self.library.history(self.alice, 'two', 'midpoint_composite')['entries'][0]
        self.assertEqual(pair['id'], 'saved-midpoint_composite')
        self.assertEqual([p['name'] for p in pair['people']], ['Synthetic library', 'Synthetic partner'])

    def test_preview_keeps_event_counts_and_does_not_invent_geometry(self):
        events = [{'instant_utc': f'2026-01-0{n}T00:00:00Z'} for n in range(1, 6)]
        thumbnail = preview({'events': events}, 'lunar_return')
        self.assertEqual(thumbnail['kind'], 'timeline')
        self.assertEqual(thumbnail['total'], 5)
        self.assertEqual(len(thumbnail['events']), 3)
        self.assertEqual(preview({'events': []}, 'mc_transit')['total'], 0)
        self.assertEqual(preview({'natal': {'positions': []}}, 'natal')['kind'], 'unavailable')
