"""Real owned PostgreSQL tone preference and atomic accepted-turn identity."""

from hashlib import sha256
from pathlib import Path
import shutil
from tests.support.personal_context_schema import remove_personal_context_schema

import psycopg

from m2.release_schema import migrate
from tests.support.database import DatabaseCase
from m2.chat.tone_profiles import DEFAULT, archived_instructions, catalogue, instructions


class ToneTests(DatabaseCase):
    def test_schema23_to_24_uses_exact_additive_empty_table_lane(self):
        self.store.create_conversation(self.alice, 'retained')
        self.store.close()
        with psycopg.connect(self.dsn) as db:
            remove_personal_context_schema(db)
            db.execute('DROP TABLE account_tones')
            db.execute('DELETE FROM schema_migrations WHERE version=24')
        path = Path(__file__).resolve().parents[2] / 'm2/migrations' / '024_account_tones.sql'
        lane = {'from': 23, 'to': 24, 'migrations': {path.name: sha256(path.read_bytes()).hexdigest()},
                'added_tables': ['account_tones'], 'added_columns': {}}
        history = Path(self.directory.name) / 'schema24-migrations'
        history.mkdir()
        for migration in path.parent.glob('*.sql'):
            if int(migration.name.split('_')[0]) <= 24:
                shutil.copy2(migration, history)
        self.assertEqual(migrate(self.dsn, lane, history), {'schema': 24, 'status': 'migrated'})
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT id FROM conversations').fetchall(), [('retained',)])
            self.assertEqual(db.execute('SELECT count(*) FROM account_tones').fetchone(), (0,))
        with self.assertRaisesRegex(ValueError, 'no replay'):
            migrate(self.dsn, lane, history)

    def test_catalogue_and_owner_scoped_revision_and_missing_row_default(self):
        self.assertEqual(len(catalogue()['profiles']), 5)
        self.assertEqual(self.store.tone_preference(self.alice), {'tone_id': DEFAULT, 'revision': 0})
        self.assertEqual(self.store.tone_preference(self.bob), {'tone_id': DEFAULT, 'revision': 0})
        with self.assertRaises(ValueError):
            self.store.set_tone_preference(self.alice, 'prompt-injection', 0)
        with self.assertRaises(ValueError):
            self.store.set_tone_preference(self.alice, 'thoughtful-wit', True)
        self.assertEqual(self.store.set_tone_preference(self.alice, 'thoughtful-wit', 0),
                         {'tone_id': 'thoughtful-wit', 'revision': 1})
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.store.set_tone_preference(self.alice, 'cosmic-cabaret', 0)
        self.assertEqual(self.store.tone_preference(self.alice)['tone_id'], 'thoughtful-wit')
        self.assertEqual(self.store.tone_preference(self.bob), {'tone_id': DEFAULT, 'revision': 0})
        with psycopg.connect(self.dsn) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM account_tones').fetchone()[0], 1)
        self.assertEqual(self.store.set_tone_preference(self.bob, 'grounded-warmth', 0)['revision'], 1)
        self.assertEqual(self.store.tone_preference(self.alice)['tone_id'], 'thoughtful-wit')

    def test_turn_zero_freezes_tone_and_prompt_before_ack_without_rewriting_history(self):
        self.store.create_conversation(self.alice, 'tones')
        self.store.begin(self.alice, 'tones', 'one', 'First question', model_provider='chatgpt_plan',
                         model_slug='synthetic', reporting_zone='UTC')
        original = self.store.read_turn(self.alice, 'tones', 'one', event_limit=1)['events'][0]['payload']['tone']
        self.assertEqual(original, instructions(DEFAULT)[1])
        self.store.set_tone_preference(self.alice, 'cosmic-cabaret', 0)
        self.store.begin(self.alice, 'tones', 'two', 'Second question', model_provider='chatgpt_plan',
                         model_slug='synthetic', reporting_zone='UTC')
        newer = self.store.read_turn(self.alice, 'tones', 'two', event_limit=1)['events'][0]['payload']['tone']
        self.assertEqual(newer, instructions('cosmic-cabaret')[1])
        self.assertEqual(self.store.read_turn(self.alice, 'tones', 'one', event_limit=1)['events'][0]['payload']['tone'], original)
        self.assertFalse(self.store.begin(self.alice, 'tones', 'one', 'First question',
                                          model_provider='chatgpt_plan', model_slug='synthetic',
                                          reporting_zone='UTC'))
        self.assertEqual(archived_instructions(original)[1], original)
        with self.assertRaises(ValueError):
            archived_instructions({**original, 'prompt_sha256': '0' * 64})
