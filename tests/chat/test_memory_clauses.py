"""Established assertion clauses through the actual deferred Responses path."""
from tests.chat.test_memory_jobs import MemoryJobsFixture


class MemoryClauseTests(MemoryJobsFixture):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.post('/api/personal-context-self', {
            'person_id': self.person, 'expected_version': 0}).status_code, 200)

    def actions_for(self, groups, assessment='asserted'):
        def transform(action, evidence):
            message = evidence['messages'][-1]
            result = []
            for group, statements in groups.items():
                spans = []
                for statement in statements:
                    start = message['text'].index(statement)
                    spans.append({'turn_id': message['turn_id'], 'start': start,
                                  'end': start + len(statement), 'text': statement})
                result.append({**action, 'attribution': 'self', 'assessment': assessment,
                               'group': group, 'statements': spans})
            return result
        return transform

    def test_fact_with_question_publishes_only_the_assertion(self):
        prompt = 'I enjoy gardening, what does my chart suggest?'
        self.action_transform = self.actions_for({'interests': ['I enjoy gardening']})
        original = self.start_memory(text=prompt)
        self.assertEqual(self.finish_memory(), 'saved')
        entry, = self.entries()
        self.assertEqual(entry['content']['title'], 'I enjoy gardening')
        self.assertEqual(entry['source']['statement'], 'I enjoy gardening')
        self.assertEqual(original[0]['payload']['content'], prompt)
        self.assertEqual(self.events('source'), original)

    def test_compound_and_conjunction_examples_preserve_all_four_facts(self):
        past = ['Got married in May 2020', 'joined ExampleWorks as a trainee in July 2021',
                'became full time around 2022']
        current = 'I am building a small venture'
        self.action_transform = self.actions_for({'past_moments': past, 'life_now': [current]})
        prompts = [', '.join([*past, current]) + ', what does my chart suggest?',
                   past[0] + ' and ' + past[1] + ' then ' + past[2] + ' and ' + current + ' how does my chart relate?']
        for index, prompt in enumerate(prompts):
            with self.subTest(prompt=prompt):
                self.start_memory(f'compound-{index}', prompt)
                self.assertEqual(self.finish_memory(), 'saved' if index == 0 else 'unchanged')
                entries = self.entries()
                self.assertEqual(len(entries), 2)
                self.assertEqual({source['statement'] for entry in entries
                                  for source in entry['source']['sources']}, {*past, current})
                self.assertTrue(all(entry['content']['date']['precision'] == 'unknown' for entry in entries))

    def test_unsupported_partial_negated_qualified_quoted_and_retracted_proposals_do_not_publish(self):
        cases = [
            ('I did not join ExampleWorks, what does my chart suggest?', 'join ExampleWorks', 'asserted'),
            ('If I joined ExampleWorks, what would happen?', 'I joined ExampleWorks', 'asserted'),
            ('I plan to move if I can, what does my chart suggest?', 'I plan to move', 'asserted'),
            ('Reference says: "I enjoy gardening", what does my chart suggest?', 'I enjoy gardening', 'asserted'),
            ('I enjoy gardening, what does my chart suggest? I take that back.', 'I enjoy gardening', 'non_asserted'),
        ]
        for index, (prompt, statement, assessment) in enumerate(cases):
            with self.subTest(prompt=prompt):
                self.action_transform = self.actions_for({'interests': [statement]}, assessment)
                self.start_memory(f'rejected-{index}', prompt)
                self.assertEqual(self.finish_memory(), 'failed')
                self.assertEqual(self.entries(), [])
