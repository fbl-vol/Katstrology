"""Shared browser request, session and origin policy; feature routes import this boundary."""
from hashlib import sha256
import json
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from m2.product_policy import public_defaults
from m2.store import MAX_MESSAGE
from m2.web_auth import SESSION_HOURS, WebAuth

MAX_JSON = 16 * 1024
# JSON can represent one accepted UTF-8 text byte as six ASCII bytes (\\u0001).
MAX_TEXT_JSON = 6 * MAX_MESSAGE + MAX_JSON
COOKIE = 'kat_session'


class Forbidden(Exception):
    pass


def json_response(value, status=200):
    return JSONResponse(json.loads(json.dumps(value, default=str)), status_code=status)


async def json_body(request, max_bytes=MAX_JSON):
    if request.headers.get('content-type', '').split(';', 1)[0] != 'application/json':
        raise ValueError('Expected JSON')
    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > max_bytes:
            raise ValueError('Request too large')
    try:
        value = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Invalid JSON') from None
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object')
    return value


async def authorized(request, mutate=False, fast=False):
    token = request.cookies.get(COOKIE)
    runtime = request.app.state.runtime
    cached = runtime.cached(token) if fast else None
    if cached:
        session, csrf = cached
    else:
        session, csrf, expires = await runtime.call(lambda _store, auth: auth.resolve(token))
        runtime.remember(token, session, csrf, expires)
    if mutate:
        try:
            WebAuth.check_csrf(csrf, request.headers.get('x-kat-csrf'))
        except PermissionError as exc:
            raise Forbidden() from exc
    return session


async def session(request):
    token = request.cookies.get(COOKIE)
    identity, csrf, expires = await request.app.state.runtime.call(
        lambda _store, auth: auth.resolve(token))
    request.app.state.runtime.remember(token, identity, csrf, expires)
    return json_response({'owner': identity.owner_id, 'csrf': csrf,
                          'workspace': 'personal' if request.app.state.deployment else 'local synthetic',
                          'product': public_defaults()})


async def login(request):
    values = await json_body(request)
    token, csrf, identity, expires = await request.app.state.runtime.call(
        lambda _store, auth: auth.login(values.get('username'), values.get('password')))
    request.app.state.runtime.remember(token, identity, csrf, expires)
    response = json_response({'owner': identity.owner_id, 'csrf': csrf,
                              'workspace': 'personal' if request.app.state.deployment else 'local synthetic',
                              'product': public_defaults()})
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        secure=request.app.state.deployment, samesite='strict', path='/')
    return response


async def logout(request):
    await authorized(request, mutate=True)
    token = request.cookies[COOKIE]
    await request.app.state.runtime.call(lambda _store, auth: auth.logout(token))
    request.app.state.runtime.active_tokens.pop(sha256(token.encode()).hexdigest(), None)
    response = json_response({'status': 'signed_out'})
    response.delete_cookie(COOKIE, path='/', secure=request.app.state.deployment,
                           httponly=True, samesite='strict')
    return response


class LocalBoundary(BaseHTTPMiddleware):
    def __init__(self, app, origin, deployment=False):
        super().__init__(app)
        self.origin = origin
        self.host = urlsplit(origin).netloc
        self.deployment = deployment

    async def dispatch(self, request, call_next):
        # The OAuth callback and inert home document allow the exact cross-site
        # top-level return; neither grants API authority.
        cross_site_document = (request.method == 'GET'
                               and request.headers.get('sec-fetch-site') == 'cross-site'
                               and request.headers.get('sec-fetch-mode') == 'navigate'
                               and request.headers.get('sec-fetch-dest') == 'document'
                               and not request.headers.get('origin'))
        callback = (not self.deployment and cross_site_document and
                    request.url.path == '/auth/chatgpt/callback')
        home = cross_site_document and request.url.path == '/'
        if (request.headers.get('host') != self.host
                or request.headers.get('origin', self.origin) != self.origin
                or (request.headers.get('sec-fetch-site', 'same-origin') not in
                    ('same-origin', 'none') and not (callback or home))):
            response = json_response({'error': 'local_origin_required'}, 403)
        elif request.method not in ('GET', 'HEAD', 'OPTIONS') and (
                request.url.path.startswith('/api/') or request.url.path == '/auth/chatgpt/start') \
                and request.headers.get('origin') != self.origin:
            response = json_response({'error': 'local_origin_required'}, 403)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = json_response({'error': 'unavailable'}, 503)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if self.deployment:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'sha256-LedIj7WJqez/+AidF5isYsfP593k9wlonn+5ZL3Mrgc='; "
            "style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'" + ('' if self.deployment else ' https://auth.openai.com'))
        response.headers['Referrer-Policy'] = (
            'same-origin' if request.method == 'GET' and request.url.path in ('/', '/index.html')
            and response.status_code == 200 else 'no-referrer')
        return response
