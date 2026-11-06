"""Read-only two-person view over the same authoritative synastry geometry as agent reads."""

from starlette.routing import Route

from m2.people.people import People
from m2.calculation.synastry import Synastry
from m2.http_boundary.boundary import authorized, json_response


async def compare(request):
    session = await authorized(request)
    query = request.query_params
    if (set(query) != {'person_a_id', 'person_b_id'} or
            any(len(query.getlist(key)) != 1 for key in query)):
        raise ValueError('Choose exactly two people; chart versions are resolved server-side')
    a_id, b_id = query['person_a_id'], query['person_b_id']
    if a_id == b_id:
        raise ValueError('Choose two distinct people')

    def calculate(store, _auth):
        people = People(store)
        # Resolve both current pointers in one serialized Store read. Neither
        # chart ID is supplied by the browser, and ownership is checked here.
        a = people.active_chart_id(session, a_id)
        b = people.active_chart_id(session, b_id)
        if not a or not b:
            return {'status': 'no_active_natal', 'missing_person_ids': [
                person_id for person_id, chart_id in ((a_id, a), (b_id, b)) if not chart_id]}
        return Synastry(store).view(session, a, b)

    return json_response(await request.app.state.runtime.call(calculate))


routes = [Route('/api/synastry', compare)]
