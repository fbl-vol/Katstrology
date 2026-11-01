"""Single-process, loopback-only browser adapter for the owned synthetic archive."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import getpass
from hashlib import sha256
import json
import os
from time import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
import uvicorn

from m2.deletion import ReferencedPersonAttachment, Tombstones
from m2.local_fixture import ROOT, fixture_dsn
from m2.product_policy import public_defaults
from m2.store import Store
from m2.web_auth import SESSION_HOURS, WebAuth


MAX_JSON = 16 * 1024
COOKIE = 'kat_session'


class Forbidden(Exception):
    pass


class BrowserRuntime:
    """One Store, on one worker thread; requests never share its transaction."""

    def __init__(self, dsn, files, ledger, siwc_factory=None, siwc_root=None, clock=None):
        from m2.app_clock import utc_now
        self.dsn, self.files, self.ledger = dsn, files, ledger
        self.clock = clock or utc_now
        self.siwc_factory, self.siwc_root = siwc_factory, siwc_root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kat-store')
        self.store = None
        self.auth = None
        self.active_tokens = {}
        self.chat = None
        self.siwc = None

    async def start(self):
        def connect():
            store = Store(self.dsn, self.files, Tombstones(self.ledger))
            try:
                store.recover_open()
                self.store, self.auth = store, WebAuth(store)
            except BaseException:
                store.close()
                raise
        try:
            await self.execute(connect)
            from m2.chat_jobs import ChatJobs
            self.chat = ChatJobs(self)
            if self.siwc_factory:
                self.siwc = await self.execute(lambda: self.siwc_factory(self.siwc_root))
        except BaseException:
            if self.store:
                await self.execute(self.store.close)
            await asyncio.to_thread(self.executor.shutdown, True)
            raise

    async def execute(self, operation):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, operation)

    async def call(self, operation):
        return await self.execute(lambda: operation(self.store, self.auth))

    def remember(self, token, session, csrf, expires):
        self.active_tokens[sha256(token.encode()).hexdigest()] = (session, csrf, expires.timestamp())

    def cached(self, token):
        if token and self.store and not self.store._blocked:
            row = self.active_tokens.get(sha256(token.encode()).hexdigest())
            if row and row[2] > time():
                return row[:2]
        return None

    async def stop(self):
        if self.chat:
            self.chat.cancel_all()
        try:
            if self.store:
                await self.execute(lambda: (self.siwc.close() if self.siwc else None,
                                            self.store.close()))
        finally:
            self.active_tokens.clear()
            await asyncio.to_thread(self.executor.shutdown, True)


def json_response(value, status=200):
    return JSONResponse(json.loads(json.dumps(value, default=str)), status_code=status)


async def json_body(request):
    if request.headers.get('content-type', '').split(';', 1)[0] != 'application/json':
        raise ValueError('Expected JSON')
    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > MAX_JSON:
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
                          'workspace': 'local synthetic', 'product': public_defaults()})


async def login(request):
    values = await json_body(request)
    token, csrf, identity, expires = await request.app.state.runtime.call(
        lambda _store, auth: auth.login(values.get('username'), values.get('password')))
    request.app.state.runtime.remember(token, identity, csrf, expires)
    response = json_response({'owner': identity.owner_id, 'csrf': csrf,
                              'workspace': 'local synthetic', 'product': public_defaults()})
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        samesite='strict', path='/')
    return response


async def logout(request):
    await authorized(request, mutate=True)
    token = request.cookies[COOKIE]
    await request.app.state.runtime.call(lambda _store, auth: auth.logout(token))
    request.app.state.runtime.active_tokens.pop(sha256(token.encode()).hexdigest(), None)
    response = json_response({'status': 'signed_out'})
    response.delete_cookie(COOKIE, path='/')
    return response


class LocalBoundary(BaseHTTPMiddleware):
    def __init__(self, app, origin):
        super().__init__(app)
        self.origin = origin
        self.host = origin.removeprefix('http://')

    async def dispatch(self, request, call_next):
        # A loopback listener is not enough: DNS rebinding and cross-site
        # requests must never turn browser cookies into ambient authority.
        # A cross-site OAuth return may retain its fetch-site through the 303
        # to the static home document. Neither GET grants API authority: the
        # callback verifies one-time state; the inert home only loads the UI.
        cross_site_document = (request.method == 'GET'
                               and request.headers.get('sec-fetch-site') == 'cross-site'
                               and request.headers.get('sec-fetch-mode') == 'navigate'
                               and request.headers.get('sec-fetch-dest') == 'document'
                               and not request.headers.get('origin'))
        callback = cross_site_document and request.url.path == '/auth/chatgpt/callback'
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
                # No raw SQL, provider payload or credentials in a browser or log.
                response = json_response({'error': 'unavailable'}, 503)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'sha256-KMBSMe9gJmMa/C3ahcFCoD5UGi47Jz2co6hC6tczP1s='; "
            "style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self' https://auth.openai.com")
        # Native same-origin sign-in forms need a real Origin header. Do not
        # forward a referrer to the provider or from the callback redirect.
        response.headers['Referrer-Policy'] = (
            'same-origin' if request.method == 'GET' and request.url.path in ('/', '/index.html')
            and response.status_code == 200 else 'no-referrer')
        return response


def create_app(dsn, files, ledger, dist, port=8765, siwc_factory=None, siwc_root=None,
               clock=None):
    """Testing may supply an owned isolated DB; supported serving uses fixture_dsn."""
    dist = Path(dist)
    if not (dist / 'index.html').is_file():
        raise FileNotFoundError('Build web app first: npm --prefix web run build')
    runtime = BrowserRuntime(dsn, files, ledger, siwc_factory,
                             siwc_root or Path(files).parent / 'siwc', clock=clock)

    @asynccontextmanager
    async def lifespan(_app):
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    async def on_error(_request, exc):
        if isinstance(exc, Forbidden):
            return json_response({'error': 'request_denied'}, 403)
        if isinstance(exc, PermissionError):
            return json_response({'error': 'authentication_required'}, 401)
        if isinstance(exc, KeyError):
            return json_response({'error': 'not_found'}, 404)
        if isinstance(exc, ReferencedPersonAttachment):
            return json_response({'error': 'attachment_in_use',
                                  'conversations': exc.conversations, 'more': exc.more}, 409)
        if isinstance(exc, ValueError):
            return json_response({'error': 'invalid_request'}, 400)
        return json_response({'error': 'unavailable'}, 503)

    from m2.web_people import routes as people_routes
    from m2.web_conversations import routes as conversation_routes
    from m2.web_chat import routes as chat_routes
    from m2.web_siwc import routes as siwc_routes
    from m2.web_transits import routes as transit_routes
    from m2.web_synastry import routes as synastry_routes
    from m2.web_advanced import routes as advanced_routes

    app = Starlette(routes=[Route('/api/session', session),
                            Route('/api/login', login, methods=['POST']),
                            Route('/api/logout', logout, methods=['POST']),
                            *people_routes,
                            *conversation_routes,
                            *chat_routes,
                            *siwc_routes,
                            *transit_routes,
                            *synastry_routes,
                            *advanced_routes,
                            Mount('/', app=StaticFiles(directory=dist, html=True))],
                    lifespan=lifespan,
                    exception_handlers={Forbidden: on_error, PermissionError: on_error,
                                        KeyError: on_error, ValueError: on_error,
                                        ReferencedPersonAttachment: on_error,
                                        RuntimeError: on_error, Exception: on_error})
    app.add_middleware(LocalBoundary, origin=f'http://127.0.0.1:{port}')
    app.state.runtime = runtime
    app.state.port = port
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'enroll'), nargs='?', default='serve')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    files = ROOT / '.local/browser-runtime/files'
    ledger = ROOT / '.local/browser-runtime/deletions.jsonl'
    dsn = fixture_dsn()  # only the currently owned local PostgreSQL fixture
    if args.action == 'enroll':
        username = input('Synthetic local username: ')
        password = getpass.getpass('Synthetic local password (12+ characters): ')
        with Store(dsn, files, Tombstones(ledger)) as store:
            store.register_local(username, password)
        return
    siwc_factory = None
    if os.environ.get('KAT_ENABLE_SIWC') == '1':
        from m2.siwc import ProviderBridge
        siwc_factory = ProviderBridge
    app = create_app(dsn, files, ledger, ROOT / 'web/dist', port=args.port,
                     siwc_factory=siwc_factory)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
