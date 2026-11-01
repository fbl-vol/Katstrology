"""New M3/M4 originals and vectors share the M2 deletion/restore lifecycle."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from m2.backup import backup, restore
from m2.charts import Charts
from m2.evidence import LocalEmbedder, personal_context, rebuild_vectors, search_evidence
from m2.gateway import run_turn
from m2.recall import assemble_prompt, rebuild_pending, search
from m2.references import PersonalContext, References
from m2.revisions import correct, export_conversation, select_branch
from m2.test_gateway import TinySource
from m2.test_support import DatabaseCase


SETTINGS = {'zodiac': 'tropical', 'house_system': 'none', 'node_type': 'true',
            'aspects': ['conjunction']}


class ExtendedLifecycleTests(DatabaseCase):
    fixture_requires_fresh_migration = True
    def fixture(self):
        charts, refs = Charts(self.store), References(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic A')
        charts.add_profile(self.alice, 'profile', SETTINGS)
        charts.add_birth(self.alice, 'person', 'birth', 'UTC', 'synthetic fixture',
                         wall_time=datetime(2024, 3, 20, 3, 6))
        charts.create_chart(self.alice, 'chart', 'person', 'birth', 'profile', 1)
        refs.add_source(self.alice, 'source', 'Synthetic author', 'Synthetic reference',
                        'synthetic edition', 'western', 'solar', 'locally authored',
                        'locally authored synthetic fixture')
        refs.add_passage(self.alice, 'source', 'passage', 'one',
                         'A synthetic equinox crossing is an astronomical calculation.')
        self.store.create_conversation(self.alice, 'thread')
        return charts, refs

    def test_correct_branch_and_delete_fence_new_evidence_and_originals(self):
        charts, refs = self.fixture()
        model = TinySource()
        run_turn(self.store, self.alice, 'thread', 'chart-turn', 'saved chart chart', model,
                 lambda _: None)
        run_turn(self.store, self.alice, 'thread', 'ref-turn', 'reference evidence equinox',
                 model, lambda _: None)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM reference_evidence')
                         .fetchone()['n'], 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM chart_evidence')
                         .fetchone()['n'], 1)
        rebuild_pending(self.store, self.alice)
        embedder = LocalEmbedder()
        rebuild_vectors(self.store, self.alice, embedder, limit=10)
        output = Path(self.directory.name) / 'evidence-export.jsonl'
        export_conversation(self.store, self.alice, 'thread', output)
        kinds = {json.loads(line)['type'] for line in output.read_text().splitlines()}
        self.assertTrue({'chart_evidence', 'reference_source', 'reference_passage'} <= kinds)

        # A source attached to an explicitly corrected turn is kept in the
        # original store but not offered as active reference evidence.
        refs.add_source(self.alice, 'turn-source', 'Synthetic author', 'Derived note',
                        'test edition', 'western', 'solar', 'from synthetic turn', 'synthetic',
                        source=('thread', 'ref-turn'))
        refs.add_passage(self.alice, 'turn-source', 'old', 'two',
                         'Old interpretation equinox claim, now withdrawn.')
        self.assertEqual(refs.get_passage(self.alice, 'turn-source', 'old')['source_status'],
                         'active')
        correct(self.store, self.alice, 'thread', 'withdraw-ref', 'ref-turn', 'withdraw')
        self.assertEqual(refs.get_passage(self.alice, 'turn-source', 'old')['source_status'],
                         'superseded')
        self.assertFalse(any(r['source_id'] == 'turn-source' for r in
                         search_evidence(self.store, self.alice, 'withdrawn')['results']))
        self.assertFalse(any(r['source_id'] == 'ref-turn' for r in
                         search_evidence(self.store, self.alice, 'equinox')['results']))
        self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM reference_passages "
                         "WHERE source_id='turn-source'").fetchone()['n'], 1)
        select_branch(self.store, self.alice, 'thread', None)
        self.assertEqual(search_evidence(self.store, self.alice, 'equinox')['results'][0]['kind'],
                         'reference_passage')
        with self.assertRaisesRegex(ValueError, 'Delete conversations containing'):
            self.ledger.delete_person(self.store, self.alice, 'person')
        with self.assertRaisesRegex(ValueError, 'Delete linked conversations'):
            self.ledger.delete_reference(self.store, self.alice, 'source')
        self.ledger.delete_conversation(self.store, self.alice, 'thread')
        self.ledger.delete_person(self.store, self.alice, 'person')
        self.ledger.delete_reference(self.store, self.alice, 'source')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM reference_vectors')
                         .fetchone()['n'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM history_vectors')
                         .fetchone()['n'], 0)
        with self.assertRaises(KeyError):
            charts.get_chart(self.alice, 'chart')

    def test_cross_conversation_birth_correction_fences_chart_answers_and_recall(self):
        charts = Charts(self.store)
        charts.add_person(self.alice, 'person', 'Synthetic')
        charts.add_profile(self.alice, 'profile', SETTINGS)
        self.store.create_conversation(self.alice, 'birth-source')
        self.store.begin(self.alice, 'birth-source', 'reported', 'Synthetic 03:06 UTC birth time')
        self.store.append(self.alice, 'birth-source', 'reported', 'complete', {})
        charts.add_birth(self.alice, 'person', 'birth', 'UTC', 'synthetic report',
                         wall_time=datetime(2024, 3, 20, 3, 6),
                         source=('birth-source', 'reported'))
        charts.create_chart(self.alice, 'chart', 'person', 'birth', 'profile', 1)
        self.store.create_conversation(self.alice, 'discussion')
        model = TinySource()
        run_turn(self.store, self.alice, 'discussion', 'discuss',
                 'saved chart chart', model, lambda _: None)
        rebuild_pending(self.store, self.alice)
        rebuild_vectors(self.store, self.alice, LocalEmbedder())
        self.assertTrue(search(self.store, self.alice, 'chart')['results'])
        with self.assertRaisesRegex(ValueError, 'Delete dependent conversations'):
            self.ledger.delete_conversation(self.store, self.alice, 'birth-source')
        archived = self.store.read_turn(self.alice, 'discussion', 'discuss')

        correct(self.store, self.alice, 'birth-source', 'correction', 'reported',
                'correct', 'The synthetic birth time was not established.')
        self.assertEqual(charts.get_chart(self.alice, 'chart')['source_status'], 'superseded')
        self.assertEqual(charts.find_events(self.alice, 'chart',
                         datetime(2024, 3, 19, tzinfo=timezone.utc),
                         datetime(2024, 3, 21, tzinfo=timezone.utc))['status'],
                         'unsupported_stale_birth_source')
        self.assertEqual(search(self.store, self.alice, 'chart')['results'], [])
        self.assertFalse(any(r['kind'] == 'conversation' for r in
                         search_evidence(self.store, self.alice, 'chart')['results']))
        prompt, _ = assemble_prompt(self.store, self.alice, 'discussion', 'discuss',
                                    'Continue', model.tokenize)
        self.assertNotIn('saved chart chart', prompt)
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'chart')['results'], [])
        self.assertEqual(self.store.read_turn(self.alice, 'discussion', 'discuss'), archived)
        response = []
        run_turn(self.store, self.alice, 'discussion', 'fresh', 'saved chart chart',
                 model, response.append)
        self.assertEqual(response[1]['payload']['source_status'], 'superseded')
        self.assertIn('historical', response[2]['payload']['content'])
        self.assertNotIn('359.999', response[2]['payload']['content'])
        self.assertEqual(model.invocations, 0)
        self.ledger.delete_conversation(self.store, self.alice, 'discussion')
        self.ledger.delete_conversation(self.store, self.alice, 'birth-source')
        with self.assertRaises(KeyError):
            charts.get_chart(self.alice, 'chart')

    def test_cross_conversation_reference_correction_fences_prior_evidence(self):
        refs = References(self.store)
        self.store.create_conversation(self.alice, 'source-thread')
        self.store.begin(self.alice, 'source-thread', 'claim', 'Synthetic equinox interpretation')
        self.store.append(self.alice, 'source-thread', 'claim', 'complete', {})
        refs.add_source(self.alice, 'linked', 'Synthetic writer', 'Synthetic essay',
                        'first edition', 'western', 'solar', 'synthetic turn',
                        'locally authored synthetic text', source=('source-thread', 'claim'))
        refs.add_passage(self.alice, 'linked', 'p1', 'opening',
                         'Synthetic equinox interpretation for testing.')
        self.store.create_conversation(self.alice, 'discussion')
        model = TinySource()
        run_turn(self.store, self.alice, 'discussion', 'evidence',
                 'reference evidence equinox', model, lambda _: None)
        rebuild_pending(self.store, self.alice)
        embedder = LocalEmbedder()
        rebuild_vectors(self.store, self.alice, embedder)
        self.assertTrue(search(self.store, self.alice, 'reference')['results'])
        self.assertEqual(refs.get_passage(self.alice, 'linked', 'p1')['source_status'], 'active')
        with self.assertRaisesRegex(ValueError, 'Delete dependent conversations'):
            self.ledger.delete_conversation(self.store, self.alice, 'source-thread')
        correct(self.store, self.alice, 'source-thread', 'withdrawn', 'claim', 'withdraw')
        self.assertEqual(refs.get_passage(self.alice, 'linked', 'p1')['source_status'], 'superseded')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM reference_vectors')
                         .fetchone()['n'], 0)
        self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM history_vectors "
                         "WHERE conversation_id='discussion'").fetchone()['n'], 0)
        self.assertEqual(rebuild_vectors(self.store, self.alice, embedder)['references_indexed'], 0)
        self.assertEqual(search(self.store, self.alice, 'reference')['results'], [])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(search(self.store, self.alice, 'reference')['results'], [])
        self.assertEqual(search_evidence(self.store, self.alice, 'equinox')['results'], [])
        self.assertEqual(self.store.read_turn(self.alice, 'discussion', 'evidence')['status'],
                         'complete')
        self.ledger.delete_conversation(self.store, self.alice, 'discussion')
        self.ledger.delete_conversation(self.store, self.alice, 'source-thread')
        with self.assertRaises(KeyError):
            refs.get_passage(self.alice, 'linked', 'p1')

    def test_old_backup_replays_newer_person_and_reference_deletions(self):
        charts, refs = self.fixture()
        charts.add_person(self.bob, 'person', 'Other synthetic person')
        refs.add_source(self.bob, 'source', 'Other author', 'Unrelated source',
                        'synthetic edition', 'western', 'solar', 'other', 'other synthetic fixture')
        refs.add_passage(self.bob, 'source', 'passage', 'one', 'Unrelated synthetic solar note.')
        self.store.begin(self.alice, 'thread', 'turn', 'Synthetic private-looking source')
        self.store.append(self.alice, 'thread', 'turn', 'complete', {})
        PersonalContext(self.store).add(self.alice, 'person', 'note', 'thread', 'turn',
                                        'Synthetic private-looking source')
        rebuild_pending(self.store, self.alice)
        rebuild_vectors(self.store, self.alice, LocalEmbedder())
        snapshot = Path(self.directory.name) / 'snapshot'
        backup(self.store, snapshot)
        self.ledger.delete_conversation(self.store, self.alice, 'thread')
        self.ledger.delete_person(self.store, self.alice, 'person')
        self.ledger.delete_reference(self.store, self.alice, 'source')
        target = 'kat_m2_restored_' + uuid4().hex[:12]
        dsn = make_conninfo(self.admin_dsn, dbname=target)
        with psycopg.connect(self.admin_dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
        restored = None
        try:
            restored = restore(snapshot, dsn, Path(self.directory.name) / 'restored', self.ledger)
            alice = restored.authenticate('alice', 'synthetic-password-alice')
            bob = restored.authenticate('bob', 'synthetic-password-bob')
            with self.assertRaises(KeyError):
                Charts(restored).get_chart(alice, 'chart')
            with self.assertRaises(KeyError):
                References(restored).get_passage(alice, 'source', 'passage')
            with self.assertRaises(KeyError):
                restored.read_turn(alice, 'thread', 'turn')
            self.assertEqual(restored.db.execute("SELECT count(*) AS n FROM personal_entries "
                             "WHERE owner_id='alice'").fetchone()['n'], 0)
            self.assertEqual(search_evidence(restored, alice, 'equinox')['results'], [])
            self.assertEqual(References(restored).get_passage(bob, 'source', 'passage')
                             ['content'], 'Unrelated synthetic solar note.')
        finally:
            if restored:
                restored.close()
            with psycopg.connect(self.admin_dsn, autocommit=True) as db:
                db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
