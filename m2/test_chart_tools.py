"""Real SDK MCP protocol and backend-owned chart event capture on owned PG."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from m2.charts import Charts
from m2.gateway import run_turn
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase
from m2.store import Store


UTC = timezone.utc
WHEN = datetime(2024, 3, 20, 3, 6, tzinfo=UTC)
SETTINGS = {'zodiac': 'tropical', 'house_system': 'none', 'node_type': 'true',
            'aspects': ['conjunction']}


class ChartToolsTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic equinox')
        charts.add_profile(self.alice, 'profile', SETTINGS)
        charts.add_birth(self.alice, 'person', 'born', 'UTC', 'synthetic supplied',
                         wall_time=datetime(2024, 3, 20, 3, 6))
        charts.add_birth(self.alice, 'person', 'unknown', 'UTC', 'synthetic uncertain',
                         earliest_utc=WHEN - timedelta(hours=12), latest_utc=WHEN + timedelta(hours=12))
        charts.create_chart(self.alice, 'known', 'person', 'born', 'profile', 1)
        charts.create_chart(self.alice, 'uncertain', 'person', 'unknown', 'profile', 1)
        self.store.create_conversation(self.alice, 'thread')

    def test_gateway_links_committed_chart_evidence_to_turn_and_qualification_to_prompt(self):
        model = TinySource()
        delivered = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'known-turn',
                                  'saved chart known', model, delivered.append), 'complete')
        self.assertEqual([e['kind'] for e in delivered],
                         ['tool_call', 'tool_result', 'assistant_chunk', 'complete'])
        self.assertEqual(delivered[1]['payload']['result']['birth']['zone'], 'UTC')
        self.assertIn('359.999', delivered[2]['payload']['content'])
        self.assertIn('houses', delivered[2]['payload']['content'])
        self.assertEqual(model.invocations, 0)
        self.assertEqual(self.store.db.execute('''
            SELECT chart_id,event_sequence FROM chart_evidence WHERE owner_id='alice'
        ''').fetchone()['event_sequence'], delivered[1]['sequence'])
        uncertain = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'uncertain-turn',
                                  'saved chart uncertain', model, uncertain.append), 'complete')
        self.assertIn('no single sign is established', uncertain[2]['payload']['content'])
        self.assertIn('no reference instant is a verified birth time',
                      uncertain[2]['payload']['content'])
        no_event = []
        self.assertEqual(run_turn(self.store, self.alice, 'thread', 'events',
                                  'chart events known 2024-03-23T00:00:00+00:00 2024-03-24T00:00:00+00:00',
                                  model, no_event.append), 'complete')
        self.assertEqual(no_event[1]['payload']['events'], [])
        self.assertIn('No Sun-to-natal-Sun', no_event[2]['payload']['content'])
        self.assertEqual(model.invocations, 0)
        run_turn(self.store, self.alice, 'thread', 'follow-up',
                 'What did we calculate earlier?', model, lambda _: None)
        self.assertEqual(model.invocations, 1)
        self.assertIn('chart_result uncertain profile 1 natal_sun', model.prompts[0])
        self.assertIn('uncertain_supplied_interval', model.prompts[0])
        with self.assertRaises(KeyError):
            Charts(self.store).get_chart(self.bob, 'known')
        self.store.create_conversation(self.bob, 'thread')
        self.store.begin(self.bob, 'thread', 'attempt', 'Synthetic wrong owner')
        with self.assertRaisesRegex(KeyError, 'Referenced chart not found'):
            self.store.append(self.bob, 'thread', 'attempt', 'tool_result',
                              {'chart_id': 'known', 'name': 'get_chart'})
        self.assertEqual(self.store.read_turn(self.bob, 'thread', 'attempt')['event_count'], 1)

    def test_local_mcp_protocol_list_call_and_cross_owner_denial(self):
        from m2.mcp_server import chart_tools

        async def exercise():
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.alice)) as client:
                tools = await client.list_tools()
                self.assertIn('get_chart', [tool.name for tool in tools.tools])
                result = await client.call_tool('get_chart', {'chart_id': 'known'})
                self.assertFalse(result.isError)
                payload = result.structuredContent or json.loads(result.content[0].text)
                self.assertEqual(payload['natal_sun']['status'], 'exact_supplied_time')
                crossing = await client.call_tool('find_chart_events', {
                    'chart_id': 'uncertain', 'start_utc': '2024-03-20T00:00:00+00:00',
                    'end_utc': '2024-03-21T00:00:00+00:00'})
                self.assertFalse(crossing.isError, crossing.content)
                content = crossing.structuredContent or json.loads(crossing.content[0].text)
                self.assertEqual(content['status'], 'unsupported_uncertain_birth_time')
            async with create_connected_server_and_client_session(
                    chart_tools(self.store, self.bob)) as other:
                denied = await other.call_tool('get_chart', {'chart_id': 'known'})
                self.assertTrue(denied.isError)
                self.assertNotIn('synthetic supplied', denied.content[0].text)

        asyncio.run(exercise())

    def test_synthetic_stdio_subprocess_uses_authenticated_protocol(self):
        self.store.close()  # stdio server owns the exclusive archive during its session
        environment = {'PATH': os.environ.get('PATH', ''), 'KAT_M2_DSN': self.dsn,
                       'KAT_M2_FILES': str(Path(self.directory.name) / 'files'),
                       'KAT_M2_LEDGER': str(self.ledger.path), 'KAT_MCP_SYNTHETIC_TEST': '1',
                       'KAT_MCP_TEST_USER': 'alice',
                       'KAT_MCP_TEST_PASSWORD': 'synthetic-password-alice'}

        async def exercise():
            parameters = StdioServerParameters(
                command=sys.executable, args=['-m', 'm2.mcp_server'], env=environment)
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    result = await client.call_tool('get_chart', {'chart_id': 'known'})
                    self.assertFalse(result.isError)
                    self.assertEqual(json.loads(result.content[0].text)['natal_sun']['status'],
                                     'exact_supplied_time')
        try:
            asyncio.run(exercise())
        finally:
            self.store = Store(self.dsn, Path(self.directory.name) / 'files', self.ledger)
            self.alice = self.store.authenticate('alice', 'synthetic-password-alice')
