"""Provider settings stay separate from the local workspace account/session."""

from hashlib import sha256
from urllib.parse import parse_qs

from starlette.responses import RedirectResponse
from starlette.routing import Route

from m2.product_policy import MODEL
from m2.provider_media import VISION_MODELS
from m2.http_boundary.boundary import COOKIE, Forbidden, authorized, json_body, json_response
from m2.web_auth import WebAuth


STATE_COOKIE = 'kat_siwc_state'


async def status(request):
    session = await authorized(request, fast=True)
    bridge = request.app.state.runtime.siwc
    result = bridge.status(session.owner_id) if bridge else {
        'available': False, 'connected': False, 'accounts': [], 'selected': None,
        'phase': 'not_connected'}
    return json_response({**result, 'registration':
                          'offline' if request.app.state.deployment else 'local'})


async def begin(request):
    if request.app.state.deployment:
        return json_response({'error': 'offline_registration_required'}, 404)
    runtime = request.app.state.runtime
    bridge = runtime.siwc
    if not bridge:
        raise ValueError('ChatGPT plan connection is disabled')
    session = await authorized(request, fast=True)
    content = await request.body()
    if len(content) > 512 or request.headers.get('content-type', '').split(';', 1)[0] != 'application/x-www-form-urlencoded':
        raise ValueError('Invalid local sign-in form')
    fields = parse_qs(content.decode('ascii'), keep_blank_values=True, strict_parsing=True)
    if set(fields) != {'csrf', 'client_id'} or any(len(value) != 1 for value in fields.values()):
        raise ValueError('Invalid local sign-in fields')
    try:
        WebAuth.check_csrf(runtime.cached(request.cookies.get(COOKIE))[1], fields['csrf'][0])
    except PermissionError as exc:
        raise Forbidden() from exc
    callback = f'http://127.0.0.1:{request.app.state.port}/auth/chatgpt/callback'
    digest = sha256(request.cookies[COOKIE].encode()).hexdigest()
    state, url = await runtime.call(lambda _store, _: bridge.begin(
        session.owner_id, digest, callback, fields['client_id'][0] or None))
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(STATE_COOKIE, state, httponly=True, samesite='lax',
                        max_age=600, path='/auth/chatgpt/callback')
    return response


async def callback(request):
    if request.app.state.deployment:
        return json_response({'error': 'offline_registration_required'}, 404)
    runtime = request.app.state.runtime
    result = 'failed'
    if runtime.siwc:
        state = request.query_params.get('state')
        cookie = request.cookies.get(STATE_COOKIE)
        try:
            def complete(store, _auth):
                def live_session(owner, digest):
                    return bool(store.db.execute('''
                        SELECT 1 FROM web_sessions WHERE owner_id=%s AND token_digest=%s
                        AND expires_at > clock_timestamp()
                    ''', (owner, digest)).fetchone())
                return runtime.siwc.complete(state, cookie, request.query_params,
                                             live_session)['status']
            result = await runtime.call(complete)
        except Exception:
            # Never echo callback codes, state, token diagnostics or hints.
            result = 'failed'
    response = RedirectResponse('/?connection=' + result, status_code=303)
    response.delete_cookie(STATE_COOKIE, path='/auth/chatgpt/callback')
    return response


async def models(request):
    session = await authorized(request, fast=True)
    bridge = request.app.state.runtime.siwc
    if not bridge:
        raise ValueError('ChatGPT plan is disabled')
    result = await request.app.state.runtime.offload(bridge.models, session.owner_id)
    return json_response({'models': [{**item, 'file_input_supported':
                                      item['slug'] in VISION_MODELS} for item in result],
                          'chat_available': any(item['slug'] == MODEL for item in result)})


async def choose(request):
    session = await authorized(request, mutate=True, fast=True)
    bridge = request.app.state.runtime.siwc
    if not bridge:
        raise ValueError('ChatGPT plan is disabled')
    payload = await json_body(request)
    if set(payload) != {'client_id'} or not isinstance(payload['client_id'], str):
        raise ValueError('Invalid saved account')
    return json_response(await request.app.state.runtime.offload(bridge.choose, session.owner_id,
                                                  payload['client_id']))


async def disconnect(request):
    session = await authorized(request, mutate=True, fast=True)
    bridge = request.app.state.runtime.siwc
    if not bridge:
        raise ValueError('ChatGPT plan is disabled')
    return json_response(await request.app.state.runtime.offload(bridge.revoke, session.owner_id))


routes = [Route('/api/siwc/status', status),
          Route('/auth/chatgpt/start', begin, methods=['POST']),
          Route('/auth/chatgpt/callback', callback),
          Route('/api/siwc/models', models),
          Route('/api/siwc/select', choose, methods=['POST']),
          Route('/api/siwc/disconnect', disconnect, methods=['POST'])]
