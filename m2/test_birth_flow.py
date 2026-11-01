"""Synthetic real-PostgreSQL protection for one-action birth/chart creation."""

import unittest

from m2.birth_flow import BirthFlow, BirthInputError
from m2.cli import DEFAULT_MODEL, model_at
from m2.gateway import run_turn
from m2.prompting import HOSTED, LOCAL, identity
from m2.people import People
from m2.places import search
from m2.test_support import DatabaseCase


class BirthFlowTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.person = People(self.store).add(self.alice, 'Synthetic reader')
        self.flow = BirthFlow(self.store)

    def details(self, **changes):
        base = dict(request_id='request-synthetic-a', birth_date='2024-03-20', birth_time='03:06',
                    time_unknown=False, birthplace='Copenhagen, Capital Region, Denmark',
                    place_id='2618425', provisional=True, zone_override=None,
                    latitude_override=None, longitude_override=None, fold=None, settings=None)
        base.update(changes)
        return base

    def test_selected_city_provisional_exact_and_same_or_new_request_retry(self):
        place = search('cOPENHAGEN')[0]
        self.assertEqual((place['id'], place['zone'], place['country']),
                         ('2618425', 'Europe/Copenhagen', 'Denmark'))
        result = self.flow.generate(self.alice, self.person['id'], self.details())
        self.assertEqual(result['chart']['result']['natal']['status'], 'complete')
        self.assertEqual(result['chart']['result']['birth']['zone'], 'Europe/Copenhagen')
        self.assertEqual(result['chart']['result']['birth']['provenance'],
                         'provisional:geonames_city_centre_2618425')
        self.assertEqual(result['chart']['result']['natal']['instant_utc'], '2024-03-20T02:06:00+00:00')
        self.assertTrue(self.flow.generate(self.alice, self.person['id'], self.details())['reused'])
        second = self.flow.generate(self.alice, self.person['id'],
                                    self.details(request_id='request-synthetic-b'))
        self.assertFalse(second['reused'])
        self.assertNotEqual(result['chart']['id'], second['chart']['id'])
        self.assertEqual(second['active_chart_id'], second['chart']['id'])
        with self.assertRaisesRegex(BirthInputError, 'request_conflict'):
            self.flow.generate(self.alice, self.person['id'], self.details(birth_time='03:07'))
        saved = People(self.store).get(self.alice, self.person['id'])
        self.assertEqual((len(saved['drafts']), len(saved['birth_records']), len(saved['charts'])), (2, 2, 2))
        self.assertEqual(saved['active_chart_id'], second['chart']['id'])
        self.assertIn(result['birth_id'], [record['id'] for record in saved['birth_records']])
        replay = self.flow.generate(self.alice, self.person['id'], self.details())
        self.assertTrue(replay['reused'])
        self.assertEqual(replay['chart']['id'], result['chart']['id'])
        self.assertEqual(replay['active_chart_id'], second['chart']['id'])
        self.assertEqual(People(self.store).active_chart_id(self.alice, self.person['id']),
                         second['chart']['id'])

    def test_one_step_selected_complete_chart_fits_actual_local_and_hosted_text_bounds(self):
        chart = self.flow.generate(self.alice, self.person['id'], self.details())['chart']
        self.store.create_conversation(self.alice, 'selected-chart-thread')

        class Capture:
            def __init__(self, tokenize, context_limit):
                self.tokenize, self.context_limit = tokenize, context_limit
                self.prompts = []

            def create_completion(self, prompt, **_kwargs):
                self.prompts.append(prompt)
                yield {'choices': [{'text': 'Synthetic only', 'finish_reason': 'stop'}]}

        selected = [{'person_id': self.person['id'], 'chart_id': chart['id']}]
        local = model_at(DEFAULT_MODEL)
        try:
            local_capture = Capture(local.tokenize, local.context_limit)
            events = []
            self.assertEqual(run_turn(self.store, self.alice, 'selected-chart-thread', 'local-chart',
                                      'Give an overview of this selected natal chart', local_capture,
                                      events.append, selected_people=selected), 'complete')
            context = next(event['payload'] for event in events if event['kind'] == 'context')
            self.assertEqual({key: context[key] for key in identity('local')}, identity('local'))
            self.assertLessEqual(context['prompt_tokens'] + context['reply_reserve'], 2048)
            self.assertEqual(local_capture.prompts[0].count('<|im_start|>system'), 1)
            self.assertIn(LOCAL, local_capture.prompts[0])
            self.assertIn(chart['id'], local_capture.prompts[0])
            self.assertIn('positions=', local_capture.prompts[0])
            self.assertIn('cusps=', local_capture.prompts[0])
        finally:
            local.close()

        class HostedCapture(Capture):
            count_method = 'conservative_utf8_byte_estimate'

        hosted = HostedCapture(lambda text, **_: range((len(text) + 1) // 2), 4096)
        hosted_events = []
        self.assertEqual(run_turn(self.store, self.alice, 'selected-chart-thread', 'hosted-chart',
                                  'Give an overview of this selected natal chart', hosted,
                                  hosted_events.append, parent_id='@root', selected_people=selected,
                                  model_provider='chatgpt_plan', model_slug='synthetic'), 'complete')
        context = next(event['payload'] for event in hosted_events if event['kind'] == 'context')
        self.assertEqual({key: context[key] for key in identity('hosted')}, identity('hosted'))
        self.assertLessEqual(context['prompt_tokens'] + context['instruction_tokens']
                             + context['reply_reserve'], 4096)
        self.assertGreater(context['instruction_tokens'], 0)
        self.assertNotIn(HOSTED, hosted.prompts[0])
        self.assertIn('positions=', hosted.prompts[0])
        self.assertIn('cusps=', hosted.prompts[0])
        replay = []
        self.assertEqual(run_turn(self.store, self.alice, 'selected-chart-thread', 'hosted-chart',
                                  'Give an overview of this selected natal chart', hosted,
                                  replay.append, parent_id='@root', selected_people=selected,
                                  model_provider='chatgpt_plan', model_slug='synthetic'), 'complete')
        self.assertEqual(len(hosted.prompts), 1)
        self.assertEqual([event['payload'] for event in replay],
                         [event['payload'] for event in hosted_events])

    def test_unknown_time_historical_day_and_reliable_label_do_not_make_full_natal(self):
        result = self.flow.generate(self.alice, self.person['id'], self.details(
            birth_date='2024-10-27', birth_time='', time_unknown=True, fold=None, provisional=False))
        self.assertEqual(result['chart']['result']['natal']['status'], 'unsupported_uncertain_birth_time')
        self.assertFalse(result['chart']['result']['natal']['houses']['angles'])
        record = People(self.store).get(self.alice, self.person['id'])['birth_records'][0]
        self.assertEqual((record['latest_utc'] - record['earliest_utc']).total_seconds(), 25 * 3600)
        self.assertEqual(result['chart']['result']['birth']['provenance'],
                         'user_reported_reliable:geonames_city_centre_2618425')
        with self.assertRaisesRegex(ValueError, 'Unsupported solar interval'):
            People(self.store).add_birth(self.alice, self.person['id'], {
                'mode': 'interval', 'zone': 'Europe/Copenhagen',
                'earliest_utc': record['earliest_utc'].isoformat(),
                'latest_utc': record['latest_utc'].isoformat(),
            })

    def test_fold_gap_missing_place_and_override_are_explicit(self):
        for details, reason in [
            (self.details(birth_date='2024-10-27', birth_time='02:30'), 'choose_dst_occurrence'),
            (self.details(birth_date='2024-03-31', birth_time='02:30'), 'nonexistent_local_time'),
            (self.details(place_id=None), 'select_place_or_advanced_location'),
            (self.details(place_id='123456789'), 'select_place_again'),
            (self.details(latitude_override=5), 'coordinates_required_together'),
            (self.details(birth_date='0001-01-01'), 'unsupported_birth_or_chart'),
        ]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.flow.generate(self.alice, self.person['id'], details)
        self.assertEqual(len(People(self.store).get(self.alice, self.person['id'])['drafts']), 0)
        chart = self.flow.generate(self.alice, self.person['id'], self.details(
            birth_date='2024-10-27', birth_time='02:30', fold=1,
            zone_override='Europe/Copenhagen', latitude_override=55.6, longitude_override=12.5))['chart']
        self.assertEqual(chart['result']['natal']['status'], 'complete')
        self.assertEqual(chart['result']['birth']['latitude'], 55.6)
        self.assertEqual(chart['result']['birth']['provenance'],
                         'provisional:user_supplied_coordinates_place_2618425')

    def test_generated_versions_obey_existing_person_deletion_fence(self):
        result = self.flow.generate(self.alice, self.person['id'], self.details())
        self.store.ledger.delete_person(self.store, self.alice, self.person['id'])
        with self.assertRaises(KeyError):
            People(self.store).get(self.alice, self.person['id'])
        with self.assertRaises(KeyError):
            People(self.store).charts.get_chart(self.alice, result['chart']['id'])
        count = self.store.db.execute('''SELECT count(*) AS n FROM birth_generation_requests
                                         WHERE owner_id=%s AND person_id=%s''',
                                      (self.alice.owner_id, self.person['id'])).fetchone()['n']
        self.assertEqual(count, 0)

    def test_other_owner_cannot_retrieve_or_generate_this_person_chart(self):
        result = self.flow.generate(self.alice, self.person['id'], self.details())
        with self.assertRaises(KeyError):
            self.flow.generate(self.bob, self.person['id'], self.details(request_id='other'))
        with self.assertRaises(KeyError):
            People(self.store).charts.get_chart(self.bob, result['chart']['id'])
        with self.assertRaises(KeyError):
            People(self.store).active_chart_id(self.bob, self.person['id'])


if __name__ == '__main__':
    unittest.main()
