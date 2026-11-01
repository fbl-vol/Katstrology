"""Seed a small synthetic-only walkthrough in the owned local PG fixture.

No private chart, session.txt, external calls, browser or existing user data.
Prints synthetic fixture IDs/password only; never prints its DSN.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from m2.charts import Charts
from m2.deletion import Tombstones
from m2.evidence import LocalEmbedder, rebuild_vectors
from m2.local_fixture import fixture_dsn
from m2.recall import rebuild_pending
from m2.references import PersonalContext, References
from m2.store import Store


PASSWORD = 'synthetic-walkthrough-password'
WHEN = datetime(2024, 3, 20, 3, 6, tzinfo=timezone.utc)
SETTINGS = {'zodiac': 'tropical', 'house_system': 'none', 'node_type': 'true',
            'aspects': ['conjunction', 'sextile']}


def seed():
    suffix = uuid4().hex[:10]
    user, person, conv = 'walkthrough-' + suffix, 'person-' + suffix, 'conversation-' + suffix
    chart_id, uncertain_id, source_id = 'chart-' + suffix, 'uncertain-' + suffix, 'reference-' + suffix
    ledger = Tombstones('.local/m2-runtime/deletions.jsonl')
    with Store(fixture_dsn(), '.local/m2-runtime/files', ledger) as store:
        store.register_local(user, PASSWORD)
        session = store.authenticate(user, PASSWORD)
        charts, refs = Charts(store), References(store)
        charts.add_person(session, person, 'Synthetic sky observer')
        charts.add_profile(session, 'solar-profile', SETTINGS)
        charts.add_birth(session, person, 'exact', 'UTC', 'synthetic equinox instant',
                         wall_time=datetime(2024, 3, 20, 3, 6))
        charts.add_birth(session, person, 'interval', 'UTC', 'synthetic uncertain interval',
                         earliest_utc=WHEN - timedelta(hours=12),
                         latest_utc=WHEN + timedelta(hours=12))
        charts.create_chart(session, chart_id, person, 'exact', 'solar-profile', 1)
        charts.create_chart(session, uncertain_id, person, 'interval', 'solar-profile', 1)
        refs.add_source(session, source_id, 'Synthetic authors', 'Synthetic comparison',
                        'local fixture', 'western', 'solar', 'authored locally for tests',
                        'synthetic, not Kat-selected or a real book')
        refs.add_passage(session, source_id, 'fact', 'astronomical fixture',
                         'At the March equinox the Sun crosses tropical zero Aries.')
        refs.add_passage(session, source_id, 'pro', 'fictional interpretation',
                         'A fictional astrologer says every equinox guarantees personal change.')
        refs.add_passage(session, source_id, 'con', 'fictional disagreement',
                         'Another fictional astrologer says an equinox alone cannot establish personal change.')
        store.create_conversation(session, conv)
        store.begin(session, conv, 'intro', 'I enjoy synthetic sky notes.')
        store.append(session, conv, 'intro', 'assistant_chunk',
                     {'content': 'We can compare recorded results and attributed sources.'})
        store.append(session, conv, 'intro', 'complete', {})
        PersonalContext(store).add(session, person, 'preference', conv, 'intro',
                                   'I enjoy synthetic sky notes.')
        rebuild_pending(store, session)
        rebuild_vectors(store, session, LocalEmbedder())
    return {'user': user, 'synthetic_password': PASSWORD, 'conversation': conv,
            'person': person, 'chart': chart_id, 'uncertain_chart': uncertain_id,
            'reference': source_id, 'reference_passage': 'fact',
            'status': 'synthetic_only_not_kat_approved'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.local/m3-m5-walkthrough.json'))
    args = parser.parse_args(argv)
    record = seed()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    print('Synthetic IDs written to', args.output)


if __name__ == '__main__':
    main()
