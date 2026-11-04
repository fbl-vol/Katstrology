"""Authenticated, read-only HTTP projection of ephemeral transit views."""

from datetime import date
import re

from starlette.routing import Route

from m2.app_clock import snapshot
from m2.people import People
from m2.product_policy import REPORTING_ZONE
from m2.transit_animation import frames
from m2.transit_views import TransitInputError, view
from m2.http_boundary.boundary import authorized, json_response


async def transit_view(request):
    session = await authorized(request)
    query = request.query_params
    if (set(query) - {'date', 'time', 'zone', 'occurrence', 'mode', 'person_id'}
            or any(len(query.getlist(key)) != 1 for key in query)
            or query.get('zone', REPORTING_ZONE) != REPORTING_ZONE):
        raise ValueError('Use the fixed reporting zone and person selection')
    mode, person_id = query.get('mode'), query.get('person_id')
    if mode not in ('sky', 'natal_transits') or (mode == 'sky' and person_id is not None):
        raise ValueError('Choose sky or one current natal')
    if mode == 'natal_transits' and not person_id:
        raise ValueError('Choose one person with an active natal')
    def calculate(store, _auth):
        chart_id = People(store).active_chart_id(session, person_id) if person_id else None
        if person_id and not chart_id:
            return {'status': 'no_active_natal', 'mode': mode, 'chart_id': None}
        return view(store, session, query.get('date'), query.get('time'), REPORTING_ZONE,
                    query.get('occurrence', 'unspecified'), mode, chart_id)
    try:
        result = await request.app.state.runtime.call(calculate)
    except TransitInputError as exc:
        return json_response({'error': exc.code}, 400)
    return json_response(result)


async def transit_frames(request):
    session = await authorized(request)
    query = request.query_params
    if (set(query) != {'from', 'to'} or
            any(len(query.getlist(key)) != 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', query[key])
                for key in ('from', 'to'))):
        raise ValueError('Choose exactly two UTC calendar dates')
    start, end = date.fromisoformat(query['from']), date.fromisoformat(query['to'])
    result = await request.app.state.runtime.call(
        lambda store, _auth: frames(store, session, request.path_params['chart_id'], start, end))
    return json_response(result)


async def application_clock(request):
    await authorized(request)
    query = request.query_params
    if set(query) - {'zone'} or len(query.getlist('zone')) != 1:
        raise ValueError('Specify exactly one IANA reporting zone')
    runtime = request.app.state.runtime
    return json_response(snapshot(runtime.clock, query['zone']))


routes = [Route('/api/transit-view', transit_view, methods=['GET']),
          Route('/api/charts/{chart_id}/transit-frames', transit_frames, methods=['GET']),
          Route('/api/clock', application_clock, methods=['GET'])]
