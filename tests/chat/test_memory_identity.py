"""One-time self choice and frozen input authority through real background work."""
from tests.chat.test_memory_jobs import MemoryJobsFixture
from tests.support.self_association import legacy_association


class MemoryIdentityTests(MemoryJobsFixture):
    def choose(self, person=None, version=0):
        return self.post('/api/personal-context-self', {
            'person_id': person or self.person, 'expected_version': version})

    def self_action(self, action, evidence):
        return {**action, 'attribution': 'self'}

    def test_one_time_http_choice_replays_but_cannot_switch_clear_or_reassign_deleted_person(self):
        other = self.post('/api/people', {'name': 'Casey'}).json()['id']
        selected = self.choose().json()
        self.assertEqual(selected, {'person_id': self.person, 'version': 1})
        self.assertEqual(self.choose().json(), selected)
        self.assertEqual(self.choose(version=1).json(), selected)
        for replacement in (other, None):
            response = self.post('/api/personal-context-self', {
                'person_id': replacement, 'expected_version': 1})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get('/api/personal-context-self').json(), selected)
        runtime = self.app.state.runtime
        self.client.portal.call(runtime.call, lambda store, _:
            store.ledger.delete_person(store, store.authenticate('alice', 'synthetic-password-alice'), self.person))
        self.assertEqual(self.client.get('/api/personal-context-self').json(), {'person_id': None, 'version': 1})
        self.assertEqual(self.choose(other, 1).status_code, 409)

    def test_unset_input_is_not_reinterpreted_by_later_first_choice_but_new_self_input_works(self):
        self.action_transform = self.self_action
        original = self.start_memory(text='I enjoy gardening.', before_analysis=lambda: self.choose())
        self.assertEqual(original[0]['payload']['personal_context']['self_association']['version'], 0)
        self.assertEqual(self.finish_memory(), 'failed')
        self.assertEqual(self.entries(), [])
        def borrow_old_input(action, evidence):
            old = evidence['messages'][0]
            return {**self.self_action(action, evidence), 'statements': action['statements'] + [{
                'turn_id': old['turn_id'], 'start': 0, 'end': len(old['text']), 'text': old['text']}]}
        self.action_transform = borrow_old_input
        self.start_memory('old-ancestry', 'I also enjoy growing herbs.')
        self.assertEqual(self.finish_memory(), 'failed')
        self.assertEqual(self.entries(), [])
        self.action_transform = self.self_action
        self.start_memory('after-choice', 'I enjoy gardening.')
        self.assertEqual(self.finish_memory(), 'saved')
        entry, = self.entries()
        self.assertEqual(entry['source']['turn_id'], 'after-choice')
        self.assertEqual(entry['source']['self_association'], {'person_id': self.person, 'version': 1})

    def test_legacy_changed_generation_cannot_relabel_pending_self_input(self):
        casey = self.post('/api/people', {'name': 'Casey'}).json()['id']
        self.assertEqual(self.choose(casey).status_code, 200)
        self.action_transform = self.self_action
        runtime = self.app.state.runtime
        def historical_change():
            self.client.portal.call(runtime.call, lambda store, _:
                legacy_association(store, store.authenticate('alice', 'synthetic-password-alice'), self.person))
        self.start_memory(text='I enjoy gardening.', before_analysis=historical_change)
        self.assertEqual(self.finish_memory(), 'failed')
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.client.get(f'/api/people/{casey}/context').json()['entries'], [])

    def test_legacy_change_during_inference_fences_application(self):
        self.choose()
        self.action_transform = self.self_action
        self.start_memory(text='I enjoy gardening.')
        runtime = self.app.state.runtime
        self.client.portal.call(runtime.call, lambda store, _:
            legacy_association(store, store.authenticate('alice', 'synthetic-password-alice'), None))
        self.assertEqual(self.finish_memory(), 'stale')
        self.assertEqual(self.entries(), [])
