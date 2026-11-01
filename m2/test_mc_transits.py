"""Saved natal astronomical MC versus actual-sky transiting longitude contacts."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from mcp.shared.memory import create_connected_server_and_client_session

from m2.advanced import Advanced
from m2.agent_reads import execute
from m2.birth_flow import BirthFlow
from m2.mcp_server import chart_tools
from m2.people import DEFAULT_NATAL_SETTINGS, People
from m2.test_support import DatabaseCase
from m2.transits import Transits, _position_at

UTC = timezone.utc


class McTransitTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person_id = People(self.store).add(self.alice, 'Synthetic MC reader')['id']
        # Published London 1948 chart (see m2.test_natal) has MC 13°16' Aries.
        self.chart = BirthFlow(self.store).generate(self.alice, self.person_id, {
            'request_id': 'mc-source', 'birth_date': '1948-11-14', 'birth_time': '21:14',
            'time_unknown': False, 'birthplace': 'Synthetic London coordinates',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 51.5, 'longitude_override': -1/6,
            'fold': None, 'settings': {**DEFAULT_NATAL_SETTINGS, 'house_system': 'whole_sign'},
        })['chart']

    def test_solar_contact_targets_astronomical_mc_and_not_tenth_cusp(self):
        mc = next(angle['longitude_degrees'] for angle in
                  self.chart['result']['natal']['houses']['angles'] if angle['id'] == 'midheaven')
        cusp = self.chart['result']['natal']['houses']['cusps'][9]['longitude_degrees']
        self.assertAlmostEqual(mc, 13 + 16/60, delta=1/60)
        self.assertGreater(abs(mc - cusp), .01)
        result = Transits(self.store).mc_events(self.alice, self.chart['id'],
            datetime(2024, 4, 1, tzinfo=UTC), datetime(2024, 4, 7, tzinfo=UTC),
            'sun', 'conjunction')
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['natal_mc_longitude_degrees'], mc)
        self.assertEqual(len(result['events']), 1)
        event = datetime.fromisoformat(result['events'][0]['instant_utc'])
        # The independently published Aries MC anchors the expected early-April season.
        self.assertLess(abs(event - datetime(2024, 4, 3, tzinfo=UTC)), timedelta(days=2))
        self.assertLess(abs((_position_at('sun', event)[0] - mc + 180) % 360 - 180), .002)
        self.assertIn('astronomical MC', result['method'])

    def test_owner_bound_source_replay_and_model_selection(self):
        params = {'start_utc': '2024-04-01T00:00:00+00:00',
                  'end_utc': '2024-04-07T00:00:00+00:00',
                  'transit_body': 'sun', 'aspect': 'conjunction'}
        with self.assertRaises(PermissionError):
            execute(self.store, self.alice, 'find_natal_mc_transits',
                {'chart_id': self.chart['id'], **params}, set())
        projected = execute(self.store, self.alice, 'find_natal_mc_transits',
            {'chart_id': self.chart['id'], **params}, {self.chart['id']})
        self.assertEqual(projected['status'], 'supported')
        result = Advanced(self.store).save(self.alice, 'saved-mc', self.person_id,
                                          'mc_transit', params)
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['events'], projected['events'])
        self.assertEqual(len(Advanced(self.store).list(self.alice, self.person_id, 'mc_transit')), 1)
        with self.assertRaises(KeyError):
            Advanced(self.store).get(self.bob, 'saved-mc')
        self.assertTrue(Advanced(self.store).save(self.alice, 'saved-mc', self.person_id,
            'mc_transit', params)['reused'])

    def test_mcp_mc_tool_is_owner_scoped_and_explicitly_selected(self):
        async def exercise():
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.alice)) as client:
                names = {item.name for item in (await client.list_tools()).tools}
                self.assertIn('find_natal_mc_transits', names)
                self.assertIn('compare_selected_charts', names)
                args = {'chart_id': self.chart['id'],
                        'start_utc': '2024-04-01T00:00:00+00:00',
                        'end_utc': '2024-04-07T00:00:00+00:00',
                        'transit_body': 'sun', 'aspect': 'conjunction'}
                response = await client.call_tool('find_natal_mc_transits', args)
                self.assertFalse(response.isError)
                payload = response.structuredContent or json.loads(response.content[0].text)
                self.assertEqual(payload['status'], 'supported')
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.bob)) as other:
                response = await other.call_tool('find_natal_mc_transits', args)
                self.assertTrue(response.isError)
        asyncio.run(exercise())

    def test_no_mc_if_recipient_houses_unsupported(self):
        polar = BirthFlow(self.store).generate(self.alice, self.person_id, {
            'request_id': 'mc-polar', 'birth_date': '1948-11-14', 'birth_time': '21:14',
            'time_unknown': False, 'birthplace': 'Synthetic polar coordinates',
            'place_id': None, 'provisional': True, 'zone_override': 'UTC',
            'latitude_override': 89.95, 'longitude_override': 15,
            'fold': None, 'settings': None,
        })['chart']
        partial = Transits(self.store).mc_events(self.alice, polar['id'],
            datetime(2024, 4, 1, tzinfo=UTC), datetime(2024, 4, 7, tzinfo=UTC),
            'sun', 'conjunction')
        self.assertEqual(partial['status'], 'unsupported_natal_mc_houses')
        self.assertNotIn('events', partial)
