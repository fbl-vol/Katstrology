"""Thin authenticated HTTP projection of the owner-scoped people services."""

from starlette.routing import Route

from m2.calculation.charts import Charts
from m2.calculation.exploration import explore_chart
from m2.people.birth_flow import BirthFlow, BirthInputError
from m2.people.chart_library import ChartLibrary
from m2.people.insights import SavedInsights
from m2.people.person_records import Watchlist, Journal
from m2.people.personal_context import PersonalContext, ContextConflict
from m2.people.personal_profile import PersonalProfile
from m2.people.places import search as search_places
from m2.people.people import People
from m2.http_boundary.boundary import authorized, json_body, json_response


async def people(request):
    session = await authorized(request, mutate=request.method == 'POST')
    if request.method == 'GET':
        rows = await request.app.state.runtime.call(
            lambda store, _: People(store).list(session))
        return json_response({'people': rows})
    data = await json_body(request)
    if set(data) - {'name', 'draft'}:
        raise ValueError('Unsupported person fields')
    person = await request.app.state.runtime.call(
        lambda store, _: People(store).add(session, data.get('name'), data.get('draft')))
    return json_response(person, 201)


async def person(request):
    session = await authorized(request, mutate=request.method == 'DELETE')
    if request.method == 'DELETE':
        await request.app.state.runtime.call(lambda store, _: store.ledger.delete_person(
            store, session, request.path_params['person_id']))
        return json_response({'status': 'deleted'})
    def read_person(store, _):
        result = People(store).get(session, request.path_params['person_id'])
        draft = result['drafts'][0] if result['drafts'] else None
        result['editor_location'] = BirthFlow(store).editor_location(
            session, result['id'], draft['revision'], draft['details']['birthplace']) if draft else None
        return result
    result = await request.app.state.runtime.call(read_person)
    return json_response(result)


async def chart_library(request):
    session = await authorized(request)
    person_id = request.path_params['person_id']
    technique = request.path_params.get('technique')
    if set(request.query_params) - ({'before'} if technique else set()):
        raise ValueError('Unsupported chart library query')
    result = await request.app.state.runtime.call(lambda store, _: (
        ChartLibrary(store).history(session, person_id, technique, request.query_params.get('before'))
        if technique else ChartLibrary(store).summary(session, person_id)))
    return json_response(result)


async def saved_chart(request):
    session = await authorized(request)
    result = await request.app.state.runtime.call(lambda store, _: Charts(store).get_chart(
        session, request.path_params['chart_id']))
    return json_response(result)


async def drafts(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    revision = await request.app.state.runtime.call(
        lambda store, _: People(store).add_draft(session, request.path_params['person_id'], data))
    return json_response({'revision': revision}, 201)


async def places(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'query'}:
        raise ValueError('Place search query required')
    def find(store, _):
        store.owner(session)
        return search_places(data['query'])
    rows = await request.app.state.runtime.call(find)
    return json_response({'places': rows})


async def generate_chart(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    try:
        result = await request.app.state.runtime.call(lambda store, _: BirthFlow(store).generate(
            session, request.path_params['person_id'], data))
    except BirthInputError as exc:
        return json_response({'error': exc.code}, 409 if exc.code == 'request_conflict' else 400)
    return json_response(result, 200 if result['reused'] else 201)


async def births(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    birth_id = await request.app.state.runtime.call(
        lambda store, _: People(store).add_birth(session, request.path_params['person_id'], data))
    return json_response({'birth_id': birth_id}, 201)


async def profiles(request):
    session = await authorized(request, mutate=request.method == 'POST')
    if request.method == 'GET':
        rows = await request.app.state.runtime.call(lambda store, _: People(store).profiles(session))
        return json_response({'profiles': rows})
    data = await json_body(request)
    if set(data) != {'id', 'settings'}:
        raise ValueError('Invalid profile fields')
    revision = await request.app.state.runtime.call(
        lambda store, _: People(store).add_profile(session, data['id'], data['settings']))
    return json_response({'id': data['id'], 'revision': revision}, 201)


async def charts(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'birth_id', 'profile_id', 'revision'} or \
            type(data['revision']) is not int or not 1 <= data['revision'] <= 1000:
        raise ValueError('Invalid chart version')
    result = await request.app.state.runtime.call(lambda store, _: People(store).create_chart(
        session, request.path_params['person_id'], data['birth_id'],
        data['profile_id'], data['revision']))
    return json_response(result, 201)


async def chart_exploration(request):
    session = await authorized(request)
    result = await request.app.state.runtime.call(lambda store, _: explore_chart(
        Charts(store).get_chart(session, request.path_params['chart_id'])))
    return json_response(result)


async def insights(request):
    session = await authorized(request, mutate=request.method == 'POST')
    person_id = request.path_params['person_id']
    if request.method == 'GET':
        raw = request.query_params.get('offset', '0')
        if not raw.isdigit():
            raise ValueError('Invalid insight offset')
        result = await request.app.state.runtime.call(
            lambda store, _: SavedInsights(store).list(session, person_id, int(raw)))
        return json_response(result)
    data = await json_body(request)
    if set(data) != {'id', 'conversation_id', 'source_turn_id', 'kind', 'quote', 'note'}:
        raise ValueError('Invalid saved passage')
    result = await request.app.state.runtime.call(lambda store, _: SavedInsights(store).save(
        session, person_id, data['id'], data['conversation_id'], data['source_turn_id'],
        data['kind'], data['quote'], data['note']))
    return json_response({'id': result}, 201)


async def insight_action(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'id', 'action', 'note'}:
        raise ValueError('Invalid insight action')
    await request.app.state.runtime.call(lambda store, _: SavedInsights(store).change(
        session, request.path_params['person_id'], request.path_params['entry_id'],
        data['id'], data['action'], data['note']))
    return json_response({'status': 'recorded'})


def _page(query):
    if set(query) not in ({}, {'offset'}) or any(len(query.getlist(key)) != 1 for key in query):
        raise ValueError('Invalid page')
    value = query.get('offset', '0')
    if not value.isdigit():
        raise ValueError('Invalid page')
    return int(value)


async def watchlist(request):
    session = await authorized(request, mutate=request.method == 'POST')
    person_id = request.path_params['person_id']
    if request.method == 'GET':
        offset = _page(request.query_params)
        result = await request.app.state.runtime.call(lambda store, _: Watchlist(store).list(
            session, person_id, request.app.state.runtime.clock, offset))
        return json_response(result)
    data = await json_body(request)
    if set(data) != {'id', 'result_id', 'event_index', 'note', 'reminder'}:
        raise ValueError('Choose one saved result and optional in-app reminder')
    item_id = await request.app.state.runtime.call(lambda store, _: Watchlist(store).save(
        session, person_id, data['id'], data['result_id'], data['event_index'],
        data['note'], data['reminder']))
    return json_response({'id': item_id}, 201)


async def watch_item(request):
    session = await authorized(request, mutate=True)
    person_id, item_id = request.path_params['person_id'], request.path_params['item_id']
    if request.method == 'DELETE':
        await request.app.state.runtime.call(lambda store, _: store.ledger.delete_person_record(
            store, session, person_id, item_id, 'watch_item'))
        return json_response({'status': 'deleted'})
    data = await json_body(request)
    if set(data) != {'id', 'note', 'reminder'}:
        raise ValueError('Invalid watchlist change')
    await request.app.state.runtime.call(lambda store, _: Watchlist(store).change(
        session, person_id, item_id, data['id'], data['note'], data['reminder']))
    return json_response({'status': 'recorded'})


async def journal(request):
    session = await authorized(request, mutate=request.method == 'POST')
    person_id = request.path_params['person_id']
    if request.method == 'GET':
        offset = _page(request.query_params)
        result = await request.app.state.runtime.call(lambda store, _: Journal(store).list(
            session, person_id, offset))
        return json_response(result)
    data = await json_body(request)
    if set(data) != {'id','kind','local_date','wall_time','zone','fold','linked_result_id','text'}:
        raise ValueError('Invalid private reflection')
    item_id = await request.app.state.runtime.call(lambda store, _: Journal(store).save(
        session, person_id, data['id'], data['kind'], data['local_date'], data['wall_time'],
        data['zone'], data['fold'], data['linked_result_id'], data['text']))
    return json_response({'id': item_id}, 201)


async def journal_entry(request):
    session = await authorized(request, mutate=True)
    person_id, entry_id = request.path_params['person_id'], request.path_params['entry_id']
    if request.method == 'DELETE':
        await request.app.state.runtime.call(lambda store, _: store.ledger.delete_person_record(
            store, session, person_id, entry_id, 'journal_entry'))
        return json_response({'status': 'deleted'})
    data = await json_body(request)
    if set(data) != {'id', 'text'}:
        raise ValueError('Invalid reflection edit')
    await request.app.state.runtime.call(lambda store, _: Journal(store).change(
        session, person_id, entry_id, data['id'], data['text']))
    return json_response({'status': 'recorded'})


async def context_preference(request):
    from m2.chat.personal_context import preference, set_preference
    session = await authorized(request, mutate=request.method != 'GET')
    try:
        if request.method == 'GET':
            result = await request.app.state.runtime.call(lambda store, _: preference(store, session))
        else:
            data = await json_body(request)
            if set(data) != {'enabled', 'expected_version'}:
                raise ValueError('Explicit context setting required')
            result = await request.app.state.runtime.call(lambda store, _: set_preference(
                store, session, data['enabled'], data['expected_version']))
        return json_response(result)
    except ContextConflict:
        return json_response({'error': 'context_preference_conflict'}, 409)


async def context_self(request):
    from m2.people.self_association import association, set_association
    session = await authorized(request, mutate=request.method != 'GET')
    try:
        if request.method == 'GET':
            result = await request.app.state.runtime.call(lambda store, _: association(store, session))
        else:
            data = await json_body(request)
            if set(data) != {'person_id', 'expected_version'}:
                raise ValueError('Explicit self association required')
            result = await request.app.state.runtime.call(lambda store, _: set_association(
                store, session, data['person_id'], data['expected_version']))
        return json_response(result)
    except ContextConflict:
        return json_response({'error': 'context_self_conflict'}, 409)


async def person_picker(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'query', 'after'}:
        raise ValueError('Invalid person picker search')
    result = await request.app.state.runtime.call(lambda store, _: People(store).picker(
        session, data['query'], data['after']))
    return json_response(result)


async def personal_profile(request):
    session = await authorized(request, mutate=request.method != 'GET')
    person_id = request.path_params['person_id']
    try:
        if request.method == 'GET':
            result = await request.app.state.runtime.call(lambda store, _: PersonalProfile(store).get(session, person_id))
        else:
            data = await json_body(request)
            if set(data) != {'operation_id', 'change'}:
                raise ValueError('Invalid profile operation')
            result = await request.app.state.runtime.call(lambda store, _: PersonalProfile(store).change(
                session, person_id, data['operation_id'], data['change']))
        return json_response(result)
    except ContextConflict:
        return json_response({'error': 'profile_conflict'}, 409)


async def personal_context_search(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'group', 'query', 'offset'}:
        raise ValueError('Invalid context search')
    result = await request.app.state.runtime.call(lambda store, _: PersonalContext(store).list(
        session, request.path_params['person_id'], data['group'], data['query'], data['offset']))
    return json_response(result)


async def personal_context(request):
    session = await authorized(request, mutate=request.method != 'GET')
    person_id = request.path_params['person_id']
    try:
        if request.method == 'GET':
            query = request.query_params
            if set(query) - {'group', 'offset'} or any(len(query.getlist(k)) != 1 for k in query):
                raise ValueError('Invalid context search')
            offset = query.get('offset', '0')
            if not offset.isdigit():
                raise ValueError('Invalid context page')
            result = await request.app.state.runtime.call(lambda store, _: PersonalContext(store).list(
                session, person_id, query.get('group'), '', int(offset)))
        else:
            data = await json_body(request)
            if request.method == 'DELETE':
                if set(data) != {'expected_version'}:
                    raise ValueError('Expected entry version required')
                await request.app.state.runtime.call(lambda store, _: PersonalContext(store).remove(
                    session, person_id, request.path_params['entry_id'], data['expected_version']))
                result = {'status': 'removed'}
            else:
                if set(data) != {'id', 'operation_id', 'expected_version', 'content'}:
                    raise ValueError('Invalid context change')
                result = await request.app.state.runtime.call(lambda store, _: PersonalContext(store).save(
                    session, person_id, data['id'], data['operation_id'], data['expected_version'], data['content']))
        return json_response(result)
    except ContextConflict:
        return json_response({'error': 'context_conflict'}, 409)


routes = [Route('/api/people/picker', person_picker, methods=['POST']),
          Route('/api/personal-context-preference', context_preference, methods=['GET', 'POST']),
          Route('/api/personal-context-self', context_self, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/personal-profile', personal_profile, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/context/search', personal_context_search, methods=['POST']),
          Route('/api/people/{person_id}/context', personal_context, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/context/{entry_id}', personal_context, methods=['DELETE']),
          Route('/api/charts/{chart_id}/exploration', chart_exploration, methods=['GET']),
          Route('/api/charts/{chart_id}', saved_chart, methods=['GET']),
          Route('/api/people/{person_id}/chart-library', chart_library, methods=['GET']),
          Route('/api/people/{person_id}/chart-library/{technique}', chart_library, methods=['GET']),
          Route('/api/people', people, methods=['GET', 'POST']),
          Route('/api/people/{person_id}', person, methods=['GET', 'DELETE']),
          Route('/api/people/{person_id}/drafts', drafts, methods=['POST']),
          Route('/api/places/search', places, methods=['POST']),
          Route('/api/people/{person_id}/generate', generate_chart, methods=['POST']),
          Route('/api/people/{person_id}/births', births, methods=['POST']),
          Route('/api/profiles', profiles, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/charts', charts, methods=['POST']),
          Route('/api/people/{person_id}/insights', insights, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/insights/{entry_id}', insight_action, methods=['PATCH']),
          Route('/api/people/{person_id}/watchlist', watchlist, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/watchlist/{item_id}', watch_item, methods=['PATCH', 'DELETE']),
          Route('/api/people/{person_id}/journal', journal, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/journal/{entry_id}', journal_entry, methods=['PATCH', 'DELETE'])]
