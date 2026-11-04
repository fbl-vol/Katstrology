"""Authenticated manual advanced calculations; no calculation sends a message."""

from starlette.routing import Route

from m2.advanced import Advanced
from m2.periods import Periods
from m2.http.boundary import authorized, json_body, json_response


async def create(request):
    session = await authorized(request, mutate=True)
    data = await json_body(request)
    if set(data) != {'id', 'person_id', 'technique', 'parameters'}:
        raise ValueError('Specify result ID, person, technique and parameters')
    result = await request.app.state.runtime.call(lambda store, _: Advanced(store).save(
        session, data['id'], data['person_id'], data['technique'], data['parameters']))
    return json_response(result, 200 if result.get('reused') else 201)


async def list_results(request):
    session = await authorized(request)
    query = request.query_params
    if set(query) != {'person_id', 'technique'} or any(
            len(query.getlist(key)) != 1 for key in query):
        raise ValueError('Choose one person and technique')
    results = await request.app.state.runtime.call(lambda store, _: Advanced(store).list(
        session, query['person_id'], query['technique']))
    return json_response({'results': results})


async def read(request):
    session = await authorized(request)
    result = await request.app.state.runtime.call(lambda store, _: Advanced(store).get(
        session, request.path_params['result_id']))
    return json_response(result)


async def period(request):
    session = await authorized(request)
    query = request.query_params
    if set(query) != {'person_id', 'chart_id', 'start', 'end', 'offset'} or any(
            len(query.getlist(key)) != 1 for key in query) or not query['offset'].isdigit():
        raise ValueError('Select a person, source chart and bounded UTC period')
    result = await request.app.state.runtime.call(lambda store, _: Periods(store).read(
        session, query['person_id'], query['chart_id'], query['start'], query['end'],
        int(query['offset'])))
    return json_response(result)


routes = [Route('/api/advanced-results/period', period, methods=['GET']),
          Route('/api/advanced-results', create, methods=['POST']),
          Route('/api/advanced-results', list_results, methods=['GET']),
          Route('/api/advanced-results/{result_id}', read, methods=['GET'])]
