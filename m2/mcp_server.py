"""Local stdio MCP adapter over authenticated archive/chart services.

No network listener, account selector tool, arbitrary file access or autonomous
conversation capture. An external MCP host is NOT an archive-capable client;
use the backend-owned gateway for complete turns and model context.
"""

import getpass
import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from m2.charts import Charts
from m2.advanced import Advanced
from m2.synastry import Synastry
from m2.deletion import Tombstones
from m2.evidence import LocalEmbedder, personal_context, search_evidence
from m2.references import References
from m2.recall import search
from m2.store import Store


def chart_tools(store, session):
    mcp = FastMCP('Kat local chart evidence')
    charts = Charts(store)
    references = References(store)

    @mcp.tool()
    def get_chart(chart_id: str) -> dict:
        """Read a saved immutable chart result with birth/profile qualification and source."""
        row = charts.get_chart(session, chart_id)
        return {'chart_id': row['id'], 'created_at': row['created_at'].isoformat(),
                'source_status': row['source_status'],
                **(row['result'] if row['source_status'] == 'current'
                   else {'status': 'unsupported_stale_birth_source'})}

    @mcp.tool()
    def find_chart_events(chart_id: str, start_utc: str, end_utc: str,
                          body: str = 'sun', aspect: str = 'conjunction') -> dict:
        """Find Sun-to-natal-Sun crossings; UTC ISO instants, <=30 UTC days."""
        return charts.find_events(session, chart_id, datetime.fromisoformat(start_utc),
                                  datetime.fromisoformat(end_utc), body, aspect)

    @mcp.tool()
    def get_solar_return(chart_id: str, year: int, latitude: float, longitude: float) -> dict:
        """Calculate a solar return for an explicit UTC anniversary and reference place."""
        return Advanced(store).calculate(session, chart_id, 'solar_return',
            {'year': year, 'latitude': latitude, 'longitude': longitude})

    @mcp.tool()
    def get_lunar_returns(chart_id: str, start_utc: str, end_utc: str,
                          latitude: float, longitude: float) -> dict:
        """Calculate bounded UTC lunar returns for an explicit reference place."""
        return Advanced(store).calculate(session, chart_id, 'lunar_return',
            {'start_utc': start_utc, 'end_utc': end_utc,
             'latitude': latitude, 'longitude': longitude})

    @mcp.tool()
    def get_planetary_returns(chart_id: str, body: str, start_utc: str, end_utc: str,
                              latitude: float, longitude: float) -> dict:
        """Search all Venus/Mars/Jupiter/Saturn direct and retrograde return passes."""
        return Advanced(store).calculate(session, chart_id, 'planetary_return', {
            'body': body, 'start_utc': start_utc, 'end_utc': end_utc,
            'latitude': latitude, 'longitude': longitude})

    @mcp.tool()
    def find_actual_lunations_eclipses(chart_id: str, start_utc: str, end_utc: str,
                                        natal_target: str, aspect: str) -> dict:
        """Find actual syzygies and distinct Swiss global eclipse maxima."""
        return Advanced(store).calculate(session, chart_id, 'actual_lunations_eclipses',
            {'start_utc': start_utc, 'end_utc': end_utc,
             'natal_target': natal_target, 'aspect': aspect})

    @mcp.tool()
    def find_progressed_lunar_phases(chart_id: str, start_utc: str, end_utc: str) -> dict:
        """Find bounded symbolic progressed Moon–Sun phase dates, not lunations."""
        return Advanced(store).calculate(session, chart_id, 'progressed_lunar_phases',
                                         {'start_utc': start_utc, 'end_utc': end_utc})

    @mcp.tool()
    def get_true_solar_arc(chart_id: str, effective_utc: str) -> dict:
        """Read true progressed-Sun solar arc directions, not MCp or real sky."""
        return Advanced(store).calculate(session, chart_id, 'true_solar_arc',
                                         {'effective_utc': effective_utc})

    @mcp.tool()
    def get_midpoint_composite(chart_a_id: str, chart_b_id: str) -> dict:
        """Read a two-source shortest-circle composite; no fabricated houses."""
        return Advanced(store).calculate(session, chart_a_id, 'midpoint_composite',
                                         {'chart_b_id': chart_b_id})

    @mcp.tool()
    def get_uncorrected_davison(chart_a_id: str, chart_b_id: str) -> dict:
        """Read derived time and arithmetic signed-coordinate midpoint chart."""
        return Advanced(store).calculate(session, chart_a_id, 'uncorrected_davison',
                                         {'chart_b_id': chart_b_id})

    @mcp.tool()
    def find_progressed_mc_contacts(chart_id: str, start_utc: str, end_utc: str,
                                    branch: str, body: str, aspect: str) -> dict:
        """Search bounded symbolic MCp or MCr contacts; never a real-sky transit."""
        return Advanced(store).calculate(session, chart_id, 'progressed_mc_contacts', {
            'start_utc': start_utc, 'end_utc': end_utc, 'branch': branch,
            'body': body, 'aspect': aspect})

    @mcp.tool()
    def get_secondary_progression(chart_id: str, effective_utc: str) -> dict:
        """Read symbolic progressed planets and distinct MCp/MCr at one effective UTC instant."""
        return Advanced(store).calculate(session, chart_id, 'secondary_progression',
                                         {'effective_utc': effective_utc})

    @mcp.tool()
    def find_natal_mc_transits(chart_id: str, start_utc: str, end_utc: str,
                               transit_body: str, aspect: str) -> dict:
        """Find exact planet contacts to the saved natal astronomical MC, <=30 UTC days."""
        return Advanced(store).calculate(session, chart_id, 'mc_transit', {
            'start_utc': start_utc, 'end_utc': end_utc,
            'transit_body': transit_body, 'aspect': aspect})

    @mcp.tool()
    def compare_selected_charts(chart_a_id: str, chart_b_id: str) -> dict:
        """Read two explicit owned natal versions and directional recipient-house overlays."""
        return Synastry(store).compare(session, chart_a_id, chart_b_id,
                                       {chart_a_id, chart_b_id})

    @mcp.tool()
    def search_conversations(query: str, limit: int = 10) -> dict:
        """Search current owned archive, returning source IDs, speakers and rebuild lag."""
        return search(store, session, query, limit)

    @mcp.tool()
    def search_reference_and_history(query: str, limit: int = 5,
                                     tradition: str | None = None,
                                     technique: str | None = None,
                                     person_id: str | None = None) -> dict:
        """Retrieve bounded untrusted sources and attributed current history; scores are NOT proof."""
        return search_evidence(store, session, query, LocalEmbedder(), limit,
                               tradition=tradition, technique=technique,
                               person_id=person_id)

    @mcp.tool()
    def get_reference_passage(source_id: str, passage_id: str) -> dict:
        """Read an owned passage and its rights/provenance; not an approved authority."""
        return references.readable_passage(session, source_id, passage_id)

    @mcp.tool()
    def get_personal_context(person_id: str, limit: int = 10) -> dict:
        """Read explicitly promoted attributed reports/inferences for one owned person."""
        return personal_context(store, session, person_id, limit)

    return mcp


def main():
    dsn = os.environ.get('KAT_M2_DSN')
    if not dsn:
        raise RuntimeError('Owned local PostgreSQL DSN required')
    files = os.environ.get('KAT_M2_FILES', '.local/m2-runtime/files')
    ledger = Tombstones(os.environ.get('KAT_M2_LEDGER', '.local/m2-runtime/deletions.jsonl'))
    with Store(dsn, files, ledger) as store:
        store.recover_open()
        if os.environ.get('KAT_MCP_SYNTHETIC_TEST') == '1':
            # Isolated integration fixture ONLY; never use this credential path
            # for personal accounts or a general client configuration.
            user = os.environ['KAT_MCP_TEST_USER']
            password = os.environ['KAT_MCP_TEST_PASSWORD']
        else:
            # stdout/stdin belong exclusively to stdio JSON-RPC. A controlling
            # terminal is mandatory; no ambient identity from MCP arguments.
            with open('/dev/tty', 'r+', encoding='utf-8') as terminal:
                terminal.write('Local account: ')
                terminal.flush()
                user = terminal.readline().strip()
            password = getpass.getpass('Local password: ')
        session = store.authenticate(user, password)
        chart_tools(store, session).run(transport='stdio')


if __name__ == '__main__':
    main()
