"""Upgrade an owned synthetic schema-015 fixture; never touch an existing archive."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.archive.deletion import Tombstones
from m2.operations.local_fixture import ROOT
from m2.archive.store import Store
from tests.support.database import test_fixture_dsn


class ActiveNatalUpgradeTests(unittest.TestCase):
    def test_schema_015_backfills_latest_generated_only_and_remains_idempotent(self):
        admin_dsn = test_fixture_dsn()
        database = 'kat_m2_test_' + uuid4().hex[:12]
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        dsn = make_conninfo(admin_dsn, dbname=database)
        try:
            with psycopg.connect(dsn) as db:
                db.execute('CREATE TABLE schema_migrations(version integer PRIMARY KEY)')
                for path in sorted((ROOT / 'm2/migrations').glob('[0-9]*.sql')):
                    number = int(path.name.split('_', 1)[0])
                    if number > 15:
                        break
                    db.execute(path.read_text(encoding='utf-8'))
                    db.execute('INSERT INTO schema_migrations VALUES (%s)', (number,))
                for owner in ('alice', 'bob'):
                    db.execute('INSERT INTO accounts(id,password_hash) VALUES (%s,%s)',
                               (owner, 'synthetic-not-a-login'))
                    for person in ('generated', 'legacy-only'):
                        db.execute('INSERT INTO people(owner_id,id,name) VALUES (%s,%s,%s)',
                                   (owner, person, 'Synthetic ' + person))
                        for version in (1, 2):
                            birth = f'{person}-birth-{version}'
                            chart = f'{person}-chart-{version}'
                            db.execute('''INSERT INTO person_drafts(owner_id,person_id,revision,details)
                                          VALUES (%s,%s,%s,'{}'::jsonb)''',
                                       (owner, person, version))
                            db.execute('''INSERT INTO birth_records(owner_id,person_id,id,zone_name,
                                          instant_utc,provenance) VALUES (%s,%s,%s,'UTC',
                                          '2024-01-01T00:00:00Z','synthetic_fixture')''',
                                       (owner, person, birth))
                            db.execute('''INSERT INTO calculation_profiles(owner_id,id,revision,settings)
                                          VALUES (%s,%s,1,'{}'::jsonb) ON CONFLICT DO NOTHING''',
                                       (owner, person))
                            db.execute('''INSERT INTO charts(owner_id,id,person_id,birth_id,
                                          profile_id,profile_revision,result,engine_version)
                                          VALUES (%s,%s,%s,%s,%s,1,'{}'::jsonb,'synthetic')''',
                                       (owner, chart, person, birth, person))
                            if person == 'generated':
                                db.execute('''INSERT INTO birth_generation_requests(owner_id,person_id,
                                    request_id,input_digest,provisional,draft_revision,birth_id,chart_id,
                                    created_at) VALUES (%s,%s,%s,%s,false,%s,%s,%s,%s)''',
                                    (owner, person, f'generate-{version}', str(version) * 64,
                                     version, birth, chart, f'2024-01-0{version}T00:00:00Z'))
                db.commit()
            with TemporaryDirectory(prefix='kat-natal-upgrade-', dir=ROOT / '.local') as directory:
                with Store(dsn, Path(directory) / 'files', Tombstones(Path(directory) / 'ledger')) as store:
                    rows = store.db.execute('''SELECT owner_id,person_id,chart_id FROM person_active_charts
                                               ORDER BY owner_id,person_id''').fetchall()
                    self.assertEqual([(row['owner_id'], row['person_id'], row['chart_id']) for row in rows],
                                     [('alice', 'generated', 'generated-chart-2'),
                                      ('bob', 'generated', 'generated-chart-2')])
                    self.assertEqual(store.db.execute('SELECT count(*) AS n FROM charts').fetchone()['n'], 8)
                with Store(dsn, Path(directory) / 'files', Tombstones(Path(directory) / 'ledger')) as store:
                    self.assertEqual(store.db.execute('SELECT count(*) AS n FROM person_active_charts')
                                     .fetchone()['n'], 2)
        finally:
            with psycopg.connect(admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


if __name__ == '__main__':
    unittest.main()
