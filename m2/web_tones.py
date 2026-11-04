"""Authenticated Kat-account tone preference; never accepts prompt text or an owner selector."""

from starlette.routing import Route

from m2.store import ToneConflict
from m2.tone_profiles import catalogue
from m2.http.boundary import authorized, json_body, json_response


async def read(request):
    session = await authorized(request)
    value = await request.app.state.runtime.call(lambda store, _: store.tone_preference(session))
    return json_response({**value, **catalogue()})


async def select(request):
    session = await authorized(request, mutate=True)
    body = await json_body(request)
    if set(body) != {'tone_id', 'revision'}:
        raise ValueError('Expected a tone ID and current revision')
    try:
        value = await request.app.state.runtime.call(lambda store, _: store.set_tone_preference(
            session, body['tone_id'], body['revision']))
    except ToneConflict:
        return json_response({'error': 'tone_preference_changed'}, 409)
    return json_response(value)


routes = [Route('/api/settings/tone', read),
          Route('/api/settings/tone', select, methods=['PUT'])]
