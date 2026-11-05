"""Compose browser routes around one runtime; feature routes depend only on boundaries."""
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from m2.deletion import ReferencedPersonAttachment
from m2.release_drain import AdmissionBoundary
from m2.http_boundary.boundary import Forbidden, LocalBoundary, json_response, login, logout, session
from m2.http_boundary.config import deployment_origin
from m2.http_boundary.runtime import BrowserRuntime


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
