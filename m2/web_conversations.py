"""Bounded conversation listing and original-preserving branch/revision HTTP views."""

from starlette.routing import Route

from m2.conversations import Conversations
from m2.revisions import correct, select_branch
from m2.http.boundary import MAX_TEXT_JSON, authorized, json_body, json_response


def _offset(request):
    raw = request.query_params.get('offset', '0')
    if not raw.isdigit():
        raise ValueError('Invalid page offset')
    return int(raw)


async def conversations(request):
    session = await authorized(request, mutate=request.method == 'POST')
    if request.method == 'GET':
        result = await request.app.state.runtime.call(lambda store, _: Conversations(store).list(
            session, person_id=request.query_params.get('person'), offset=_offset(request)))
        return json_response(result)
    payload = await json_body(request)
    if set(payload) != {'id', 'title', 'people'}:
        raise ValueError('Invalid conversation scope')
    result = await request.app.state.runtime.call(lambda store, _: Conversations(store).create(
        session, payload['id'], payload['title'], payload['people']))
    return json_response(result, 201)


async def search_conversations(request):
    session = await authorized(request, mutate=True)
    payload = await json_body(request)
    if set(payload) != {'query', 'person', 'offset'}:
        raise ValueError('Invalid conversation search')
    result = await request.app.state.runtime.call(lambda store, _: Conversations(store).list(
        session, person_id=payload['person'], query=payload['query'], offset=payload['offset']))
    return json_response(result)


async def conversation(request):
    session = await authorized(request, mutate=request.method != 'GET')
    conv_id = request.path_params['conv_id']
    if request.method == 'PATCH':
        payload = await json_body(request)
        if set(payload) != {'title'}:
            raise ValueError('Invalid conversation title')
        result = await request.app.state.runtime.call(
            lambda store, _: Conversations(store).rename(session, conv_id, payload['title']))
        return json_response(result)
    if request.method == 'DELETE':
        await request.app.state.runtime.call(
            lambda store, _: store.ledger.delete_conversation(store, session, conv_id))
        return json_response({'status': 'deleted'})
    row = await request.app.state.runtime.call(lambda store, _: Conversations(store).get(session, conv_id))
    return json_response(row)


async def turns(request):
    session = await authorized(request)
    result = await request.app.state.runtime.call(lambda store, _: Conversations(store).turns(
        session, request.path_params['conv_id'], offset=_offset(request)))
    return json_response(result)


async def turn(request):
    session = await authorized(request)
    result = await request.app.state.runtime.call(lambda store, _: store.read_turn(
        session, request.path_params['conv_id'], request.path_params['turn_id'],
        event_offset=_offset(request), event_limit=64))
    return json_response(result)


async def branch(request):
    session = await authorized(request, mutate=True)
    payload = await json_body(request)
    if set(payload) != {'head'} or payload['head'] is not None and not isinstance(payload['head'], str):
        raise ValueError('Invalid selected head')
    head = await request.app.state.runtime.call(lambda store, _: select_branch(
        store, session, request.path_params['conv_id'], payload['head']))
    request.app.state.runtime.chat._schedule_rebuild(session, request.path_params['conv_id'])
    return json_response({'active_head': head})


async def correction(request):
    session = await authorized(request, mutate=True)
    payload = await json_body(request, max_bytes=MAX_TEXT_JSON)
    if set(payload) != {'id', 'source_turn', 'action', 'replacement'}:
        raise ValueError('Invalid correction')
    created = await request.app.state.runtime.call(lambda store, _: correct(
        store, session, request.path_params['conv_id'], payload['id'],
        payload['source_turn'], payload['action'], payload['replacement']))
    if created:
        request.app.state.runtime.chat._schedule_rebuild(session, request.path_params['conv_id'])
    return json_response({'created': created})


routes = [Route('/api/conversations', conversations, methods=['GET', 'POST']),
          Route('/api/conversations/search', search_conversations, methods=['POST']),
          Route('/api/conversations/{conv_id}', conversation, methods=['GET', 'PATCH', 'DELETE']),
          Route('/api/conversations/{conv_id}/turns', turns),
          Route('/api/conversations/{conv_id}/turns/{turn_id}', turn),
          Route('/api/conversations/{conv_id}/branch', branch, methods=['POST']),
          Route('/api/conversations/{conv_id}/corrections', correction, methods=['POST'])]
