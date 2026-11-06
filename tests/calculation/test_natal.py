"""Independent published chart anchors plus isolated owner-scoped persistence.

References are public computational samples, not verified birth-time evidence:
https://cafeastrology.com/articles/howtoobtainchart.html (London 1948)
https://fourfoldastrology.com/charts/gould-shane (Sydney 1956; time estimated)
Expected degrees below were transcribed from these published tables, never
regenerated from the implementation under test.
"""

import asyncio
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from m2.calculation.charts import Charts
from m2.chat.gateway import run_turn
from m2.chat.tool_answers import _chart_prompt_evidence
from m2.calculation.natal import DEFAULT_ORBS, _aspects, calculate_natal, checked_natal_settings
from m2.people.people import People
from m2.chat.recall import assemble_prompt
from tests.chat.test_gateway import TinySource
from tests.support.database import DatabaseCase


UTC = timezone.utc
SETTINGS = {'chart_kind': 'natal', 'zodiac': 'tropical', 'house_system': 'placidus',
            'node_type': 'true', 'aspects': list(DEFAULT_ORBS), 'orbs': DEFAULT_ORBS}


def placement(chart, name):
    return next(item for item in chart['positions'] if item['id'] == name)


def angle(chart, name):
    return next(item for item in chart['houses']['angles'] if item['id'] == name)


class NatalReferenceTests(unittest.TestCase):
    def test_published_london_tropical_placidus_and_true_node(self):
        # Published GMT instant, 51°30' N, 0°10' W. Minute-resolution positions
        # permit 1 arcminute; do not assert any extra precision from the source.
        result = calculate_natal(datetime(1948, 11, 14, 21, 14, tzinfo=UTC),
                                 51.5, -1 / 6, SETTINGS)
        self.assertEqual(result['status'], 'complete')
        for name, expected, house in (
            ('sun', 210 + 22 + 25 / 60, 4),
            ('moon', 30 + 26 / 60, 10),
            ('mercury', 210 + 6 + 57 / 60, 4),
            ('jupiter', 240 + 29 + 53 / 60, 5),
            ('north_node', 30 + 4 + 58 / 60, 10),
        ):
            with self.subTest(body=name):
                self.assertAlmostEqual(placement(result, name)['longitude_degrees'], expected, delta=1 / 60)
                self.assertEqual(placement(result, name)['house'], house)
        self.assertAlmostEqual(angle(result, 'ascendant')['longitude_degrees'],
                               120 + 5 + 23 / 60, delta=1 / 60)
        self.assertAlmostEqual(angle(result, 'midheaven')['longitude_degrees'],
                               13 + 16 / 60, delta=1 / 60)
        self.assertAlmostEqual(result['houses']['cusps'][1]['longitude_degrees'],
                               120 + 22 + 8 / 60, delta=1 / 60)
        self.assertAlmostEqual(result['houses']['cusps'][2]['longitude_degrees'],
                               150 + 13 + 38 / 60, delta=1 / 60)
        north = placement(result, 'north_node')
        south = placement(result, 'south_node')
        self.assertAlmostEqual(south['longitude_degrees'],
                               (north['longitude_degrees'] + 180) % 360)
        self.assertEqual(south['derived_from'], 'selected_north_node_antipode')
        self.assertFalse(any('south_node' in (a['first'], a['second'])
                             for a in result['aspects']))
        opposition = [a for a in result['aspects'] if {a['first'], a['second']} ==
                      {'jupiter', 'uranus'} and a['kind'] == 'opposition']
        self.assertEqual(len(opposition), 1)
        self.assertLess(opposition[0]['orb_degrees'], 0.1)
        self.assertEqual(len(result['ephemeris_sha256']), 2)

    def test_published_southern_hemisphere_chart_with_mean_node(self):
        # Publicly published sample at 23:15 AEST, Sydney 33°52' S / 151°13' E.
        # The historical time is estimated; these are computational anchors for
        # the *stated input*, not a claim about a person's actual birth minute.
        settings = {**SETTINGS, 'node_type': 'mean'}
        result = calculate_natal(datetime(1956, 11, 23, 13, 15, tzinfo=UTC),
                                 -33 - 52 / 60, 151 + 13 / 60, settings)
        self.assertEqual(result['status'], 'complete')
        for name, expected, house in (
            ('sun', 240 + 1 + 14 / 60, 4),
            ('moon', 120 + 11 + 26 / 60, 1),
            ('mercury', 240 + 7 + 16 / 60, 4),
            ('north_node', 210 + 28 + 45 / 60, 4),
        ):
            with self.subTest(body=name):
                self.assertAlmostEqual(placement(result, name)['longitude_degrees'], expected, delta=.025)
                self.assertEqual(placement(result, name)['house'], house)
        self.assertAlmostEqual(angle(result, 'ascendant')['longitude_degrees'],
                               120 + 7 + 4 / 60, delta=.025)
        self.assertAlmostEqual(angle(result, 'midheaven')['longitude_degrees'],
                               30 + 24 + 48 / 60, delta=.025)
        self.assertAlmostEqual(result['houses']['cusps'][1]['longitude_degrees'],
                               150 + 19 + 49 / 60, delta=.025)

    def test_wrapped_major_aspects_and_declared_orb_inclusion(self):
        points = [{'id': 'first', 'longitude_degrees': 359},
                  {'id': 'second', 'longitude_degrees': 1},
                  {'id': 'third', 'longitude_degrees': 180}]
        settings = {**SETTINGS, 'aspects': ['conjunction', 'opposition'],
                    'orbs': {'conjunction': 2, 'opposition': 1}}
        found = _aspects(points, settings)
        self.assertEqual({(item['kind'], item['orb_degrees']) for item in found},
                         {('conjunction', 2), ('opposition', 1)})
        self.assertEqual(len(found), 3)
        self.assertEqual(_aspects(points, {**settings,
            'orbs': {'conjunction': 1.99, 'opposition': .99}}), [])

    def test_boundaries_orb_policy_and_no_silent_fallback(self):
        instant = datetime(2024, 3, 20, 3, 6, tzinfo=UTC)
        result = calculate_natal(instant, 70, 20, SETTINGS)
        self.assertEqual(result['status'], 'partial_unsupported_houses')
        self.assertEqual(result['houses']['status'], 'unsupported_house_calculation')
        self.assertEqual(result['houses']['cusps'], [])
        self.assertEqual(result['houses']['angles'], [])
        self.assertTrue(all(p['house'] is None for p in result['positions']))
        self.assertLess(min(placement(result, 'sun')['longitude_degrees'],
                            360 - placement(result, 'sun')['longitude_degrees']), .05)
        self.assertEqual(calculate_natal(instant, None, None, SETTINGS)['houses']['status'],
                         'unsupported_missing_coordinates')
        whole = calculate_natal(instant, 70, 20, {**SETTINGS, 'house_system': 'whole_sign'})
        self.assertEqual(whole['houses']['status'], 'supported')
        self.assertTrue(all(1 <= p['house'] <= 12 for p in whole['positions']))
        with self.assertRaisesRegex(ValueError, '1900–2099'):
            calculate_natal(datetime(1899, 12, 31, tzinfo=UTC), 0, 0, SETTINGS)
        with self.assertRaisesRegex(ValueError, 'Aware birth instant'):
            calculate_natal(datetime(2024, 3, 20, 3, 6), 0, 0, SETTINGS)
        for invalid in ({**SETTINGS, 'orbs': {'conjunction': 30}},
                        {**SETTINGS, 'orbs': {**DEFAULT_ORBS, 'trine': True}},
                        {**SETTINGS, 'node_type': 'south'},
                        {**SETTINGS, 'house_system': 'koch'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                checked_natal_settings(invalid)
        with patch('m2.calculation.natal.swe.house_pos', return_value=0):
            unusable = calculate_natal(instant, 55, 12, SETTINGS)
        self.assertEqual(unusable['houses']['status'], 'unsupported_house_calculation')
        self.assertEqual(unusable['houses']['cusps'], [])
        self.assertTrue(all(p['house'] is None for p in unusable['positions']))
        with patch('m2.calculation.natal.swe.calc_ut', return_value=((0, 0, 0, 0, 0, 0), 4)):
            with self.assertRaisesRegex(RuntimeError, 'fallback'):
                calculate_natal(instant, 0, 0, SETTINGS)


class NatalArchiveTests(DatabaseCase):
    def test_local_model_tokenizer_fits_a_selected_chart_without_inference(self):
        from m2.cli import DEFAULT_MODEL, model_at
        charts = Charts(self.store)
        charts.add_person(self.alice, 'reader', 'Synthetic reader')
        charts.add_birth(self.alice, 'reader', 'born', 'Europe/London', 'synthetic input',
                         wall_time=datetime(1948, 11, 14, 21, 14),
                         latitude=51.5, longitude=-1 / 6)
        charts.add_profile(self.alice, 'natal', SETTINGS)
        chart = charts.create_chart(self.alice, 'saved-natal', 'reader', 'born', 'natal', 1)
        self.store.create_conversation(self.alice, 'thread')
        payload = {'chart_id': chart['id'], 'source_status': 'current', 'result': chart['result']}
        selected = json.dumps([{'person_id': 'reader', 'name': 'Synthetic reader',
                                'chart_id': chart['id'],
                                'selected_birth_record': {'id': 'born',
                                    'source': 'supplied validated birth record for explicitly selected saved chart',
                                    'details': {'wall_time': '1948-11-14T21:14',
                                                'zone_name': 'Europe/London'}}}])
        model = model_at(DEFAULT_MODEL)
        try:
            prompt, budget = assemble_prompt(
                self.store, self.alice, 'thread', None,
                'What do the placements say? Saved chart evidence: ' + _chart_prompt_evidence(payload),
                model.tokenize, context_limit=model.context_limit, selected_context=selected)
            self.assertLessEqual(budget['prompt_tokens'] + budget['reply_reserve'], 2048)
            self.assertIn('cusps=', prompt)
        finally:
            model.close()

    def test_versioned_immutable_chart_selected_evidence_and_owner_boundary(self):
        people = People(self.store)
        charts = Charts(self.store)
        charts.add_person(self.alice, 'reader', 'Synthetic reader')
        birth = people.add_birth(self.alice, 'reader', {
            'mode': 'exact', 'zone': 'Europe/London', 'wall_time': '1948-11-14T21:14',
            'latitude': 51.5, 'longitude': -1 / 6})
        chart = people.create_chart(self.alice, 'reader', birth, 'natal-default', 1)
        original = chart['result']
        self.assertEqual(original['natal']['status'], 'complete')
        self.assertEqual(original['natal_sun']['sun_longitude_degrees'],
                         placement(original['natal'], 'sun')['longitude_degrees'])
        self.assertEqual(charts.find_events(self.alice, chart['id'],
                                            datetime(2024, 11, 14, tzinfo=UTC),
                                            datetime(2024, 11, 20, tzinfo=UTC))['status'], 'supported')
        revision = people.add_profile(self.alice, 'natal-default', {
            **SETTINGS, 'orbs': {**DEFAULT_ORBS, 'opposition': 0.1}})
        changed = people.create_chart(self.alice, 'reader', birth, 'natal-default', revision)
        self.assertEqual(charts.get_chart(self.alice, chart['id'])['result'], original)
        self.assertEqual(changed['result']['profile']['revision'], 2)
        with self.assertRaises(KeyError):
            charts.get_chart(self.bob, chart['id'])
        self.store.create_conversation(self.alice, 'thread')
        model = TinySource()
        events = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'first',
                                  'Please describe the calculated chart', model, events.append,
                                  selected_people=[{'person_id': 'reader', 'chart_id': chart['id']}]), 'complete')
        tool = next(e['payload'] for e in events if e['kind'] == 'tool_result')
        self.assertEqual(tool['result'], original)
        self.assertIn('cusps=', model.prompts[0])
        self.assertIn('method=natal-tropical-v1', model.prompts[0])
        self.assertEqual(tool['result']['natal']['ephemeris_sha256'],
                         original['natal']['ephemeris_sha256'])
        self.assertNotIn('Sun-only', model.prompts[0])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'first')['selected_people'][0]
                         ['profile_revision'], 1)
        self.assertEqual(self.store.db.execute('''
            SELECT count(*) AS n FROM chart_evidence WHERE owner_id='alice' AND chart_id=%s
        ''', (chart['id'],)).fetchone()['n'], 1)
        from mcp.shared.memory import create_connected_server_and_client_session
        from m2.mcp_server import chart_tools

        async def check_tool():
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.alice)) as client:
                response = await client.call_tool('get_chart', {'chart_id': chart['id']})
                self.assertFalse(response.isError)
                returned = response.structuredContent or json.loads(response.content[0].text)
                self.assertEqual(returned['natal'], original['natal'])
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.bob)) as other:
                denied = await other.call_tool('get_chart', {'chart_id': chart['id']})
                self.assertTrue(denied.isError)
        asyncio.run(check_tool())
        # Retrying the same ID is an archived replay, not another calculation.
        replay = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'first',
                                  'Please describe the calculated chart', model, replay.append,
                                  selected_people=[{'person_id': 'reader', 'chart_id': chart['id']}]), 'complete')
        self.assertEqual(model.invocations, 1)
        self.assertEqual([e['payload'] for e in replay], [e['payload'] for e in events])
        # A context-limited model fails with a terminal error, not an open turn
        # or an unrecorded omission of saved chart evidence.
        class SmallModel(TinySource):
            context_limit = 100
        limited = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'small-model',
                                  'Explain the full saved chart', SmallModel(), limited.append,
                                  selected_people=[{'person_id': 'reader', 'chart_id': chart['id']}]), 'error')
        self.assertIn('exceeds model context budget', limited[-1]['payload']['reason'])
        self.assertEqual(self.store.read_turn(self.alice, 'thread', 'small-model')['status'], 'error')

    def test_unknown_time_and_stale_source_never_become_current_natal_facts(self):
        people = People(self.store)
        charts = Charts(self.store)
        charts.add_person(self.alice, 'reader', 'Synthetic reader')
        birth = people.add_birth(self.alice, 'reader', {
            'mode': 'interval', 'zone': 'UTC', 'earliest_utc': '2024-03-20T00:00:00+00:00',
            'latest_utc': '2024-03-20T12:00:00+00:00', 'latitude': 55, 'longitude': 12})
        chart = people.create_chart(self.alice, 'reader', birth, 'natal-default', 1)
        self.assertEqual(chart['result']['natal']['status'], 'unsupported_uncertain_birth_time')
        self.assertEqual(chart['result']['natal']['positions'], [])
        self.assertEqual(chart['result']['natal']['houses']['angles'], [])
        self.store.create_conversation(self.alice, 'source')
        self.store.begin(self.alice, 'source', 'turn', 'Synthetic input')
        self.store.append(self.alice, 'source', 'turn', 'complete', {})
        charts.add_birth(self.alice, 'reader', 'sourced', 'UTC', 'synthetic source',
                         wall_time=datetime(2024, 3, 20, 3, 6), latitude=55, longitude=12,
                         source=('source', 'turn'))
        sourced = charts.create_chart(self.alice, 'sourced-chart', 'reader', 'sourced',
                                     'natal-default', 1)
        self.assertEqual(sourced['source_status'], 'current')
        from m2.archive.revisions import correct
        correct(self.store, self.alice, 'source', 'correction', 'turn', 'correct', 'Wrong time')
        self.assertEqual(charts.get_chart(self.alice, 'sourced-chart')['source_status'], 'superseded')
        from mcp.shared.memory import create_connected_server_and_client_session
        from m2.mcp_server import chart_tools

        async def stale_tool():
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.alice)) as client:
                response = await client.call_tool('get_chart', {'chart_id': 'sourced-chart'})
                result = response.structuredContent or json.loads(response.content[0].text)
                self.assertEqual(result['status'], 'unsupported_stale_birth_source')
                self.assertNotIn('natal', result)
        asyncio.run(stale_tool())
        self.store.create_conversation(self.alice, 'thread')
        with self.assertRaisesRegex(ValueError, 'superseded'):
            self.store.begin(self.alice, 'thread', 'attempt', 'Synthetic', selected_people=[
                {'person_id': 'reader', 'chart_id': 'sourced-chart'}])
        events = []
        run_turn(self.store, self.alice, 'thread', 'read', 'saved chart sourced-chart',
                 TinySource(), events.append)
        self.assertEqual(events[1]['payload']['result'],
                         {'status': 'unsupported_stale_birth_source'})
