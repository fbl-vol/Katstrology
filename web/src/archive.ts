import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from './api';
import type { Selection } from './conversation';
import type { ArchiveEvent, Turn } from './turns';

type TurnPage = { turns: Turn[]; next_offset: number | null };
export type SelectedResult = { result_id: string; event_index: number | null };
type Send = { id: string; text: string; selected_people: Selection[]; parent: string;
  revision_kind: 'normal' | 'edit' | 'regenerate'; replaces_turn_id: string | null;
  selected_result?: SelectedResult };
type Pending = { conversationId: string; payload: Send;
  failure?: { message: string; reconnect: boolean } };

function completeEvents(events: ArchiveEvent[]): ArchiveEvent[] {
  const bySequence = new Map(events.map(event => [event.sequence, event]));
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}

function checkEventPage(page: Turn, id: string, offset: number) {
  if (page.id !== id || !Number.isSafeInteger(page.event_count) ||
      !Array.isArray(page.events) || page.events.some((event, index) => event.sequence !== offset + index) ||
      (page.next_event_offset !== null && (page.next_event_offset !== offset + page.events.length ||
        page.next_event_offset <= offset || page.next_event_offset >= page.event_count)) ||
      (page.next_event_offset === null && offset + page.events.length !== page.event_count)) {
    throw new Error('Incomplete or inconsistent archived event page');
  }
}

export function useArchiveChat(workspace: Workspace | null,
  onTerminal: (conversationId: string, status: string) => void,
  view: { conversationId: string | null; visible: boolean; navigation: { current: number } }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState('');
  const [hasPending, setHasPending] = useState(false);
  const [localPending, setLocalPending] = useState<Pending | null>(null);
  const [eventFailures, setEventFailures] = useState<Record<string, string>>({});
  const eventLoads = useRef(new Set<string>());
  const openedConversation = useRef('');
  const routeVersion = useRef(view.navigation.current);
  const viewRef = useRef(view);
  viewRef.current = view;
  const lastView = useRef({ visible: false, conversationId: null as string | null });
  const identity = `${workspace?.owner || ''}:${workspace?.csrf || ''}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const connection = useRef<EventSource | null>(null);
  const pending = useRef<Pending | null>(null);
  const retryInFlight = useRef<Pending | null>(null);
  const current = useRef('');
  const navigationVersion = useRef(0);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  function disconnect() {
    connection.current?.close(); connection.current = null;
    current.current = ''; setBusy(false);
  }
  function reset() {
    navigationVersion.current++;
    openedConversation.current = '';
    disconnect(); pending.current = null; retryInFlight.current = null;
    setHasPending(false); setLocalPending(null); setSendError('');
    setEventFailures({}); setTurns([]); setNextOffset(null);
  }
  useEffect(() => () => connection.current?.close(), []);

  function mergeEvent(turnId: string, event: ArchiveEvent) {
    setTurns(existing => existing.map(turn => {
      if (turn.id !== turnId || turn.events.some(item => item.sequence === event.sequence)) return turn;
      const events = completeEvents([...turn.events, event]);
      return { ...turn, events, event_count: Math.max(turn.event_count, event.sequence + 1),
        status: ['complete', 'interrupted', 'error'].includes(event.kind) ? event.kind : turn.status };
    }));
  }

  function connect(conversationId: string, turnId: string, after = -1) {
    disconnect(); current.current = conversationId;
    setBusy(true); setSendError('');
    const source = new EventSource(`/api/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turnId)}/events?after=${after}`);
    connection.current = source;
    source.onmessage = message => {
      const event = JSON.parse(message.data) as ArchiveEvent;
      mergeEvent(turnId, event);
      if (['complete', 'interrupted', 'error'].includes(event.kind)) {
        source.close(); if (connection.current === source) connection.current = null;
        setBusy(false);
        onTerminalRef.current(conversationId, event.kind);
      }
    };
    source.onerror = () => setSendError('Stream disconnected. Reconnecting from the committed event cursor; no turn will rerun.');
  }

  function sameConversation(conversationId: string, version: number, owner: string) {
    return navigationVersion.current === version && openedConversation.current === conversationId &&
      identityRef.current === owner && viewRef.current.navigation.current === routeVersion.current;
  }

  function sameView(conversationId: string, version: number, owner: string) {
    return sameConversation(conversationId, version, owner) && viewRef.current.visible &&
      viewRef.current.conversationId === conversationId;
  }

  async function loadRemaining(conversationId: string, turn: Turn, version: number, owner: string) {
    const routeAtStart = routeVersion.current;
    const key = `${version}:${routeAtStart}:${conversationId}:${turn.id}`;
    const live = () => routeVersion.current === routeAtStart &&
      sameView(conversationId, version, owner);
    if (eventLoads.current.has(key)) return;
    eventLoads.current.add(key);
    let cursor = turn.next_event_offset;
    let collected = turn.events;
    let terminalExpected = turn.status !== 'open';
    try {
      while (cursor !== null && live()) {
        const page = await api<Turn>(`conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(turn.id)}?offset=${cursor}`);
        if (!live()) return;
        checkEventPage(page, turn.id, cursor);
        terminalExpected ||= page.status !== 'open';
        collected = completeEvents([...collected, ...page.events]);
        cursor = page.next_event_offset;
        if (cursor === null && terminalExpected &&
            !collected.some(event => ['complete', 'interrupted', 'error'].includes(event.kind)))
          throw new Error('Archived terminal event missing');
        setTurns(existing => live() ? existing.map(item => item.id === turn.id ? {
          ...item, events: completeEvents([...item.events, ...page.events]),
          event_count: Math.max(item.event_count, page.event_count),
          next_event_offset: cursor,
          status: item.status === 'open' && page.status !== 'open' ? page.status : item.status,
        } : item) : existing);
      }
      if (live() && terminalExpected &&
          !collected.some(event => ['complete', 'interrupted', 'error'].includes(event.kind))) {
        throw new Error('Archived terminal event missing');
      }
      if (live())
        setEventFailures(existing => {
          if (!live()) return existing;
          const next = { ...existing }; delete next[turn.id]; return next;
        });
    } catch {
      if (live())
        setEventFailures(existing => live() ? ({ ...existing, [turn.id]:
          'The saved reply is incomplete because part of it could not be loaded. Retry loading; this will not resend the message.' }) : existing);
    } finally {
      eventLoads.current.delete(key);
    }
  }

  async function open(conversationId: string, offset = 0) {
    if (!offset) reset();
    openedConversation.current = conversationId;
    routeVersion.current = viewRef.current.navigation.current;
    const version = navigationVersion.current;
    const owner = identityRef.current;
    const page = await api<TurnPage>(`conversations/${encodeURIComponent(conversationId)}/turns?offset=${offset}`);
    if (!sameConversation(conversationId, version, owner)) return page;
    for (const turn of page.turns) checkEventPage(turn, turn.id, 0);
    setTurns(old => sameConversation(conversationId, version, owner) ?
      (offset ? [...old, ...page.turns] : page.turns) : old);
    setNextOffset(page.next_offset);
    for (const turn of page.turns) void loadRemaining(conversationId, turn, version, owner);
    const openTurn = page.turns.find(turn => turn.status === 'open');
    if (openTurn) connect(conversationId, openTurn.id, -1);
    return page;
  }

  useEffect(() => {
    const returned = view.visible && (!lastView.current.visible ||
      lastView.current.conversationId !== view.conversationId);
    lastView.current = { visible: view.visible, conversationId: view.conversationId };
    if (!returned || !view.conversationId || view.conversationId !== openedConversation.current) return;
    routeVersion.current = view.navigation.current;
    const version = navigationVersion.current;
    const owner = identityRef.current;
    for (const turn of turns)
      if (turn.next_event_offset !== null && !eventFailures[turn.id])
        void loadRemaining(view.conversationId, turn, version, owner);
  }, [view.visible, view.conversationId, turns, identity]);

  function retryEvents(conversationId: string, turn: Turn) {
    if (openedConversation.current !== conversationId) return;
    const version = navigationVersion.current;
    const owner = identityRef.current;
    setEventFailures(existing => { const next = { ...existing }; delete next[turn.id]; return next; });
    void loadRemaining(conversationId, turn.next_event_offset === null ?
      { ...turn, next_event_offset: 0 } : turn, version, owner);
  }

  function failPending(message: string, reconnect = false) {
    if (!pending.current) return;
    pending.current = { ...pending.current, failure: { message, reconnect } };
    setLocalPending(pending.current);
    setBusy(false);
  }

  function queue(conversationId: string, text: string, selected: Selection[],
    parent = '@active', revisionKind: Send['revision_kind'] = 'normal', replaces: string | null = null,
    selectedResult?: SelectedResult) {
    if (!workspace || pending.current) return false;
    const payload: Send = { id: `turn-${crypto.randomUUID()}`, text, selected_people: selected,
      parent, revision_kind: revisionKind, replaces_turn_id: replaces,
      ...(selectedResult ? { selected_result: selectedResult } : {}) };
    const item = { conversationId, payload };
    pending.current = item; setLocalPending(item); setHasPending(true);
    return true;
  }

  async function submit(conversationId: string, text: string, selected: Selection[],
    parent = '@active', revisionKind: Send['revision_kind'] = 'normal', replaces: string | null = null) {
    if (!queue(conversationId, text, selected, parent, revisionKind, replaces)) return false;
    return retry();
  }

  async function retry() {
    const item = pending.current;
    if (!workspace || !item || retryInFlight.current) return false;
    retryInFlight.current = item;
    pending.current = { ...item, failure: undefined };
    setLocalPending(pending.current);
    setBusy(true); setSendError('');
    const version = navigationVersion.current;
    const owner = identityRef.current;
    try {
      const ack = await api<{ acknowledged: boolean; turn: Turn }>(
        `conversations/${item.conversationId}/turns`, workspace.csrf, 'POST', item.payload);
      if (!ack.acknowledged) throw new Error('Archive acknowledgement missing');
      if (version !== navigationVersion.current || owner !== identityRef.current) return true; // Original is archived; current view moved away.
      setTurns(old => old.some(turn => turn.id === ack.turn.id) ? old :
        [...old, { ...ack.turn, on_active_branch: true }]);
      pending.current = null; setHasPending(false); setLocalPending(null);
      connect(item.conversationId, item.payload.id, 0);
      return true;
    } catch (error) {
      if (version !== navigationVersion.current || owner !== identityRef.current) return false;
      if (error instanceof ApiError && error.status === 409) {
        failPending(error.code === 'fixed_model_unavailable' ?
          'This ChatGPT account cannot use the selected model. Check your connection, then retry.' :
          error.code === 'selected_account_changed' ?
            'Your ChatGPT account changed before this message was saved. Check your connection, then retry.' :
            'Connect an eligible ChatGPT plan, then retry this message.', true);
      } else if (error instanceof ApiError && error.code === 'release_maintenance') {
        failPending('Kat is updating. Your message is still here. Retry this same message in a moment.');
      } else if (error instanceof ApiError && error.status === 400) {
        failPending('This message or its selected context was not accepted. Review your selection before trying again.');
      } else {
        failPending('Saving this message was not confirmed. Retry here to check the same message without sending a duplicate.');
      }
      return false;
    } finally {
      if (retryInFlight.current === item) retryInFlight.current = null;
    }
  }

  return { turns, nextOffset, busy, sendError, hasPending, localPending, eventFailures,
    reset, disconnect, open, retryEvents, queue, submit, retry, failPending };
}
