from hashlib import sha256

from m2.chat.memory_evidence import snapshot
from m2.chat.personal_context import set_preference
from m2.http_boundary.web_auth import WebAuth
from m2.people.people import People
from m2.people.personal_context import PersonalContext
from tests.people.test_personal_context import fact
from tests.support.database import DatabaseCase


class MemoryEvidenceTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.auth = WebAuth(self.store)
        self.token, _, self.alice, _ = self.auth.login('alice', 'synthetic-password-alice')
        self.digest = sha256(self.token.encode()).hexdigest()
        self.store.create_conversation(self.alice, 'thread')
        People(self.store).charts.add_person(self.alice, 'frederik', 'Frederik')
        People(self.store).charts.add_person(self.bob, 'frederik', 'Frederik')
        set_preference(self.store, self.alice, True, 0)

    def complete(self, turn, text='Frederik enjoys gardening.', parent=None):
        self.store.memory_origins[('alice', 'thread', turn)] = {}
        self.store.begin(self.alice, 'thread', turn, text, parent, selected_people=[])
        self.store.memory_origins.pop(('alice', 'thread', turn))
        self.store.append(self.alice, 'thread', turn, 'complete', {})
        return {'owner_id': 'alice', 'conversation_id': 'thread', 'turn_id': turn,
                'consent_version': 1, 'session_digest': self.digest}

    def test_unselected_owned_person_without_chart_is_eligible(self):
        work = self.complete('one')
        evidence = snapshot(self.store, self.auth, work)
        self.assertEqual([person['id'] for person in evidence['people']], ['frederik'])
        person = evidence['people'][0]
        self.assertTrue(person['named_eligible'])
        self.assertFalse(person['associated_self'])
        self.assertIsNone(evidence['self_association']['person_id'])
        self.assertEqual(evidence['messages'][0]['text'], 'Frederik enjoys gardening.')
        self.assertEqual(person['eligible_turns'], ['one'])

    def test_duplicate_owned_names_are_not_resolved_by_first_match(self):
        People(self.store).charts.add_person(self.alice, 'another', 'Frederik')
        evidence = snapshot(self.store, self.auth, self.complete('one'))
        self.assertEqual(len(evidence['people']), 2)
        self.assertTrue(all(not person['named_eligible'] for person in evidence['people']))

    def test_bounded_followup_retains_original_user_reference(self):
        self.complete('one')
        work = self.complete('two', 'He grows tomatoes too.', 'one')
        evidence = snapshot(self.store, self.auth, work)
        self.assertEqual([item['turn_id'] for item in evidence['messages']], ['one', 'two'])
        self.assertEqual(evidence['people'][0]['eligible_turns'], ['one', 'two'])

    def test_session_owner_consent_and_deletion_fences(self):
        work = self.complete('one')
        service = PersonalContext(self.store)
        service.save(self.alice, 'frederik', 'deleted', 'manual', 0, fact())
        service.remove(self.alice, 'frederik', 'deleted', 1)
        self.assertIsNone(snapshot(self.store, self.auth, work))
        work = self.complete('two', parent='one')
        evidence = snapshot(self.store, self.auth, work)
        self.assertEqual(evidence['people'][0]['eligible_turns'], ['two'])
        set_preference(self.store, self.alice, False, 1)
        self.assertIsNone(snapshot(self.store, self.auth, work))
        self.auth.logout(self.token)
        with self.assertRaises(PermissionError):
            snapshot(self.store, self.auth, work)

    def test_oversized_current_message_is_not_trimmed_to_remove_retraction(self):
        work = self.complete('one', 'Frederik gardens. ' + 'x' * 8200 + 'That is fiction.')
        self.assertIsNone(snapshot(self.store, self.auth, work))
