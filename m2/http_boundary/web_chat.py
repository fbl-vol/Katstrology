"""Idempotent turn ACK, committed SSE cursor, cancellation and owned export."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.responses import StreamingResponse
from starlette.routing import Route

from m2.archive.revisions import export_conversation
from m2.operations.product_policy import MODEL, REPORTING_ZONE
from m2.provider.siwc import ProviderFailure
from m2.http_boundary.boundary import MAX_TEXT_JSON, authorized, json_body, json_response


def _cursor(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError('Invalid event cursor') from None
    if not -1 <= result <= 1000000:
        raise ValueError('Event cursor out of bounds')
    return result


async def send(request):
    session = await authorized(request, mutate=True, fast=True)
    payload = await json_body(request, max_bytes=MAX_TEXT_JSON)
    required = {'id', 'text', 'selected_people', 'parent', 'revision_kind', 'replaces_turn_id'}
    legacy = {'mode', 'model_slug', 'chart_file', 'reporting_zone'}
    optional = {'selected_result'}
    if set(payload) - (required | legacy | optional) or required - set(payload):
        raise ValueError('Invalid chat request')
    runtime = request.app.state.runtime
    try:
        archived = await runtime.call(lambda store, _: store.read_turn(
            session, request.path_params['conv_id'], payload['id'], event_limit=1))
    except KeyError:
        archived = None
    # Replay preserves the original request's route, chart selection, file and
    # zone even after product defaults change. Never inspect credentials or bytes.
    if archived:
        original = archived['selected_people']
        new_shape = not set(payload) & legacy
        if new_shape:
            if (set(payload) - optional != required or
                    payload.get('selected_result') != archived['events'][0]['payload'].get('selected_result') or
                    not isinstance(payload['selected_people'], list)
                    or sorted(item['person_id'] for item in payload['selected_people']
                              if isinstance(item, dict) and set(item) == {'person_id'}) !=
                    [item['person_id'] for item in original]
                    or len(payload['selected_people']) != len(original)):
                raise ValueError('Archived selection differs from request')
        elif not {'mode', 'model_slug'} <= set(payload):
            raise ValueError('Incomplete legacy replay request')
        result = await runtime.chat.submit(
            session, request.path_params['conv_id'], payload['id'], payload['text'],
            payload['selected_people'], parent_id=payload['parent'],
            revision_kind=payload['revision_kind'], replaces_turn_id=payload['replaces_turn_id'],
            mode=payload.get('mode', 'chatgpt'), model_slug=payload.get('model_slug', MODEL),
            chart_file=payload.get('chart_file'),
            reporting_zone=(REPORTING_ZONE if new_shape else payload.get('reporting_zone')),
            archived_selection=([{'person_id': item['person_id'], 'chart_id': item['chart_id']}
                                 for item in original] if new_shape else None),
            selected_result=payload.get('selected_result'))
        return json_response(result, 202)

    # A new browser turn has no client-controlled provider, model, zone or file.
    if (set(payload) - optional != required or not isinstance(payload['selected_people'], list)
            or any(not isinstance(item, dict) or set(item) != {'person_id'}
                   for item in payload['selected_people'])):
        raise ValueError('New chat accepts person IDs, not chart versions or files')
    bridge = runtime.siwc
    if not bridge:
        return json_response({'error': 'chatgpt_plan_permission_required'}, 409)
    try:
        admission = await runtime.offload(bridge.admit, session.owner_id, MODEL)
    except ProviderFailure as failure:
        code = ('chatgpt_plan_permission_required' if failure.reason ==
                'chatgpt_plan_permission_required' else
                'selected_account_changed' if failure.reason == 'selected_account_changed' else
                'fixed_model_unavailable')
        return json_response({'error': code}, 409)
    try:
        result = await runtime.chat.submit(
            session, request.path_params['conv_id'], payload['id'], payload['text'],
            payload['selected_people'], parent_id=payload['parent'],
            revision_kind=payload['revision_kind'], replaces_turn_id=payload['replaces_turn_id'],
            mode='chatgpt', model_slug=MODEL, reporting_zone=REPORTING_ZONE,
            resolve_active=True, admission=admission,
            selected_result=payload.get('selected_result'))
    except ProviderFailure:
        return json_response({'error': 'selected_account_changed'}, 409)
    return json_response(result, 202)


async def events(request):
    session = await authorized(request, fast=True)
    conv_id, turn_id = request.path_params['conv_id'], request.path_params['turn_id']
    # Read ownership even when a completed job is still in the in-memory ring.
    # For an active same-owner job the ACK has already committed and established
    # the owner through the authenticated Store session.
    job = request.app.state.runtime.chat.jobs.get((session.owner_id, conv_id, turn_id))
    if not job:
        await request.app.state.runtime.call(lambda store, _: store.read_turn(
            session, conv_id, turn_id, event_limit=1))
    after = _cursor(request.headers.get('last-event-id', request.query_params.get('after', '-1')))

    async def stream():
        async for event in request.app.state.runtime.chat.events(session, conv_id, turn_id, after):
            if event is None:
                yield ': keepalive\n\n'
                continue
            payload = json.dumps(event, default=str, ensure_ascii=False)
            yield f'id: {event["sequence"]}\ndata: {payload}\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream', headers={
        'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})


async def cancel(request):
    session = await authorized(request, mutate=True, fast=True)
    conv_id, turn_id = request.path_params['conv_id'], request.path_params['turn_id']
    if request.app.state.runtime.chat.cancel(session.owner_id, conv_id, turn_id):
        return json_response({'status': 'cancellation_requested'})
    turn = await request.app.state.runtime.call(
        lambda store, _: store.read_turn(session, conv_id, turn_id, event_limit=1))
    return json_response({'status': turn['status']})


async def export(request):
    session = await authorized(request, mutate=True)
    conv_id = request.path_params['conv_id']
    runtime = request.app.state.runtime

    def write(store, _auth):
        directory = TemporaryDirectory(prefix='export-', dir=store.files)
        try:
            path = Path(directory.name) / 'conversation.jsonl'
            export_conversation(store, session, conv_id, path)
            return directory, path
        except BaseException:
            directory.cleanup()
            raise

    directory, path = await runtime.call(write)

    async def stream():
        try:
            with path.open('rb') as archive:
                while chunk := archive.read(64 * 1024):
                    yield chunk
        finally:
            directory.cleanup()

    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={
        'Content-Disposition': 'attachment; filename="conversation-export.jsonl"',
        'Cache-Control': 'no-store'})


routes = [Route('/api/conversations/{conv_id}/turns', send, methods=['POST']),
          Route('/api/conversations/{conv_id}/turns/{turn_id}/events', events),
          Route('/api/conversations/{conv_id}/turns/{turn_id}/cancel', cancel,
                methods=['POST']),
          Route('/api/conversations/{conv_id}/export', export, methods=['POST'])]
