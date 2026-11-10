"""Invalidated history remains invalidated without occupying the active inventory."""
from m2.people.personal_context import PersonalContext
from tests.chat.test_memory_jobs import MemoryJobsFixture


class MemoryActiveContextTests(MemoryJobsFixture):
    def test_new_source_reestablishes_fact_after_many_old_entries_are_invalidated(self):
        self.start_memory()
        self.assertEqual(self.finish_memory(), 'saved')
        old, = self.entries()
        runtime = self.app.state.runtime

        def older_entries(store, _):
            session = store.authenticate('alice', 'synthetic-password-alice')
            for index in range(33):
                PersonalContext(store).save(session, self.person, f'old-{index}', f'old-{index}',
                                            0, old['content'], old['source'])
        self.client.portal.call(runtime.call, older_entries)
        response = self.post('/api/conversations/thread/corrections', {
            'id': 'withdraw-old', 'source_turn': 'source', 'action': 'withdraw', 'replacement': None})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.entries(), [])
        self.start_memory('new-source', 'Frederik enjoys gardening.')
        self.assertEqual(self.finish_memory(), 'saved')
        current, = self.entries()
        self.assertNotEqual(current['id'], old['id'])
        self.assertEqual(current['content']['title'], 'Frederik enjoys gardening.')
        self.assertEqual({source['turn_id'] for source in current['source']['sources']}, {'new-source'})
        counts = self.client.portal.call(runtime.call, lambda store, _: store.db.execute(
            '''SELECT lifecycle,count(*) AS total FROM personal_context WHERE owner_id='alice'
               AND person_id=%s GROUP BY lifecycle''', (self.person,)).fetchall())
        self.assertEqual({row['lifecycle']: row['total'] for row in counts},
                         {'source_invalidated': 34, 'active': 1})
