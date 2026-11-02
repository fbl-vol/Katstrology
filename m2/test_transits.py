"""Synthetic natal and ephemeris-backed transit calculations (no live inference)."""

from datetime import datetime, timedelta, timezone
import json

import swisseph as swe

from m2.agent_reads import execute
from m2.gateway import run_turn
from m2.provider_model import ResponsesModel
from m2.test_agent_reads import FakeBridge, ScriptedTransport
from m2.birth_flow import BirthFlow
from m2.people import People
from m2.test_support import DatabaseCase
from m2.transits import Transits
from m2.core_calc import aspect_separation


UTC = timezone.utc


class TransitTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic sky reader')
        self.chart = BirthFlow(self.store).generate(self.alice, self.person['id'], {
            'request_id': 'synthetic-transit-chart', 'birth_date': '2024-03-20',
            'birth_time': '03:06', 'time_unknown': False,
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': None,
        })['chart']
        self.transits = Transits(self.store)
        self.selected = {self.chart['id']}

    def test_moon_to_natal_sun_refined_crossing_and_snapshot_use_declared_profile(self):
        start = datetime(2024, 4, 1, tzinfo=UTC)
        result = self.transits.events(self.alice, self.chart['id'], start,
                                     start + timedelta(days=7), 'moon', 'sun', 'square')
        self.assertEqual(result['status'], 'supported')
        self.assertTrue(result['events'])
        self.assertEqual(result['birth_time_status'], 'exact_supplied_time_not_verified')
        for event in result['events']:
            instant = datetime.fromisoformat(event['instant_utc'])
            jd = swe.julday(instant.year, instant.month, instant.day,
                            instant.hour + instant.minute / 60 + instant.second / 3600)
            position = swe.calc_ut(jd, swe.MOON, swe.FLG_SWIEPH)[0][0]
            natal_sun = next(p['longitude_degrees'] for p in self.chart['result']['natal']['positions']
                             if p['id'] == 'sun')
            self.assertLess(aspect_separation(position, natal_sun, 'square'), 0.03)
            snapshot = self.transits.snapshot(self.alice, self.chart['id'], instant,
                                             'moon', 'sun', 'square')
            self.assertTrue(snapshot['in_orb'])
            self.assertLess(snapshot['orb_degrees'], 0.03)
            self.assertEqual(snapshot['ephemeris_sha256'], self.chart['result']['natal']['ephemeris_sha256'])

    def test_two_year_moon_contacts_match_adjacent_windows_without_an_event_cap(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        midpoint = start + timedelta(days=366)
        end = start + timedelta(days=732)
        def contacts(begin, finish):
            result = self.transits.events(self.alice, self.chart['id'], begin, finish,
                                          'moon', 'sun', 'square')
            self.assertEqual(result['status'], 'supported')
            return [item['instant_utc'] for item in result['events']]
        whole = contacts(start, end)
        halves = contacts(start, midpoint) + contacts(midpoint, end)
        self.assertGreater(len(whole), 40)
        self.assertEqual(whole, halves)

    def test_ingress_and_station_have_expected_synthetic_calendar_anchor(self):
        ingress = self.transits.sky_events(self.alice, self.chart['id'],
            datetime(2024, 3, 19, tzinfo=UTC), datetime(2024, 3, 22, tzinfo=UTC),
            'sun', 'ingress')
        self.assertEqual(len(ingress['events']), 1)
        event = ingress['events'][0]
        self.assertEqual(event['sign_entered'], 0)
        self.assertEqual(event['target_degrees'], 0)
        # Independent USNO 2024 seasons table: March equinox 03:06 UTC.
        # https://aa.usno.navy.mil/calculated/seasons?year=2024&tz=0
        self.assertLess(abs(datetime.fromisoformat(event['instant_utc']) -
                            datetime(2024, 3, 20, 3, 6, tzinfo=UTC)), timedelta(minutes=5))
        station = self.transits.sky_events(self.alice, self.chart['id'],
            datetime(2024, 3, 30, tzinfo=UTC), datetime(2024, 4, 4, tzinfo=UTC),
            'mercury', 'station')
        self.assertEqual(len(station['events']), 1)
        self.assertEqual(station['events'][0]['direction_after'], 'retrograde')
        self.assertEqual(datetime.fromisoformat(station['events'][0]['instant_utc']).date().isoformat(),
                         '2024-04-01')

    def test_model_requested_snapshot_is_committed_and_tied_to_selected_chart(self):
        self.store.create_conversation(self.alice, 'sky-thread')
        argument = {'chart_id': self.chart['id'], 'instant_utc': '2024-04-01T12:00:00+00:00',
                    'transit_body': 'moon', 'natal_body': 'sun', 'aspect': 'square'}
        call = {'type': 'function_call', 'id': 'fc_sky', 'call_id': 'call_sky',
                'name': 'get_transit_snapshot', 'arguments': json.dumps(argument)}
        transport = ScriptedTransport()
        transport.script = [
            [({'type': 'response.completed', 'response': {'output': [call]}}, 'fixture')],
            [({'type': 'response.output_text.delta', 'delta': 'Synthetic sky reading.'}, 'fixture'),
             ({'type': 'response.completed', 'response': {'output': []}}, 'fixture')],
        ]
        model = ResponsesModel(FakeBridge(transport), 'alice', 'synthetic-response-model')
        result = run_turn(self.store, self.alice, 'sky-thread', 'requested',
            'Describe the synthetic transit', model, lambda _: None,
            selected_people=[{'person_id': self.person['id'], 'chart_id': self.chart['id']}],
            model_provider='chatgpt_plan', model_slug='synthetic-response-model')
        self.assertEqual(result, 'complete')
        value = json.loads(transport.calls[1]['input'][-1]['output'])
        self.assertEqual(value['chart_id'], self.chart['id'])
        self.assertEqual(value['natal_body_id'], 'sun')
        events = self.store.read_turn(self.alice, 'sky-thread', 'requested')['events']
        recorded = next(e for e in events if e['kind'] == 'tool_result' and
                        e['payload']['name'] == 'get_transit_snapshot')
        self.assertEqual(recorded['payload']['chart_id'], self.chart['id'])
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS value FROM chart_evidence WHERE owner_id=%s
                AND conversation_id=%s AND turn_id=%s AND event_sequence=%s
        ''', ('alice', 'sky-thread', 'requested', recorded['sequence'])).fetchone()['value'], 1)

    def test_unknown_birth_time_allows_only_independent_sky_not_natal_transit(self):
        other = People(self.store).add(self.alice, 'Synthetic unknown time')
        chart = BirthFlow(self.store).generate(self.alice, other['id'], {
            'request_id': 'synthetic-unknown-transit', 'birth_date': '2024-03-20',
            'birth_time': '', 'time_unknown': True,
            'birthplace': 'Copenhagen, Capital Region, Denmark', 'place_id': '2618425',
            'provisional': True, 'zone_override': None, 'latitude_override': None,
            'longitude_override': None, 'fold': None, 'settings': None,
        })['chart']
        instant = datetime(2024, 4, 1, tzinfo=UTC)
        self.assertEqual(self.transits.snapshot(self.alice, chart['id'], instant,
            'sun', 'sun', 'conjunction')['status'],
            'unsupported_uncertain_birth_time_or_non_natal_chart')
        sky = self.transits.sky_events(self.alice, chart['id'],
            datetime(2024, 3, 19, tzinfo=UTC), datetime(2024, 3, 22, tzinfo=UTC),
            'sun', 'ingress')
        self.assertEqual(sky['birth_time_status'], 'natal_positions_unsupported_sky_only')
        self.assertEqual(sky['events'][0]['sign_entered'], 0)

    def test_selected_chart_owner_and_time_horizon_fail_closed(self):
        args = {'chart_id': self.chart['id'], 'instant_utc': '2024-04-01T12:00:00+00:00',
                'transit_body': 'sun', 'natal_body': 'sun', 'aspect': 'conjunction'}
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'get_transit_snapshot', args, set())
        with self.assertRaises(KeyError):
            self.transits.snapshot(self.bob, self.chart['id'],
                                   datetime(2024, 4, 1, tzinfo=UTC), 'sun', 'sun', 'conjunction')
        response = execute(self.store, self.alice, 'get_transit_snapshot', args, self.selected)
        self.assertEqual(response['chart_id'], self.chart['id'])
        with self.assertRaisesRegex(ValueError, 'at most 732 days'):
            self.transits.events(self.alice, self.chart['id'],
                datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 4, tzinfo=UTC),
                'sun', 'sun', 'conjunction')
        with self.assertRaisesRegex(ValueError, '1900–2099'):
            self.transits.snapshot(self.alice, self.chart['id'],
                datetime(2100, 1, 1, tzinfo=UTC), 'sun', 'sun', 'conjunction')
        with self.assertRaisesRegex(ValueError, 'Unsupported planet'):
            self.transits.snapshot(self.alice, self.chart['id'],
                datetime(2024, 4, 1, tzinfo=UTC), 'vulcan', 'sun', 'conjunction')
