"""Thin authenticated HTTP projection of the owner-scoped people services."""

from urllib.parse import quote

from starlette.responses import Response
from starlette.routing import Route

from m2.attachments import Attachments
from m2.birth_flow import BirthFlow, BirthInputError
from m2.insights import SavedInsights
from m2.person_records import Watchlist, Journal
from m2.places import search as search_places
from m2.people import People
from m2.http.boundary import authorized, json_body, json_response


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


async def file(request):
    session = await authorized(request, mutate=request.method == 'DELETE')
    person_id, attachment_id = (request.path_params[item] for item in ('person_id', 'attachment_id'))
    if request.method == 'DELETE':
        await request.app.state.runtime.call(
            lambda store, _: store.ledger.delete_person_attachment(
                store, session, person_id, attachment_id))
        return json_response({'status': 'deleted'})
    metadata, content = await request.app.state.runtime.call(
        lambda store, _: Attachments(store).read_person(session, person_id, attachment_id))
    return Response(content, media_type=metadata['media_type'], headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(metadata['filename'])})


routes = [Route('/api/people', people, methods=['GET', 'POST']),
          Route('/api/people/{person_id}', person, methods=['GET', 'DELETE']),
          Route('/api/people/{person_id}/drafts', drafts, methods=['POST']),
          Route('/api/places/search', places, methods=['POST']),
          Route('/api/people/{person_id}/generate', generate_chart, methods=['POST']),
          Route('/api/people/{person_id}/births', births, methods=['POST']),
          Route('/api/profiles', profiles, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/charts', charts, methods=['POST']),
          Route('/api/people/{person_id}/files/{attachment_id}', file, methods=['GET', 'DELETE']),
          Route('/api/people/{person_id}/insights', insights, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/insights/{entry_id}', insight_action, methods=['PATCH']),
          Route('/api/people/{person_id}/watchlist', watchlist, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/watchlist/{item_id}', watch_item, methods=['PATCH', 'DELETE']),
          Route('/api/people/{person_id}/journal', journal, methods=['GET', 'POST']),
          Route('/api/people/{person_id}/journal/{entry_id}', journal_entry, methods=['PATCH', 'DELETE'])]
