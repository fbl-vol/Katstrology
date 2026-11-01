async (page) => {
  const result = await page.evaluate(async () => {
    const digest = async value => Array.from(new Uint8Array(await crypto.subtle.digest(
      'SHA-256', new TextEncoder().encode(value)))).map(byte => byte.toString(16).padStart(2, '0')).join('');
    const region = document.querySelector('.conversation[data-kat-conversation-id]');
    const turns = Array.from(document.querySelectorAll('.turn-card[data-kat-turn-id]'));
    if (!region || !turns.length) return { status: 'pending', visible_turns: turns.length };
    const conv = region.getAttribute('data-kat-conversation-id');
    const id = turns[turns.length - 1].getAttribute('data-kat-turn-id');
    if (!conv || !id) return { status: 'pending', visible_turns: turns.length };
    let offset = 0, pages = 0, eventCount = 0, answerLength = 0, calls = 0, results = 0,
        artifacts = 0, completeMarkers = 0, errorCode = null, status = 'open', scope = [], model = null;
    do {
      if (++pages > 32) return { status: 'pagination_exceeded', pages };
      const response = await fetch('/api/conversations/' + encodeURIComponent(conv) +
        '/turns/' + encodeURIComponent(id) + '?offset=' + offset, { credentials: 'same-origin' });
      if (!response.ok) return { status: 'archive_unavailable', http_status: response.status };
      const turn = await response.json();
      status = turn.status;
      scope = (turn.selected_people || []).map(row => [row.person_id, row.chart_id || null])
        .sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
      eventCount = turn.event_count;
      for (const event of turn.events || []) {
        const payload = event.payload || {};
        if (event.kind === 'user') model = payload.model_slug || null;
        if (event.kind === 'assistant_chunk') answerLength += typeof payload.content === 'string' ? payload.content.length : 0;
        if (event.kind === 'tool_call') calls++;
        if (event.kind === 'tool_result') {
          results++;
          if (payload.name === 'get_transit_view') artifacts++;
        }
        if (event.kind === 'complete') completeMarkers++;
        if (event.kind === 'error') errorCode = /^[a-zA-Z0-9_]{1,60}$/.test(payload.code || '') ? payload.code : 'other';
      }
      offset = turn.next_event_offset;
    } while (offset !== null);
    return { status, pages, event_count: eventCount, answer_length: answerLength,
      tool_calls: calls, tool_results: results, transit_artifacts: artifacts,
      complete_markers: completeMarkers, terminal_error_code: errorCode,
      scope_sha256: await digest(JSON.stringify(scope)), model_slug: model,
      visible_turns: turns.length, turn_id_sha256: await digest(id) };
  });
  return 'KAT_META:' + JSON.stringify(result);
}
