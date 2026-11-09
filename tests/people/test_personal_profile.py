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

    def test_existing_off_page_link_has_same_owned_picker_descriptor(self):
        people = People(self.store)
        people.charts.add_person(self.bob, 'foreign', 'Shared name')
        people.charts.add_person(self.bob, 'foreign-parent', 'Unique parent')
        people.charts.add_person(self.alice, 'z-target', 'Shared name')
        for index in range(52):
            people.charts.add_person(self.alice, f'a-{index:02}', 'Shared name')
        people.charts.add_person(self.alice, 'parent', 'Unique parent')
        profile = PersonalProfile(self.store)
        profile.change(self.alice, 'z-target', 'describe', {'kind': 'details', 'expected_version': 0,
            'details': {'pronouns': '', 'home': 'Northport', 'occupation': 'Teacher', 'about': ''}})
        profile.change(self.alice, 'parent', 'link', {'kind': 'link', 'expected_version': 0,
            'id': 'existing', 'other_person_id': 'z-target', 'label': 'Friend', 'dates': ''})
        first = people.picker(self.alice)
        self.assertEqual(len(first['people']), 50)
        self.assertNotIn('z-target', {row['id'] for row in first['people']})
        second = people.picker(self.alice, after=first['next_after'])
        target = next(row for row in second['people'] if row['id'] == 'z-target')
        link = profile.get(self.alice, 'parent')['links'][0]
        self.assertEqual(link['other_person_id'], 'z-target')
        self.assertEqual(link.get('picker_label'), 'Shared name · Teacher, Northport (profile 1)')
        self.assertEqual(link['picker_label'], target['picker_label'])
        self.assertNotIn('z-target', link['picker_label'])
        self.assertNotIn('foreign', {row['id'] for row in first['people'] + second['people']})
        with self.assertRaises(KeyError):
            profile.get(self.bob, 'parent')
        with self.assertRaises(KeyError):
            profile.change(self.alice, 'parent', 'foreign-link', {'kind': 'link', 'expected_version': 0,
                'id': 'invalid', 'other_person_id': 'foreign', 'label': 'Friend', 'dates': ''})
        profile.change(self.alice, 'z-target', 'unique-link', {'kind': 'link', 'expected_version': 0,
            'id': 'unique', 'other_person_id': 'parent', 'label': 'Friend', 'dates': ''})
        self.assertEqual(profile.get(self.alice, 'z-target')['links'][0]['picker_label'], 'Unique parent')

    def test_single_person_read_retains_canonical_self_label_without_changing_authority(self):
        from m2.chat.personal_context import preference
        from m2.people.self_association import association, set_association

        people = People(self.store)
        profile = PersonalProfile(self.store)
        people.charts.add_person(self.bob, 'foreign', 'Casey')
        for person, occupation in (('z-teacher', 'Teacher'), ('a-artist', 'Artist')):
            people.charts.add_person(self.alice, person, 'Casey')
            profile.change(self.alice, person, 'describe-' + person, {
                'kind': 'details', 'expected_version': 0,
                'details': {'pronouns': '', 'home': '', 'occupation': occupation, 'about': ''}})
        # The saved identity need not occur on the first picker page.
        for index in range(51):
            people.charts.add_person(self.alice, f'b-{index:02}', 'Other person')
        self.assertNotIn('z-teacher', {row['id'] for row in people.picker(self.alice)['people']})
        saved = set_association(self.store, self.alice, 'z-teacher', 0)
        for person, expected in (('z-teacher', 'Casey · Teacher (profile 1)'),
                                 ('a-artist', 'Casey · Artist (profile 2)')):
            self.assertEqual(people.get(self.alice, person).get('picker_label'), expected)
            self.assertEqual(next(row['picker_label'] for row in people.picker(self.alice, 'Casey')['people']
                                  if row['id'] == person), expected)
        self.assertEqual(association(self.store, self.alice), saved)
        self.assertEqual(preference(self.store, self.alice), {'enabled': False, 'version': 0})
        self.assertEqual(people.get(self.bob, 'foreign')['picker_label'], 'Casey')
        with self.assertRaises(KeyError):
            people.get(self.bob, 'z-teacher')
        with self.assertRaises(KeyError):
            people.get(self.alice, 'missing')
        # Missing descriptive details still use the canonical date/ordinal label.
        profile.change(self.alice, 'z-teacher', 'clear-details', {
            'kind': 'details', 'expected_version': 1,
            'details': {'pronouns': '', 'home': '', 'occupation': '', 'about': ''}})
        self.assertRegex(people.get(self.alice, 'z-teacher')['picker_label'],
                         r'^Casey · added \d{2} \w{3} \d{4} \(profile 1\)$')
        self.assertEqual(association(self.store, self.alice), saved)

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
