"""Single-process browser adapter: loopback local mode or explicit HTTPS deployment."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import getpass
from ipaddress import ip_address
from hashlib import sha256
import json
import os
from time import time
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.conninfo import make_conninfo

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
from m2.store import Store, MAX_MESSAGE
from m2.release_drain import Admission, AdmissionBoundary, serve_control, SOCKET
from m2.web_auth import SESSION_HOURS, WebAuth


MAX_JSON = 16 * 1024
# JSON can represent one accepted UTF-8 text byte as six ASCII bytes (\\u0001).
# Reserve the ordinary body allowance for the bounded request envelope; other
# routes retain MAX_JSON and Store still enforces the 64 KiB text limit.
MAX_TEXT_JSON = 6 * MAX_MESSAGE + MAX_JSON
COOKIE = 'kat_session'


class Forbidden(Exception):
    pass


class BrowserRuntime:
    """One Store, on one worker thread; requests never share its transaction."""

    def __init__(self, dsn, files, ledger, siwc_factory=None, siwc_root=None, clock=None,
                 maintenance=False):
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
        self.admission = Admission(Path(files).parent / 'release-fence.json' if maintenance else None)
        self.maintenance = maintenance
        self.control_server = None

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
            if self.maintenance:
                self.control_server = await serve_control(self.admission)
        except BaseException:
            if self.store:
                await self.execute(self.store.close)
            await asyncio.to_thread(self.executor.shutdown, True)
            raise

    async def execute(self, operation):
        return await self.admission.worker(self.executor, operation)

    async def offload(self, operation, *args):
        return await self.admission.worker(None, lambda: operation(*args))

    def spawn(self, coroutine):
        return self.admission.spawn(coroutine)

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
        if self.control_server:
            self.control_server.close()
            await self.control_server.wait_closed()
            Path(SOCKET).unlink(missing_ok=True)
        if self.chat:
            self.chat.cancel_all()
        try:
            # A cancelled coroutine can still have an executor/provider call running.
            while self.admission.pending:
                await asyncio.gather(*tuple(self.admission.pending), return_exceptions=True)
            if self.store:
                await self.execute(lambda: (self.siwc.close() if self.siwc else None,
                                            self.store.close()))
        finally:
            self.active_tokens.clear()
            await asyncio.to_thread(self.executor.shutdown, True)


def deployment_origin(value):
    """Validate the public browser authority without trusting proxy headers."""
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname and
                 parsed.hostname == parsed.hostname.lower() and
                 '.' in parsed.hostname and parsed.port is None and
                 not parsed.username and not parsed.password and
                 not parsed.path and not parsed.query and not parsed.fragment and
                 value == f'https://{parsed.hostname}' and
                 not parsed.hostname.endswith('.') and
                 all(part and part.isascii() and part.replace('-', '').isalnum()
                     and not part.startswith('-') and not part.endswith('-')
                     for part in parsed.hostname.split('.')))
    except (TypeError, ValueError):
        valid = False
    if valid:
        try:
            ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            valid = False
    if not valid:
        raise ValueError('Deployment requires an exact HTTPS DNS origin without a port or path')
    return value


def deployment_dsn(password_file, host, database, user):
    """Configuration-only resolution; never use fixture discovery in deployment."""
    path = Path(password_file)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077):
        raise ValueError('Deployment database password file must be private and absolute')
    Store._id(database)
    Store._id(user)
    if host != 'db':
        raise ValueError('Deployment database must use the private Compose service')
    secret = path.read_text(encoding='utf-8').rstrip('\n')
    if not secret or '\n' in secret or '\r' in secret:
        raise ValueError('Invalid deployment database password file')
    return make_conninfo(host=host, port=5432, dbname=database, user=user, password=secret)


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
                # No raw SQL, provider payload or credentials in a browser or log.
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
        # Native same-origin sign-in forms need a real Origin header. Do not
        # forward a referrer to the provider or from the callback redirect.
        response.headers['Referrer-Policy'] = (
            'same-origin' if request.method == 'GET' and request.url.path in ('/', '/index.html')
            and response.status_code == 200 else 'no-referrer')
        return response


def create_app(dsn, files, ledger, dist, port=8765, siwc_factory=None, siwc_root=None,
               clock=None, origin=None, deployment=False):
    """Testing may supply an owned isolated DB; serving selects one explicit mode."""
    if deployment:
        origin = deployment_origin(origin)
    else:
        origin = f'http://127.0.0.1:{port}'

    dist = Path(dist)
    if not (dist / 'index.html').is_file():
        raise FileNotFoundError('Build web app first: npm --prefix web run build')
    runtime = BrowserRuntime(dsn, files, ledger, siwc_factory,
                             siwc_root or Path(files).parent / 'siwc', clock=clock,
                             maintenance=deployment)

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
    from m2.web_tones import routes as tone_routes
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
                            *tone_routes,
                            *transit_routes,
                            *synastry_routes,
                            *advanced_routes,
                            Mount('/', app=StaticFiles(directory=dist, html=True))],
                    lifespan=lifespan,
                    exception_handlers={Forbidden: on_error, PermissionError: on_error,
                                        KeyError: on_error, ValueError: on_error,
                                        ReferencedPersonAttachment: on_error,
                                        RuntimeError: on_error, Exception: on_error})
    app.add_middleware(AdmissionBoundary, admission=runtime.admission)
    app.add_middleware(LocalBoundary, origin=origin, deployment=deployment)
    app.state.runtime = runtime
    app.state.port = port
    app.state.deployment = deployment
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('serve', 'enroll'), nargs='?', default='serve')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--deployment-origin', help='Enable deployment at this exact HTTPS origin')
    parser.add_argument('--db-password-file', type=Path)
    parser.add_argument('--db-name', default='kat')
    parser.add_argument('--db-user', default='kat')
    parser.add_argument('--enable-siwc', action='store_true',
                        help='Allow only offline-enrolled ChatGPT registration in deployment')
    parser.add_argument('--state-directory', type=Path, default=ROOT / '.local',
                        help='Absolute directory containing the existing owned fixture and browser-runtime')
    parser.add_argument('--served-dist', type=Path,
                        help='Absolute path to the verified static build')
    args = parser.parse_args()
    served_dist = args.served_dist if args.served_dist is not None else ROOT / 'web/dist'
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    if not args.state_directory.is_absolute() or not served_dist.is_absolute():
        parser.error('State directory and served dist must be absolute paths')
    deployment = args.deployment_origin is not None
    if deployment:
        # Reject incomplete deployment input before any Store or fixture access.
        origin = deployment_origin(args.deployment_origin)
        if (args.db_password_file is None or args.state_directory == ROOT / '.local'
                or args.served_dist is None):
            parser.error('Deployment requires explicit private state, build and database password paths')
        dsn = deployment_dsn(args.db_password_file, 'db', args.db_name, args.db_user)
    else:
        if args.db_password_file is not None:
            parser.error('Database password file requires deployment origin')
        origin = None
        dsn = fixture_dsn(args.state_directory)
    state = args.state_directory
    files = state / 'browser-runtime/files'
    ledger = (state / 'browser-runtime/deletions/deletions.jsonl' if deployment else
              state / 'browser-runtime/deletions.jsonl')
    if args.action == 'enroll':
        username = input('Kat workspace username: ')
        password = getpass.getpass('Kat workspace password (12+ characters): ')
        with Store(dsn, files, Tombstones(ledger)) as store:
            store.register_local(username, password)
        return
    siwc_factory = None
    if args.enable_siwc or (not deployment and os.environ.get('KAT_ENABLE_SIWC') == '1'):
        from m2.siwc import ProviderBridge
        siwc_factory = ProviderBridge
    app = create_app(dsn, files, ledger, served_dist, port=args.port,
                     siwc_factory=siwc_factory, origin=origin, deployment=deployment)
    uvicorn.run(app, host='0.0.0.0' if deployment else '127.0.0.1',
                port=args.port, proxy_headers=False, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
