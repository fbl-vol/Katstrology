"""Real owned PostgreSQL, clock and deletion-journal contracts for deliberate records."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.advanced import Advanced
from m2.backup import backup, restore
from m2.birth_flow import BirthFlow
from m2.people import People
from m2.person_records import Journal, Watchlist
from m2.test_support import DatabaseCase


class PersonRecordTests(DatabaseCase):
    fixture_requires_fresh_migration = True

    def fixture(self):
        store = self.store
        people = People(store)
        people.charts.add_person(self.alice, 'one', 'Synthetic reader')
        people.charts.add_person(self.bob, 'one', 'Other reader with colliding person ID')
        chart = BirthFlow(store).generate(self.alice, 'one', {
            'request_id': 'synthetic-record-source', 'birth_date': '2001-06-21',
            'birth_time': '04:00', 'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
            'place_id': '2618425', 'provisional': True, 'zone_override': None,
            'latitude_override': None, 'longitude_override': None, 'fold': None,
            'settings': None,
        })['chart']['id']
        saved = Advanced(store).save(self.alice, 'source-return', 'one', 'solar_return',
            {'year': 2026, 'latitude': 55.68, 'longitude': 12.57})
        self.assertEqual(saved['status'], 'supported')
        return chart, saved

    def test_watchlist_same_id_dst_and_stale_source(self):
        chart, saved = self.fixture()
        watch = Watchlist(self.store)
        early = {'wall_time': '2026-10-25T02:30', 'zone': 'Europe/Copenhagen', 'fold': 0}
        with self.assertRaisesRegex(ValueError, 'Nonexistent'):
            watch.save(self.alice, 'one', 'gap', saved['id'], 0, '',
                       {**early, 'wall_time': '2026-03-29T02:30'})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            watch.save(self.alice, 'one', 'fold', saved['id'], 0, '', {**early, 'fold': None})
        self.assertEqual(watch.save(self.alice, 'one', 'saved-watch', saved['id'], 0,
                                    'Review this', early), 'saved-watch')
        self.assertEqual(watch.save(self.alice, 'one', 'saved-watch', saved['id'], 0,
                                    'Review this', early), 'saved-watch')
        with self.assertRaises(ValueError):
            watch.save(self.alice, 'one', 'saved-watch', saved['id'], None, 'Review this', early)
        with self.assertRaises(KeyError):
            watch.list(self.bob, 'not-the-same-person')
        self.assertEqual(watch.list(self.bob, 'one')['items'], [])
        self.assertEqual(watch.list(self.alice, 'one',
                         lambda: datetime(2026, 10, 25, 0, 29, tzinfo=timezone.utc))
                         ['items'][0]['reminder_status'], 'scheduled')
        self.assertEqual(watch.list(self.alice, 'one',
                         lambda: datetime(2026, 10, 25, 0, 31, tzinfo=timezone.utc))
                         ['items'][0]['reminder_status'], 'due')
        watch.change(self.alice, 'one', 'saved-watch', 'later-fold', 'Review later',
                     {**early, 'fold': 1})
        self.assertEqual(watch.list(self.alice, 'one')['items'][0]['reminder']
                         ['instant_utc'], '2026-10-25T01:30:00+00:00')
        watch.change(self.alice, 'one', 'saved-watch', 'later-fold', 'Review later',
                     {**early, 'fold': 1})
        with self.assertRaises(ValueError):
            watch.change(self.alice, 'one', 'saved-watch', 'later-fold', 'Changed', None)
        # A newer active source cannot retarget the original calculation.
        BirthFlow(self.store).generate(self.alice, 'one', {
            'request_id': 'synthetic-newer-source', 'birth_date': '2002-06-21',
            'birth_time': '04:00', 'time_unknown': False, 'birthplace': 'Copenhagen, Capital Region, Denmark',
            'place_id': '2618425', 'provisional': True, 'zone_override': None,
            'latitude_override': None, 'longitude_override': None, 'fold': None,
            'settings': None,
        })
        item = watch.list(self.alice, 'one',
                          lambda: datetime(2026, 10, 25, 3, tzinfo=timezone.utc))['items'][0]
        self.assertEqual(item['source_status'], 'historical')
        self.assertEqual(item['reminder_status'], 'needs_review')
        self.assertEqual(item['result_id'], saved['id'])
        self.assertNotEqual(People(self.store).active_chart_id(self.alice, 'one'), chart)

    def test_watched_eclipse_maximum_resolves_original_not_syzygy(self):
        self.fixture()
        sky = Advanced(self.store).save(self.alice, 'watched-sky-source', 'one',
            'actual_lunations_eclipses', {
                'start_utc': '2024-03-01T00:00:00+00:00',
                'end_utc': '2024-06-01T00:00:00+00:00',
                'natal_target': 'sun', 'aspect': 'conjunction'})
        self.assertTrue(sky['eclipses'])
        watch = Watchlist(self.store)
        watch.save(self.alice, 'one', 'watched-maximum', 'watched-sky-source', 500,
                   'Original maximum, not nearby syzygy', None)
        listed = watch.list(self.alice, 'one')['items'][0]
        self.assertEqual(listed['event']['maximum_utc'], sky['eclipses'][0]['maximum_utc'])
        self.assertEqual(listed['event_index'], 500)
        with self.assertRaises(ValueError):
            watch.save(self.alice, 'one', 'invalid-maximum', 'watched-sky-source',
                       500 + len(sky['eclipses']),
                       '', None)

    def test_private_reflection_excluded_and_deletion_survives_old_backup(self):
        _, saved = self.fixture()
        journal, watch = Journal(self.store), Watchlist(self.store)
        with self.assertRaises(ValueError):
            journal.save(self.alice, 'one', 'gap', 'instant', '2026-03-29',
                '2026-03-29T02:30', 'Europe/Copenhagen', None, None, 'not an instant')
        journal.save(self.alice, 'one', 'reported', 'uncertain', '2026-06-21', None,
                     None, None, saved['id'], 'Voluntary private event')
        journal.save(self.alice, 'one', 'reported', 'uncertain', '2026-06-21', None,
                     None, None, saved['id'], 'Voluntary private event')
        journal.change(self.alice, 'one', 'reported', 'edited', 'Corrected private event')
        self.assertEqual(journal.list(self.alice, 'one')['entries'][0]['text'], 'Corrected private event')
        self.assertEqual(journal.list(self.alice, 'one')['model_and_automatic_recall'], 'excluded')
        self.assertEqual(journal.list(self.bob, 'one')['entries'], [])
        with self.assertRaises(KeyError):
            journal.change(self.bob, 'one', 'reported', 'wrong-owner', 'cross owner')
        watch.save(self.alice, 'one', 'watched', saved['id'], 0, '', None)
        snapshot = Path(self.directory.name) / 'record-snapshot'
        backup(self.store, snapshot)
        self.ledger.delete_person_record(self.store, self.alice, 'one', 'reported', 'journal_entry')
        self.ledger.delete_person_record(self.store, self.alice, 'one', 'watched', 'watch_item')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM journal_actions').fetchone()['n'], 0)
        with self.assertRaises(ValueError):
            journal.save(self.alice, 'one', 'reported', 'date', '2026-06-21', None,
                         None, None, None, 'Cannot reuse a tombstoned entry')
        target = 'kat_person_restore_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(snapshot, dsn, Path(self.directory.name) / 'restored', self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            self.assertEqual(Journal(restored).list(alice, 'one')['entries'], [])
            self.assertEqual(Watchlist(restored).list(alice, 'one')['items'], [])
            self.assertEqual(restored.db.execute('SELECT count(*) AS n FROM journal_actions').fetchone()['n'], 0)
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
        journal.save(self.alice, 'one', 'other', 'date', '2026-06-22', None,
                     None, None, None, 'Another event')
        self.ledger.delete_person(self.store, self.alice, 'one')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM journal_actions').fetchone()['n'], 0)
