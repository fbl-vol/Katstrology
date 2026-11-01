"""Reference/personal original records through real owned PostgreSQL FKs."""

from m2.charts import Charts
from m2.references import PersonalContext, References
from m2.test_support import DatabaseCase


class ReferenceRecordsTests(DatabaseCase):
    def test_rights_metadata_passage_hash_and_same_id_owner_isolation(self):
        refs = References(self.store)
        for session in (self.alice, self.bob):
            refs.add_source(session, 'manual', 'Synthetic author', 'Synthetic primer',
                            'synthetic edition', 'western', 'solar', 'authored synthetic fixture',
                            'locally authored synthetic text, no external rights claimed')
        digest = refs.add_passage(self.alice, 'manual', 'p1', 'section A',
                                  'A synthetic claim about a solar crossing.')
        self.assertEqual(refs.get_passage(self.alice, 'manual', 'p1')['content_sha256'], digest)
        self.assertEqual(refs.get_passage(self.alice, 'manual', 'p1')['approval'],
                         'not_kat_selected')
        with self.assertRaises(KeyError):
            refs.get_passage(self.bob, 'manual', 'p1')
        self.assertEqual(self.store.db.execute('SELECT count(*) AS n FROM reference_sources')
                         .fetchone()['n'], 2)

    def test_personal_entry_requires_owned_completed_source_and_explicit_confirmation(self):
        charts = Charts(self.store)
        for session in (self.alice, self.bob):
            charts.add_person(session, 'person', 'Synthetic person')
            self.store.create_conversation(session, 'thread')
        self.store.begin(self.alice, 'thread', 'reported', 'I keep a synthetic sky journal.')
        self.store.append(self.alice, 'thread', 'reported', 'assistant_chunk',
                          {'content': 'Maybe this means you prefer evening observations.'})
        self.store.append(self.alice, 'thread', 'reported', 'complete', {})
        notebook = PersonalContext(self.store)
        notebook.add(self.alice, 'person', 'reported', 'thread', 'reported',
                     'I keep a synthetic sky journal.')
        notebook.add(self.alice, 'person', 'inference', 'thread', 'reported',
                     'Maybe you prefer evening observations.', 'agent_inference', 1)
        with self.assertRaisesRegex(ValueError, 'separate user turn'):
            notebook.add(self.alice, 'person', 'false-confirmed', 'thread', 'reported',
                         'I keep a synthetic sky journal.', 'explicitly_confirmed',
                         confirmation_turn_id='reported')
        with self.assertRaisesRegex(ValueError, 'attributed source'):
            notebook.add(self.alice, 'person', 'invented', 'thread', 'reported', 'I love storms')
        with self.assertRaises(KeyError):
            notebook.add(self.bob, 'person', 'crossed', 'thread', 'reported',
                         'I keep a synthetic sky journal.')

        self.store.begin(self.alice, 'thread', 'confirmed',
                         'confirm: I keep a synthetic sky journal.', parent_id='reported')
        self.store.append(self.alice, 'thread', 'confirmed', 'complete', {})
        notebook.add(self.alice, 'person', 'confirmed', 'thread', 'reported',
                     'I keep a synthetic sky journal.', 'explicitly_confirmed',
                     confirmation_turn_id='confirmed')
        self.assertEqual(self.store.db.execute("SELECT epistemic_status FROM personal_entries "
                         "WHERE owner_id='alice' AND id='confirmed'").fetchone()
                         ['epistemic_status'], 'explicitly_confirmed')
        self.ledger.delete_conversation(self.store, self.alice, 'thread')
        self.assertEqual(self.store.db.execute("SELECT count(*) AS n FROM personal_entries "
                         "WHERE owner_id='alice'").fetchone()['n'], 0)
