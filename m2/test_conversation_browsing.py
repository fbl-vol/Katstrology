"""Navigation previews use current owner-scoped indexed excerpts, never stale turns."""

from m2.conversations import Conversations
from m2.recall import rebuild_pending
from m2.revisions import correct, select_branch
from m2.test_support import DatabaseCase


class ConversationBrowsingTests(DatabaseCase):
    def test_preview_follows_indexed_branch_correction_and_pending_epoch(self):
        threads = Conversations(self.store)
        threads.create(self.alice, 'thread', 'Synthetic topics')
        threads.create(self.bob, 'thread', 'Other owner')
        self.store.begin(self.alice, 'thread', 'first', 'Original synthetic question')
        self.store.append(self.alice, 'thread', 'first', 'assistant_chunk',
                          {'content': 'Original answer with unique clue'})
        self.store.append(self.alice, 'thread', 'first', 'complete', {})

        pending = threads.list(self.alice)['conversations'][0]
        self.assertIsNone(pending['preview'])
        self.assertTrue(pending['preview_pending'])
        self.assertEqual(threads.list(self.bob)['conversations'][0]['preview'], None)
        rebuild_pending(self.store, self.alice)
        current = threads.list(self.alice)['conversations'][0]
        self.assertEqual(current['preview'], 'Original synthetic question')
        self.assertEqual(current['preview_speaker'], 'user')
        matched = threads.list(self.alice, query='unique clue')['conversations'][0]
        self.assertEqual(matched['preview'], 'Original answer with unique clue')
        self.assertEqual(matched['preview_speaker'], 'assistant')

        self.store.begin(self.alice, 'thread', 'branch', 'Selected branch now', 'first')
        self.store.append(self.alice, 'thread', 'branch', 'complete', {})
        self.assertIsNone(threads.list(self.alice)['conversations'][0]['preview'])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(threads.list(self.alice)['conversations'][0]['preview'], 'Selected branch now')
        self.assertTrue(correct(self.store, self.alice, 'thread', 'fix', 'branch', 'correct',
                                'Corrected branch wording'))
        self.assertIsNone(threads.list(self.alice)['conversations'][0]['preview'])
        rebuild_pending(self.store, self.alice)
        corrected = threads.list(self.alice)['conversations'][0]
        self.assertEqual(corrected['preview'], 'Corrected branch wording')
        self.assertEqual(corrected['preview_speaker'], 'correction')
        select_branch(self.store, self.alice, 'thread', 'first')
        self.assertIsNone(threads.list(self.alice)['conversations'][0]['preview'])
        rebuild_pending(self.store, self.alice)
        self.assertEqual(threads.list(self.alice)['conversations'][0]['preview'],
                         'Original synthetic question')
        self.assertEqual(threads.list(self.alice, query='Corrected branch wording')['conversations'], [])
        self.assertEqual(threads.list(self.bob)['conversations'][0]['preview'], None)

    def test_page_remains_bounded_and_normalizes_only_short_excerpt(self):
        threads = Conversations(self.store)
        for index in range(23):
            threads.create(self.alice, f'conv-{index:02}', f'Synthetic topic {index:02}')
        self.store.begin(self.alice, 'conv-22', 'long', 'First line\n' + 'many words ' * 100)
        self.store.append(self.alice, 'conv-22', 'long', 'complete', {})
        rebuild_pending(self.store, self.alice)
        first = threads.list(self.alice)
        self.assertEqual(len(first['conversations']), 20)
        self.assertEqual(first['next_offset'], 20)
        preview = next(row for row in first['conversations'] if row['id'] == 'conv-22')['preview']
        self.assertTrue(preview.startswith('First line many words'))
        self.assertLessEqual(len(preview), 144)
        self.assertEqual(len(threads.list(self.alice, offset=20)['conversations']), 3)
