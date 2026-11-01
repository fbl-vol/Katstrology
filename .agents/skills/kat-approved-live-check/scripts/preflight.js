async (page) => {
  const result = await page.evaluate(async () => {
    const digest = async value => Array.from(new Uint8Array(await crypto.subtle.digest(
      'SHA-256', new TextEncoder().encode(value)))).map(byte => byte.toString(16).padStart(2, '0')).join('');
    const input = document.querySelector('textarea#message');
    const send = document.querySelector('button[aria-label="Send message"]');
    const scope = Array.from(document.querySelectorAll('.scope-row .person-chip'))
      .map(node => [node.getAttribute('data-kat-person-id'), node.getAttribute('data-kat-chart-id') || null])
      .sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
    const model = document.querySelector('.model-label')?.textContent || '';
    return { origin: location.origin, conversation_id: document.querySelector('.conversation')?.getAttribute('data-kat-conversation-id') || null,
      model_slug: model.includes('ChatGPT plan') ? model.split(' · ')[0] : null,
      question_sha256: input ? await digest(input.value) : null,
      question_length: input?.value.length || 0,
      scope_sha256: await digest(JSON.stringify(scope)), scope_count: scope.length,
      previous_turns: document.querySelectorAll('.turn-card[data-kat-turn-id]').length,
      send_ready: !!(input && send && !send.disabled && send.getClientRects().length),
      dialog_open: !!document.querySelector('dialog[open]') };
  });
  return 'KAT_META:' + JSON.stringify(result);
}
