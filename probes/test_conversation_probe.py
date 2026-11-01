from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

import swisseph as swe

from capture_probe import Archive, run_turn
from conversation_probe import bounded_prompt, run_calculation_turn
from core_calc import solar_longitude


COMMAND = 'solar longitude at 2024-03-20T03:06:00+00:00'


class ControlledModel:
    def __init__(self):
        self.prompts = []

    def tokenize(self, text, **kwargs):
        # Lightweight budget fixture; the real CLI uses the actual model tokenizer.
        return text.split()

    def create_completion(self, prompt, **kwargs):
        self.prompts.append(prompt)
        yield {'choices': [{'text': 'Tool answer', 'finish_reason': None}]}
        yield {'choices': [{'text': '', 'finish_reason': 'stop'}]}


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.archive = Archive(Path(self.directory.name) / 'archive.sqlite')
        self.addCleanup(self.archive.close)
        swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))

    def test_real_tool_capture_and_replay_without_any_reinvocation(self):
        class VerifyBeforeInference(ControlledModel):
            def create_completion(inner, prompt, **kwargs):
                with sqlite3.connect(self.archive.db.execute('PRAGMA database_list').fetchone()[2]) as reader:
                    self.assertEqual(reader.execute('SELECT status FROM turns WHERE id=?', ('a',)).fetchone(), ('open',))
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM events WHERE turn_id=?', ('a',)).fetchone()[0], 4)
                return super().create_completion(prompt, **kwargs)

        model = VerifyBeforeInference()
        delivered = []

        def deliver(event):
            with sqlite3.connect(self.archive.db.execute('PRAGMA database_list').fetchone()[2]) as db:
                rows = db.execute('SELECT payload FROM events WHERE turn_id=?', ('a',)).fetchall()
                self.assertGreaterEqual(len(rows), 2)
            self.assertIn(event, self.archive.replay('a'))
            delivered.append(event)

        run_calculation_turn(self.archive, 'a', None, COMMAND, model, deliver)
        events = self.archive.replay('a')
        self.assertEqual([e['kind'] for e in events], ['user', 'tool_call', 'tool_result',
                         'context', 'assistant_chunk', 'complete'])
        self.assertAlmostEqual(events[2]['result']['longitude_degrees'],
                               solar_longitude(datetime(2024, 3, 20, 3, 6, tzinfo=timezone.utc)))
        self.assertEqual(delivered, events[1:])
        self.assertEqual(self.archive.status('a'), 'complete')
        run_calculation_turn(self.archive, 'a', None, COMMAND, model, lambda event: None)
        self.assertEqual(len(model.prompts), 1)
        self.assertEqual(self.archive.replay('a'), events)
        with self.assertRaisesRegex(ValueError, 'different content'):
            run_calculation_turn(self.archive, 'a', None, COMMAND + ' edit', model, lambda event: None)

    def test_tool_failure_and_unsaved_stream_chunk_never_look_complete(self):
        model = ControlledModel()
        delivered = []
        swe.set_ephe_path(self.directory.name)  # deliberate missing Swiss files
        with self.assertRaisesRegex(RuntimeError, 'fallback'):
            run_calculation_turn(self.archive, 'bad-tool', None, COMMAND, model, delivered.append)
        self.assertEqual([event['kind'] for event in delivered], ['tool_call'])
        self.assertEqual(len(model.prompts), 0)
        self.assertEqual(self.archive.status('bad-tool'), 'open')
        self.archive.recover()
        self.assertEqual(self.archive.status('bad-tool'), 'interrupted')
        swe.set_ephe_path(str((Path(__file__).resolve().parents[1] / '.local/ephe').resolve()))

        def reject_unsaved_chunk(event):
            delivered.append(event)
            if event['kind'] == 'context':
                self.archive.db.execute('PRAGMA query_only=ON')

        with self.assertRaises(sqlite3.OperationalError):
            run_calculation_turn(self.archive, 'bad-write', None, COMMAND, model, reject_unsaved_chunk)
        self.assertEqual(self.archive.status('bad-write'), 'open')
        self.assertEqual([event['kind'] for event in delivered[-3:]],
                         ['tool_call', 'tool_result', 'context'])
        self.assertNotIn('assistant_chunk', [e['kind'] for e in self.archive.replay('bad-write')])
        self.archive.db.execute('PRAGMA query_only=OFF')
        self.archive.recover()
        self.assertEqual(self.archive.status('bad-write'), 'interrupted')

    def test_branches_and_revisions_preserve_originals_and_bound_actual_prompt(self):
        model = ControlledModel()
        root = COMMAND + ' ROOT_MARKER ' + 'padding ' * 25
        original = COMMAND + ' ABANDONED_MARKER ' + 'padding ' * 25
        edited = COMMAND + ' EDITED_MARKER ' + 'padding ' * 25
        regenerate = COMMAND + ' REGENERATED_MARKER ' + 'padding ' * 25
        for turn_id, parent, text in [('root', None, root), ('old', 'root', original),
                                      ('edit', 'root', edited), ('regen', 'edit', regenerate)]:
            run_turn(self.archive, turn_id, text,
                     lambda: iter([{'kind': 'assistant_chunk', 'content': text},
                                   {'kind': 'complete'}]), lambda event: None, parent_id=parent)

        prompt, budget = bounded_prompt(self.archive, 'regen', COMMAND, model.tokenize,
                                        context_limit=130, reply_reserve=10)
        self.assertEqual(budget['prompt_tokens'], len(model.tokenize(prompt.encode())))
        self.assertLessEqual(budget['prompt_tokens'] + budget['reply_reserve'], 130)
        self.assertGreater(budget['excluded_turns'], 0)
        self.assertIn('REGENERATED_MARKER', prompt)
        self.assertNotIn('ABANDONED_MARKER', prompt)
        self.assertNotIn('ROOT_MARKER', prompt)
        self.assertEqual(self.archive.ancestry('old'), ['root', 'old'])
        self.assertEqual(self.archive.ancestry('regen'), ['root', 'edit', 'regen'])
        self.assertIn('ABANDONED_MARKER', self.archive.replay('old')[0]['content'])
        with self.assertRaisesRegex(ValueError, 'ancestry'):
            run_turn(self.archive, 'regen', regenerate, lambda: self.fail('reinvoke'),
                     lambda event: None, parent_id='old')

    def test_interruption_storage_refusal_and_restart_leave_honest_state(self):
        model = ControlledModel()
        run_calculation_turn(self.archive, 'cancel', None, COMMAND, model,
                             lambda event: None, interrupt_after=1)
        self.assertEqual(self.archive.status('cancel'), 'interrupted')
        self.assertEqual(self.archive.replay('cancel')[-2]['content'], 'Tool answer')
        self.archive.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):
            run_calculation_turn(self.archive, 'refused', None, COMMAND, model,
                                 lambda event: None)
        self.assertEqual(len(model.prompts), 1)
        self.archive.db.execute('PRAGMA query_only=OFF')
        run_turn(self.archive, 'open', COMMAND, lambda: iter([]),
                 lambda event: None)
        # Existing run_turn converts clean exhaustion to interrupted.
        self.assertEqual(self.archive.status('open'), 'interrupted')
        self.archive.begin('crash', COMMAND)
        self.archive.append('crash', {'kind': 'tool_call', 'id': 'crash:solar',
                                      'name': 'solar_longitude', 'arguments': {}})
        self.archive.close()
        self.archive = Archive(Path(self.directory.name) / 'archive.sqlite')
        self.archive.recover()
        self.assertEqual(self.archive.status('crash'), 'interrupted')
        calls = len(model.prompts)
        run_calculation_turn(self.archive, 'crash', None, COMMAND, model, lambda event: None)
        self.assertEqual(len(model.prompts), calls)
        self.assertEqual([e['kind'] for e in self.archive.replay('crash')],
                         ['user', 'tool_call', 'interrupted'])


if __name__ == '__main__':
    unittest.main()
