from m2.people.people import People
from m2.people.personal_profile import PersonalProfile
from m2.people.personal_context import ContextConflict
from tests.support.database import DatabaseCase


class PersonalProfileTests(DatabaseCase):
    def test_complete_picker_keeps_sidebar_bounded_and_owner_scope(self):
        people = People(self.store)
        people.charts.add_person(self.alice, 'z-old', 'Shared name')
        for index in range(55):
            people.charts.add_person(self.alice, f'a-{index:02}', 'Shared name')
        people.charts.add_person(self.bob, 'private', 'Shared name')
        self.assertEqual(len(people.list(self.alice)), 50)
        self.assertNotIn('z-old', {row['id'] for row in people.list(self.alice)})
        first = people.picker(self.alice, 'Shared')
        self.assertEqual(first['total'], 56)
        self.assertEqual(len(first['people']), 50)
        second = people.picker(self.alice, 'Shared', first['next_after'])
        self.assertEqual(len(second['people']), 6)
        self.assertIsNone(second['next_after'])
        self.assertIn('z-old', {row['id'] for row in second['people']})
        choices = first['people'] + second['people']
        self.assertNotIn('private', {row['id'] for row in choices})
        self.assertEqual(len({row['picker_label'] for row in choices}), 56)
        self.assertTrue(all(row['id'] not in row['picker_label'] for row in choices))
        self.assertIn('(profile 1)', next(row['picker_label'] for row in choices if row['id'] == 'z-old'))
        people.charts.add_person(self.alice, 'unique', 'Unique name')
        self.assertEqual(people.picker(self.alice, 'Unique')['people'][0]['picker_label'], 'Unique name')
        with self.assertRaises(KeyError):
            people.picker(self.alice, '', 'private')
        profile = PersonalProfile(self.store)
        profile.change(self.alice, 'a-00', 'link-old', {'kind': 'link', 'expected_version': 0,
            'id': 'old', 'other_person_id': 'z-old', 'label': 'Friend', 'dates': ''})
        self.assertEqual(profile.get(self.alice, 'a-00')['links'][0]['other_person_id'], 'z-old')

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
        label = next(row['picker_label'] for row in people.picker(self.alice, 'Same')['people'] if row['id'] == 'one')
        self.assertIn('Teacher, A fictional town', label)
        self.assertNotIn('one', label)
        self.assertEqual(next(row['picker_label'] for row in people.picker(self.alice, 'name')['people'] if row['id'] == 'one'), label)
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
