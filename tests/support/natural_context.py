"""Owned browser fixture: real archive/outcomes, synthetic response-model bytes."""
from unittest.mock import patch

import psycopg

from m2.archive.conversations import Conversations
from m2.chat.gateway import run_turn
from m2.chat.personal_context import set_preference, stage
from m2.people.people import People
from m2.people.personal_context import PersonalContext
from m2.people.self_association import set_association
from tests.chat.test_natural_context import proposal
from tests.chat.test_tool_evidence_budget import native_call
from tests.provider.test_provider_output_compat import model_for, text, slim_footer


def seed_terminal_states(store, session):
    from tests.people.test_personal_context import fact
    PersonalContext(store).save(session, 'casey', 'answers', 'answers', 0,
                               fact('guidance_preferences', 'Short ExampleWorks answers'))
    statements = ['Actually, I prefer detailed ExampleWorks answers.',
                  'Actually, I prefer brief ExampleWorks answers.']
    prompt = ' '.join(statements)
    Conversations(store).create(session, 'capture-conflict', 'Context conflict')
    store.begin(session, 'capture-conflict', 'conflict', prompt,
                selected_people=[{'person_id': 'casey', 'chart_id': None}])
    for statement in statements:
        args = proposal(prompt, statement, 'guidance_preferences')
        args.update(identity=args['statement'], intent='correct', entry_id='answers',
                    expected_version=1, correction_cue='Actually', target_phrase='ExampleWorks')
        stage(store, session, 'capture-conflict', 'conflict', args)
    store.append(session, 'capture-conflict', 'conflict', 'assistant_chunk', {'content': 'Two synthetic proposals compete for one supplied version.'})
    store.append(session, 'capture-conflict', 'conflict', 'complete', {})
    prompt = 'I am considering a small venture.'
    Conversations(store).create(session, 'capture-discarded', 'Context discarded')
    store.begin(session, 'capture-discarded', 'discarded', prompt,
                selected_people=[{'person_id': 'casey', 'chart_id': None}])
    stage(store, session, 'capture-discarded', 'discarded', proposal(prompt, prompt, 'coming_up'))
    store.append(session, 'capture-discarded', 'discarded', 'interrupted', {})


def seed_capture_views(store):
    for view in ('desktop', 'mobile', 'short-mobile', 'reflow'):
        user = 'reader-capture-' + view
        store.register_local(user, 'synthetic-browser-password')
        session = store.authenticate(user, 'synthetic-browser-password')
        People(store).charts.add_person(session, 'casey', 'Casey')
        People(store).charts.add_person(session, 'other', 'Casey')
        set_association(store, session, 'casey', 0)
        set_preference(store, session, True, 0)
        for state in ('saved', 'omitted', 'rejected', 'failure'):
            conversation = 'capture-' + state
            Conversations(store).create(session, conversation, 'Context ' + state)
            prompt = 'I joined ExampleWorks in July 2021.'
            args = proposal(prompt, prompt)
            if state == 'rejected':
                prompt = 'I did not join ExampleWorks.'
                args = proposal(prompt, 'join ExampleWorks.')
            answer = [text('Synthetic response. The archived context outcome is separate from this reply.'), slim_footer([])]
            model, bridge = model_for(answer) if state == 'omitted' else model_for(
                native_call(1, 'stage_personal_context', args), answer)
            try:
                def run():
                    return run_turn(store, session, conversation, state, prompt, model, lambda _: None,
                                    selected_people=[{'person_id': 'casey', 'chart_id': None}],
                                    model_provider='chatgpt_plan', model_slug='gpt-6.1-sol')
                if state == 'failure':
                    with patch.object(PersonalContext, 'save', side_effect=psycopg.OperationalError('synthetic failure')):
                        assert run() == 'complete'
                else:
                    assert run() == 'complete'
            finally:
                bridge.close()
        seed_terminal_states(store, session)
        set_association(store, session, None, 1)
        set_preference(store, session, False, 1)
