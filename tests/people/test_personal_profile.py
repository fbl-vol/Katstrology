from m2.people.people import People
from m2.people.personal_profile import PersonalProfile
from m2.people.personal_context import ContextConflict
from tests.support.database import DatabaseCase


class PersonalProfileTests(DatabaseCase):
    def test_details_links_colliding_names_and_owner_boundaries(self):
        people = People(self.store)
        for owner, person in ((self.alice, 'one'), (self.alice, 'two'), (self.bob, 'private')):
            people.charts.add_person(owner, person, 'Same name')
        profile = PersonalProfile(self.store)
        details = {'kind': 'details', 'expected_version': 0,
                   'details': {'pronouns': '', 'home': 'A fictional town', 'occupation': 'Teacher', 'about': ''}}
        profile.change(self.alice, 'one', 'details', details)
        profile.change(self.alice, 'one', 'details', details)
        self.assertEqual(profile.get(self.alice, 'one')['version'], 1)
        with self.assertRaises(ContextConflict):
            profile.change(self.alice, 'one', 'stale', details)
        link = {'kind': 'link', 'expected_version': 0, 'id': 'link', 'other_person_id': 'two',
                'label': 'Sibling', 'dates': 'Since childhood'}
        profile.change(self.alice, 'one', 'link', link)
        self.assertEqual(profile.get(self.alice, 'two')['links'], [])
        with self.assertRaises(ContextConflict):
            profile.change(self.alice, 'one', 'duplicate', {**link, 'id': 'duplicate', 'label': ' sibling '})
        with self.assertRaises(KeyError):
            profile.change(self.alice, 'one', 'foreign', {**link, 'id': 'foreign', 'other_person_id': 'private'})
        with self.assertRaises(ValueError):
            profile.change(self.alice, 'one', 'self', {**link, 'id': 'self', 'other_person_id': 'one'})
        profile.change(self.alice, 'one', 'edit', {**link, 'expected_version': 1, 'label': 'Friend'})
        self.assertEqual(profile.get(self.alice, 'one')['links'][0]['version'], 2)
        profile.change(self.alice, 'one', 'unlink', {'kind': 'unlink', 'id': 'link', 'expected_version': 2})
        profile.change(self.alice, 'one', 'unlink', {'kind': 'unlink', 'id': 'link', 'expected_version': 2})
        with self.assertRaises(ContextConflict):
            profile.change(self.alice, 'one', 'resurrect', link)
        self.assertEqual(profile.get(self.alice, 'one')['links'], [])
        self.assertEqual(people.get(self.alice, 'two')['name'], 'Same name')
