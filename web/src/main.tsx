import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, ApiError, type Workspace } from './api';
import { useArchiveChat, type SelectedResult } from './archive';
import { LocalPendingMessage } from './local-pending';
import { ConversationBrowseList, ScopeChips, ScopePicker, type Conversation, type Selection } from './conversation';
import { ContextChart } from './context-chart';
import { TurnCard, type Turn, type TurnActions } from './turns';
import { CreatePersonDialog, PersonDetail, type Person } from './people';
import { useProvider } from './provider';
import { SettingsView } from './settings';
import { SourceNotice } from './source-notice';
import { TransitView } from './transit-view';
import { ChartHub, type ChartChoice } from './chart-hub';
import { AdvancedView, type AdvancedDraft } from './advanced-view';
import { McTransitsView } from './mc-transits-view';
import { ProgressionsView } from './progressions-view';
import { RelationshipDerivedView } from './relationship-derived-view';
import { SolarArcView } from './solar-arc-view';
import { ProgressedPhasesView } from './progressed-phases-view';
import { LunationsView } from './lunations-view';
import { PlanetaryReturnsView, type PlanetaryReturnDraft } from './planetary-returns-view';
import { useGrowingComposer } from './chat-scroll';
import { SynastryView } from './synastry-view';
import './style.css';
import './themes.css';

type ThreadPage = { conversations: Conversation[]; next_offset: number | null; search_pending: number };
type Edit = { parent: string; replaces: string; kind: 'edit' | 'regenerate' };
function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [drawer, setDrawer] = useState(false);
  const [people, setPeople] = useState<Person[]>([]);
  const [person, setPerson] = useState<Person | null>(null);
  const [skyOpen, setSkyOpen] = useState(false);
  const [skyFromHub, setSkyFromHub] = useState(false);
  const [chartHub, setChartHub] = useState<ChartChoice | null>(null);
  const [profileChildFocus, setProfileChildFocus] = useState(false);
  const [profileFromHub, setProfileFromHub] = useState(false);
  const [profileChartFocus, setProfileChartFocus] = useState(false);
  const [profileEditorRequest, setProfileEditorRequest] = useState(0);
  const hubPreviousPerson = useRef<Person | null>(null);
  const hubPreviousFilter = useRef<string | null>(null);
  const returnToAdvanced = useRef<{ choice: 'solar_return' | 'lunar_return'; draft: AdvancedDraft } | null>(null);
  const advancedDraft = useRef<AdvancedDraft | null>(null);
  const returnToPlanetary = useRef<PlanetaryReturnDraft | null>(null);
  const planetaryDraft = useRef<PlanetaryReturnDraft | null>(null);
  const [personDialog, setPersonDialog] = useState(false);
  const [profileEditorPersonId, setProfileEditorPersonId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [scopePicker, setScopePicker] = useState(false);
  const [selection, setSelection] = useState<Selection[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [filterPersonId, setFilterPersonId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searched, setSearched] = useState('');
  const [nextConversationOffset, setNextConversationOffset] = useState<number | null>(null);
  const [listStatus, setListStatus] = useState('');
  const [message, setMessage] = useState('');
  const [discuss, setDiscuss] = useState<{ selected: SelectedResult; label: string } | null>(null);
  const chatComposer = useGrowingComposer(message);
  const [editing, setEditing] = useState<Edit | null>(null);
  const pendingConversationId = useRef('');
  const submissionInFlight = useRef(false);
  const submissionVersion = useRef(0);
  const [preparingSend, setPreparingSend] = useState(false);
  const navigationVersion = useRef(0);
  const listRequestVersion = useRef(0);
  const peopleRequestVersion = useRef(0);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const chartNavButton = useRef<HTMLButtonElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsOpener = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const historyHeading = useRef<HTMLHeadingElement>(null);
  const focusProfile = useRef<{ id: string; navigation: number } | null>(null);
  const personDialogOpener = useRef<HTMLElement | null>(null);
  const wasDrawerOpen = useRef(false);
  const setMessageInput = useCallback((element: HTMLTextAreaElement | null) => {
    chatComposer.input(element);
    messageInput.current = element;
  }, [chatComposer.input]);

  useEffect(() => {
    api<Workspace>('session').then(setWorkspace).catch((error: unknown) => {
      if (!(error instanceof ApiError && error.status === 401)) setNotice('Workspace unavailable. Check the local server.');
    }).finally(() => setLoading(false));
  }, []);

  const refreshPeople = useCallback(async () => {
    const version = ++peopleRequestVersion.current;
    const result = await api<{ people: Person[] }>('people');
    if (version !== peopleRequestVersion.current) return;
    setPeople(result.people);
    if (person) {
      const updated = await api<Person>(`people/${person.id}`);
      if (version === peopleRequestVersion.current)
        setPerson(current => current?.id === person.id ? updated : current);
    }
  }, [person?.id]);

  const loadThreads = useCallback(async (offset = 0, text = searched) => {
    if (!workspace) return;
    const version = ++listRequestVersion.current;
    setListStatus('Loading conversations…');
    try {
      const result = text ? await api<ThreadPage>('conversations/search', workspace.csrf, 'POST',
        { query: text, person: filterPersonId, offset }) :
        await api<ThreadPage>(`conversations${filterPersonId ? `?person=${encodeURIComponent(filterPersonId)}&offset=${offset}` : `?offset=${offset}`}`);
      if (version !== listRequestVersion.current) return;
      setConversations(old => offset ? [...old, ...result.conversations] : result.conversations);
      setNextConversationOffset(result.next_offset);
      setListStatus(result.search_pending ? 'Search indexing is pending; results may be incomplete.' : '');
    } catch {
      if (version === listRequestVersion.current) setListStatus('Conversations unavailable. Retry the search.');
    }
  }, [workspace?.owner, filterPersonId, searched]);

  async function refreshTitleAfterCompletion(id: string) {
    const version = navigationVersion.current;
    for (let attempt = 0; attempt < 8; attempt++) {
      await new Promise(resolve => window.setTimeout(resolve, 1500));
      if (navigationVersion.current !== version) return;
      try {
        const updated = await api<Conversation>(`conversations/${id}`);
        if (navigationVersion.current !== version) return;
        setConversation(current => current?.id === id ? updated : current);
        if (updated.title_status === 'generated') { void loadThreads(0); return; }
        if (updated.title_status !== 'waiting' && updated.title_status !== 'pending') return;
      } catch { return; }
    }
  }

  const provider = useProvider(workspace);
  const archive = useArchiveChat(workspace, (id, status) => {
    void api<Conversation>(`conversations/${id}`).then(updated =>
      setConversation(current => current?.id === id ? updated : current)).catch(() => {});
    void loadThreads(0);
    if (status === 'complete') void refreshTitleAfterCompletion(id);
  }, { conversationId: conversation?.id || null,
    visible: !person && !skyOpen && !chartHub && !settingsOpen,
    navigation: navigationVersion });

  const headNotLoaded = !!conversation?.active_head &&
    !archive.turns.some(turn => turn.id === conversation.active_head);
  const pendingTurnId = archive.localPending?.payload.id;
  const submittedReveal = useRef<{ id: string; navigation: number; scrollY?: number } | null>(null);
  useLayoutEffect(() => {
    if (pendingTurnId && submittedReveal.current?.id !== pendingTurnId)
      submittedReveal.current = { id: pendingTurnId, navigation: navigationVersion.current };
    const reveal = submittedReveal.current;
    if (!reveal || reveal.navigation !== navigationVersion.current || person || skyOpen || chartHub || settingsOpen) return;
    // An ACK may arrive after the reader deliberately scrolls away from the new message.
    if (reveal.scrollY !== undefined && Math.abs(window.scrollY - reveal.scrollY) > 8) return;
    const pending = document.querySelector<HTMLElement>('.local-pending');
    const bubble = pending?.dataset.katPendingTurnId === reveal.id ? pending :
      [...document.querySelectorAll<HTMLElement>('.turn-card')]
        .find(turn => turn.dataset.katTurnId === reveal.id)?.querySelector('.user-bubble');
    if (!bubble) return;
    const dockTop = document.querySelector('.composer-wrap')?.getBoundingClientRect().top ?? window.innerHeight;
    const hiddenBy = bubble.getBoundingClientRect().bottom - Math.min(dockTop, window.innerHeight) + 12;
    if (hiddenBy > 0) window.scrollBy(0, hiddenBy);
    reveal.scrollY = window.scrollY;
  }, [pendingTurnId, conversation?.id]);

  useEffect(() => {
    if (workspace) {
      void refreshPeople().catch(() => setNotice('People could not be loaded. Retry after checking your workspace.'));
      void loadThreads(0, '').catch(() => setListStatus('Conversations unavailable.'));
    }
  }, [workspace?.owner, filterPersonId]);

  useEffect(() => {
    if (drawer) closeButton.current?.focus();
    else if (wasDrawerOpen.current) menuButton.current?.focus();
    wasDrawerOpen.current = drawer;
  }, [drawer]);

  useEffect(() => {
    const target = focusProfile.current;
    if (!target || target.id !== person?.id || target.navigation !== navigationVersion.current ||
        drawer || chartHub || skyOpen || settingsOpen) return;
    focusProfile.current = null;
    document.getElementById('person-heading')?.focus();
  }, [person?.id, drawer, chartHub, skyOpen, settingsOpen]);

  function closeDrawer() { setDrawer(false); }

  function openSettings() {
    settingsOpener.current = document.activeElement as HTMLElement;
    setSettingsOpen(true); closeDrawer();
  }

  function closeSettings() {
    setSettingsOpen(false);
    requestAnimationFrame(() => {
      const target = settingsOpener.current;
      if (target?.getClientRects().length && getComputedStyle(target).visibility !== 'hidden') target.focus();
      else if (window.matchMedia('(max-width:700px)').matches) menuButton.current?.focus();
      else settingsButton.current?.focus();
    });
  }

  function drawerKeys(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape') closeDrawer();
    if (event.key !== 'Tab' || !drawer) return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not([disabled])')];
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  async function signIn(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setNotice('');
      const user = await api<Workspace>('login', undefined, 'POST', { username, password });
      setWorkspace(user); setPassword('');
    } catch { setNotice('Sign-in failed. Check the local username and password.'); }
  }

  async function signOut() {
    if (!workspace) return;
    try {
      await api('logout', workspace.csrf, 'POST');
      navigationVersion.current++; listRequestVersion.current++; peopleRequestVersion.current++;
      returnToAdvanced.current = null; advancedDraft.current = null;
      returnToPlanetary.current = null; planetaryDraft.current = null;
      archive.reset(); invalidateSubmission(); setSettingsOpen(false); setWorkspace(null); setPeople([]); setPerson(null); setConversation(null); setSkyOpen(false); setChartHub(null);
      setSelection([]);
      setMessage(''); setDiscuss(null); setEditing(null); closeDrawer();
    } catch { setNotice('Sign-out did not complete. Try again.'); }
  }

  function invalidateSubmission() {
    submissionVersion.current++;
    submissionInFlight.current = false;
    setPreparingSend(false);
  }

  function allConversations() {
    navigationVersion.current++; archive.reset(); invalidateSubmission();
    setSettingsOpen(false); setSkyOpen(false); setSkyFromHub(false); setChartHub(null);
    setProfileFromHub(false); setProfileChartFocus(false); setProfileChildFocus(false);
    setPerson(null); setConversation(null); setDiscuss(null); setFilterPersonId(null);
    pendingConversationId.current = '';
    setSearched(''); setSearchQuery('');
    if (!filterPersonId) void loadThreads(0, '');
    // The requested history is in this drawer on mobile: do not close it out of reach.
    if (!window.matchMedia('(max-width:700px)').matches) closeDrawer();
    requestAnimationFrame(() => historyHeading.current?.focus());
  }

  function newChat(personIds?: string | string[]) {
    setSettingsOpen(false); setSkyOpen(false); setChartHub(null); setProfileChartFocus(false); navigationVersion.current++; archive.reset(); invalidateSubmission(); setPerson(null); setConversation(null);
    setSelection((personIds ? (Array.isArray(personIds) ? personIds : [personIds]) : []).map(person_id => ({ person_id })));
    setMessage(''); setDiscuss(null); setEditing(null); pendingConversationId.current = '';
    closeDrawer();
  }

  async function openConversation(id: string) {
    setSettingsOpen(false); setSkyOpen(false); setChartHub(null);
    const version = ++navigationVersion.current;
    try {
      setNotice('');
      const thread = await api<Conversation>(`conversations/${id}`);
      if (version !== navigationVersion.current) return;
      await archive.open(id);
      if (version !== navigationVersion.current) return;
      invalidateSubmission();
      let selected: Selection[] = thread.people.map(item => ({ person_id: item.person_id || item.id! }));
      if (thread.active_head) {
        const active = await api<Turn>(`conversations/${id}/turns/${thread.active_head}`);
        selected = active.selected_people.map(item => ({ person_id: item.person_id }));
      }
      if (version !== navigationVersion.current) return;
      setConversation(thread); setSelection(selected); setDiscuss(null);
      setEditing(null);
      setPerson(null); closeDrawer();
    } catch { if (version === navigationVersion.current) setNotice('Conversation could not be opened. Your current draft remains here.'); }
  }

  function openChartHub() {
    returnToAdvanced.current = null; advancedDraft.current = null;
    returnToPlanetary.current = null; planetaryDraft.current = null;
    navigationVersion.current++;
    hubPreviousPerson.current = person;
    hubPreviousFilter.current = filterPersonId;
    setSettingsOpen(false); setSkyOpen(false); setChartHub('hub'); closeDrawer();
  }

  function closeChartHub() {
    setChartHub(null);
    window.requestAnimationFrame(() => {
      if (window.matchMedia('(max-width:700px)').matches) menuButton.current?.focus();
      else chartNavButton.current?.focus();
    });
  }

  function openContextChart(personRecord: Person) {
    navigationVersion.current++;
    hubPreviousPerson.current = null; hubPreviousFilter.current = filterPersonId;
    setProfileFromHub(true); setProfileChartFocus(true); setProfileChildFocus(false);
    setProfileEditorPersonId(null); setPerson(personRecord); setFilterPersonId(personRecord.id);
    setSkyOpen(false); setChartHub(null); closeDrawer();
  }

  function openHubPerson(id: string, child = false) {
    const version = ++navigationVersion.current;
    peopleRequestVersion.current++; setSettingsOpen(false);
    void api<Person>(`people/${id}`).then(selected => {
      if (version !== navigationVersion.current) return;
      setPerson(selected); setProfileEditorPersonId(id);
      setProfileEditorRequest(current => current + 1);
      setProfileChildFocus(child); setProfileFromHub(true); setProfileChartFocus(false);
      setFilterPersonId(id); setChartHub(null); closeDrawer();
    }).catch(() => { if (version === navigationVersion.current) {
      returnToAdvanced.current = null; returnToPlanetary.current = null;
      setNotice('That person could not be opened. Choose another person.');
    } });
  }

  function discussSavedResult(personId: string, selected: SelectedResult, label: string) {
    if (archive.hasPending) {
      setNotice('Finish or retry the current message before choosing another result.'); return;
    }
    navigationVersion.current++; archive.reset(); invalidateSubmission();
    setSettingsOpen(false); setChartHub(null); setSkyOpen(false);
    setPerson(null); setConversation(null); setSelection([{ person_id: personId }]);
    setDiscuss({ selected, label }); setEditing(null); pendingConversationId.current = '';
    closeDrawer();
    requestAnimationFrame(() => messageInput.current?.focus());
  }

  async function startConversation(selected: Selection[]): Promise<Conversation | null> {
    if (!workspace) return null;
    const version = ++navigationVersion.current;
    if (!pendingConversationId.current) pendingConversationId.current = 'thread-' + crypto.randomUUID();
    try {
      const result = await api<Conversation>('conversations', workspace.csrf, 'POST', {
        id: pendingConversationId.current, title: 'New conversation',
        people: selected.map(item => item.person_id),
      });
      if (version !== navigationVersion.current) return null;
      setConversation(result); setPerson(null); setNotice('');
      pendingConversationId.current = '';
      void loadThreads(0, ''); // A sidebar failure cannot make the turn send ambiguous.
      return result;
    } catch {
      if (version === navigationVersion.current)
        archive.failPending('This conversation was not confirmed. Retry this message; your other draft is unchanged.');
      return null;
    }
  }

  async function sendText(submittedMessage: string, revision?: Edit & { selected: Selection[] },
    clearComposer = true): Promise<boolean> {
    if (archive.hasPending || submissionInFlight.current || !submittedMessage.trim() || archive.busy || headNotLoaded) return false;
    submissionInFlight.current = true; setPreparingSend(true);
    const submission = ++submissionVersion.current;
    if (!conversation && !pendingConversationId.current)
      pendingConversationId.current = 'thread-' + crypto.randomUUID();
    const selected = (revision?.selected || selection).map(item => ({ ...item }));
    const queued = archive.queue(conversation?.id || pendingConversationId.current, submittedMessage,
      selected, revision?.parent || editing?.parent || '@active',
      revision?.kind || editing?.kind || 'normal', revision?.replaces || editing?.replaces || null,
      revision || editing ? undefined : discuss?.selected);
    if (!queued) { submissionInFlight.current = false; setPreparingSend(false); return false; }
    setDiscuss(null); // The immutable pending payload retains the selection on retry.
    if (clearComposer) {
      setMessage(current => current === submittedMessage ? '' : current);
      setEditing(null);
      messageInput.current?.focus();
    }
    try {
      if (!provider.status.connected) {
        archive.failPending('ChatGPT is not connected yet. Connect your plan, then retry this message.', true);
      } else {
        const thread = conversation || await startConversation(selected);
        if (thread) {
          await archive.retry();
          void loadThreads(0, ''); // Sidebar refresh never gates this message.
        }
      }
      return true; // Accepted into the visible local projection, not claimed saved.
    } finally {
      if (submission === submissionVersion.current) {
        submissionInFlight.current = false; setPreparingSend(false);
      }
    }
  }

  async function retryPending() {
    const item = archive.localPending;
    if (!item || submissionInFlight.current || archive.busy) return;
    if (item.failure?.reconnect && !provider.status.connected) {
      archive.failPending('ChatGPT is not connected yet. Connect your plan, then retry this message.', true);
      return;
    }
    submissionInFlight.current = true; setPreparingSend(true);
    const submission = ++submissionVersion.current;
    try {
      if (!conversation && pendingConversationId.current !== item.conversationId) return;
      const thread = conversation || await startConversation(item.payload.selected_people);
      if (thread?.id === item.conversationId) {
        await archive.retry();
        void loadThreads(0, '');
      }
    } finally {
      if (submission === submissionVersion.current) {
        submissionInFlight.current = false; setPreparingSend(false);
      }
    }
  }

  async function sendMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await sendText(message);
  }

  async function changeBranch(head: string) {
    if (!workspace || !conversation || archive.busy) return;
    try {
      await api(`conversations/${conversation.id}/branch`, workspace.csrf, 'POST', { head });
      await openConversation(conversation.id);
    } catch { setNotice('Branch selection was not saved. The original branch is unchanged.'); }
  }

  async function correctTurn(turn: Turn, action: 'correct' | 'withdraw', replacement: string | null) {
    if (!workspace || !conversation || archive.busy) return;
    try {
      await api(`conversations/${conversation.id}/corrections`, workspace.csrf, 'POST', {
        id: 'correction-' + crypto.randomUUID(), source_turn: turn.id, action, replacement
      });
      await openConversation(conversation.id);
    } catch { setNotice('Correction was not confirmed. Check the original turn before retrying.'); }
  }

  function editTurn(turn: Turn) {
    if (archive.busy) return;
    if (headNotLoaded) { setNotice('Load the current saved message before editing this conversation.'); return; }
    setMessage(String(turn.events.find(item => item.kind === 'user')?.payload.content || ''));
    setSelection(turn.selected_people.map(item => ({ person_id: item.person_id })));
    setEditing({ parent: turn.parent_id || '@root', replaces: turn.id, kind: 'edit' });
    document.getElementById('message')?.focus();
  }

  function retryFailedTurn(turn: Turn) {
    if (!conversation || archive.busy || archive.hasPending || submissionInFlight.current) return;
    if (turn.selected_people.some(item => item.attachment_id)) {
      setNotice('Reselect the file and give fresh consent before trying again.'); return;
    }
    const text = String(turn.events.find(item => item.kind === 'user')?.payload.content || '');
    if (!text) { setNotice('Load the saved input first, then try again.'); return; }
    void sendText(text, undefined, false); // A new paid turn, never a resend of the archived failure.
  }

  async function regenerateTurn(turn: Turn) {
    if (!conversation || archive.busy || headNotLoaded) return;
    const text = String(turn.events.find(item => item.kind === 'user')?.payload.content || '');
    if (!text) { setNotice('Load the original input event first.'); return; }
    await archive.submit(conversation.id, text,
      turn.selected_people.map(item => ({ person_id: item.person_id })),
      turn.parent_id || '@root', 'regenerate', turn.id);
  }

  async function renameConversation() {
    if (!workspace || !conversation || archive.busy) return;
    const title = window.prompt('Conversation title', conversation.title);
    if (title === null) return;
    try {
      const updated = await api<Conversation>(`conversations/${conversation.id}`, workspace.csrf,
        'PATCH', { title });
      setConversation(updated); await loadThreads(0);
    } catch { setNotice('Title was not saved. Use 1–80 characters and retry.'); }
  }

  async function deleteConversation() {
    if (!workspace || !conversation || archive.busy) return;
    if (!window.confirm('Delete this archived conversation and its owned files? Dependent conversations must be removed first. Existing exports cannot be recalled.')) return;
    try {
      await api(`conversations/${conversation.id}`, workspace.csrf, 'DELETE');
      archive.reset(); setConversation(null); setMessage(''); setEditing(null);
      await loadThreads(0);
    } catch { setNotice('Deletion was blocked or unavailable. Dependent conversations and original records remain.'); }
  }

  async function exportConversation() {
    if (!workspace || !conversation) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(conversation.id)}/export`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-Kat-CSRF': workspace.csrf }
      });
      if (!response.ok) throw new Error('Export failed');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = 'kat-conversation.jsonl';
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { setNotice('Export was not available; the original archive remains in the local workspace.'); }
  }

  const latestTurnActions: TurnActions = {
    onBranch: head => void changeBranch(head),
    onEdit: editTurn,
    onRegenerate: turn => void regenerateTurn(turn),
    onRetryFailed: retryFailedTurn,
    onCorrect: (turn, action, replacement) => void correctTurn(turn, action, replacement),
    onRetryEvents: turn => {
      if (conversation) archive.retryEvents(conversation.id, turn);
    },
  };
  const turnActions = useRef(latestTurnActions);
  turnActions.current = latestTurnActions;

  if (loading) return <main className="login-screen" aria-busy="true"><p>Opening your local workspace…</p></main>;
  if (!workspace) return <main className="login-screen"><section className="login-card">
    <span className="eyebrow">THE READING ROOM · LOCAL</span>
    <h1>Welcome to Kat.</h1><p>Sign in to your local workspace. Your ChatGPT connection is separate.</p>
    <form onSubmit={signIn}>
      <label htmlFor="username">Username</label>
      <input id="username" autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} />
      <label htmlFor="password">Password</label>
      <input id="password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
      {notice && <p className="error" role="alert">{notice}</p>}
      <button className="primary" type="submit">Open workspace</button>
    </form>
    <SourceNotice />
  </section></main>;

  return <div className="app">
    {drawer && <button className="drawer-scrim" aria-label="Close navigation" onClick={closeDrawer} />}
    <aside className={`sidebar${drawer ? ' open' : ''}`} aria-label="Workspace navigation" onKeyDown={drawerKeys}>
      <div className="brand-row"><button className="brand" type="button" aria-label="kat. — New conversation" onClick={() => newChat()}>kat.</button><button className="side-close" ref={closeButton} aria-label="Close navigation" onClick={closeDrawer}>×</button></div>
      <div className="side-main-actions"><button className="new-chat" type="button" onClick={() => newChat()}>＋ &nbsp; New conversation</button>
        <button ref={chartNavButton} className="create-chart-nav" type="button" onClick={openChartHub}>＋ &nbsp; Create chart</button></div>
      <nav aria-label="People"><div className="side-heading-row"><h2 className="side-heading">PEOPLE</h2><button aria-label="Add person" onClick={() => {
        personDialogOpener.current = document.activeElement as HTMLElement;
        setSettingsOpen(false); closeDrawer(); setPersonDialog(true);
      }}>＋</button></div>
        {people.length ? <div className="person-list">{people.map(item => <button key={item.id} className={`person-link${filterPersonId === item.id ? ' selected' : ''}`} onClick={() => {
          setSettingsOpen(false); setSkyOpen(false); setSkyFromHub(false); setChartHub(null);
          const version = ++navigationVersion.current;
          peopleRequestVersion.current++; setProfileEditorPersonId(null); setProfileFromHub(false);
          setProfileChartFocus(false); setProfileChildFocus(false);
          focusProfile.current = { id: item.id, navigation: version };
          archive.reset(); void api<Person>(`people/${item.id}`).then(selected => {
            if (version === navigationVersion.current) setPerson(selected);
          }).catch(() => { if (version === navigationVersion.current) setNotice('Person could not be opened.'); });
          setFilterPersonId(item.id); setSearched(''); setSearchQuery(''); setConversation(null);
          closeDrawer();
        }}><span className="initial">{item.name.charAt(0).toUpperCase()}</span><span>{item.name}</span></button>)}</div> : <p className="side-empty">No people yet.</p>}</nav>
      <nav aria-label="Recent conversations"><h2 className="side-heading" ref={historyHeading} tabIndex={-1}>RECENT CONVERSATIONS</h2>
        <button type="button" className="all-conversations-nav" onClick={allConversations}>All conversations</button>
        {filterPersonId && <p className="side-filter">For {people.find(p => p.id === filterPersonId)?.name || 'selected person'} <button onClick={() => { setFilterPersonId(null); setSearched(''); setSearchQuery(''); }}>Show all</button></p>}
        <form className="search-conversations" onSubmit={e => { e.preventDefault(); setSearched(searchQuery); void loadThreads(0, searchQuery); }}><label className="sr-only" htmlFor="thread-search">Search conversations</label><input id="thread-search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search conversations" /><button type="submit">Search</button></form>
        {listStatus && <p className="side-filter" role="status">{listStatus}</p>}
        <div className="recent">{conversations.length ? <ConversationBrowseList conversations={conversations}
          selectedId={conversation?.id} zone={workspace.product.reporting_zone} onOpen={id => void openConversation(id)} /> :
          listStatus !== 'Loading conversations…' && !listStatus.startsWith('Conversations unavailable') &&
            <p className="side-empty">{searched ? 'No matches in current indexed conversations.' :
              filterPersonId ? 'No conversations for this person.' : 'No conversations yet.'}</p>}
          {nextConversationOffset !== null && <button onClick={() => void loadThreads(nextConversationOffset)}>Load older conversations</button>}</div>
      </nav>
      <div className="side-bottom"><button ref={settingsButton} type="button" onClick={openSettings}>Settings</button>
        <div className="account"><span className="initial">{workspace.owner.charAt(0).toUpperCase()}</span><span>{workspace.owner}<small>{workspace.workspace === 'personal' ? 'Personal workspace' : 'Local workspace'}</small></span></div><button type="button" onClick={signOut}>Sign out</button></div>
    </aside>
    <main className={`main${settingsOpen ? ' settings-main' : !person && !skyOpen && !chartHub ? ' chat-scroll-page' : ''}`} inert={drawer}>
      <header className="header"><div className="header-left"><button ref={menuButton} className="mobile-menu" aria-label="Open navigation" aria-expanded={drawer} onClick={() => setDrawer(true)}>☰</button><span className="header-title">{settingsOpen ? 'Settings' : chartHub ? 'Create chart' : skyOpen ? 'Sky at a date' : person ? person.name : conversation?.title || 'New conversation'}</span></div><span className="model-label">{provider.error.startsWith('Connection status could not') ? 'ChatGPT connection unavailable' :
          provider.status.registration === 'offline' ?
            provider.status.connected ? 'ChatGPT account saved' : 'Chat not connected' :
            provider.status.connected ? 'ChatGPT connected' : 'Connect ChatGPT plan to send'}</span></header>
      {settingsOpen && <SettingsView workspace={workspace} provider={provider} onClose={closeSettings} />}
      <div className={settingsOpen ? 'settings-hidden' : 'settings-visible'} inert={settingsOpen}>
      {chartHub === 'synastry' && <SynastryView workspace={workspace} people={people}
        discussionDisabled={archive.hasPending || archive.busy}
        onClose={() => setChartHub('hub')} onCreate={id => openHubPerson(id)}
        onDiscuss={ids => {
          if (archive.hasPending || archive.busy) return;
          if (message.trim() && !window.confirm('Start a new discussion? Your current unsent draft will be cleared.')) return;
          newChat(ids);
        }} />}
      {(chartHub === 'solar_return' || chartHub === 'lunar_return') &&
        <AdvancedView key={chartHub} workspace={workspace} people={people} technique={chartHub}
          initialDraft={advancedDraft.current || undefined}
          onDiscuss={discussSavedResult}
          onClose={() => { advancedDraft.current = null; setChartHub('hub'); }}
          onCreateNatal={(id, draft) => {
            returnToAdvanced.current = { choice: chartHub, draft }; openHubPerson(id);
          }} />}
      {chartHub === 'mc_transit' && <McTransitsView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'secondary_progression' && <ProgressionsView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'relationship_derived' && <RelationshipDerivedView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'true_solar_arc' && <SolarArcView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'progressed_lunar_phases' && <ProgressedPhasesView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'actual_lunations_eclipses' && <LunationsView workspace={workspace} people={people}
        onClose={() => setChartHub('hub')} />}
      {chartHub === 'planetary_return' && <PlanetaryReturnsView workspace={workspace} people={people}
        initialDraft={planetaryDraft.current || undefined}
        onClose={() => { planetaryDraft.current = null; setChartHub('hub'); }}
        onCreateNatal={(id, draft) => { returnToPlanetary.current = draft; openHubPerson(id); }} />}
      {chartHub && chartHub !== 'synastry' && chartHub !== 'solar_return' &&
        chartHub !== 'lunar_return' && chartHub !== 'mc_transit' &&
        chartHub !== 'secondary_progression' && chartHub !== 'relationship_derived' &&
        chartHub !== 'true_solar_arc' && chartHub !== 'progressed_lunar_phases' &&
        chartHub !== 'actual_lunations_eclipses' && chartHub !== 'planetary_return' && <ChartHub choice={chartHub} people={people}
        onSelect={choice => {
          if (choice === 'transits') { setChartHub(null); setSkyFromHub(true); setSkyOpen(true); }
          else setChartHub(choice);
        }}
        onPerson={id => openHubPerson(id, chartHub === 'child')}
        onAddPerson={() => {
          personDialogOpener.current = document.activeElement as HTMLElement;
          setPersonDialog(true);
        }}
        onClose={() => chartHub === 'hub' ? closeChartHub() : setChartHub('hub')} />}
      {skyOpen && <TransitView workspace={workspace} people={people}
        initialPersonId={person?.id || selection[0]?.person_id}
        returnLabel={skyFromHub ? 'Back to chart choices' : 'Return to conversation'}
        onClose={() => { setSkyOpen(false); if (skyFromHub) setChartHub('hub'); setSkyFromHub(false); }} />}
      <div className={`reader-content${skyOpen || chartHub ? ' sky-hidden' : ''}`} inert={skyOpen || !!chartHub}>
      {person ? <PersonDetail key={person.id} workspace={workspace} person={person} refresh={refreshPeople}
        discussSavedResult={(selected, label) => discussSavedResult(person.id, selected, label)}
        initialEditorOpen={profileEditorPersonId === person.id} initialTab={profileChartFocus && profileFromHub ? 'charts' : 'basic'} editorRequest={profileEditorRequest}
        childFocus={profileChildFocus && profileFromHub} returnLabel={conversation ? 'conversation' : 'workspace'}
        onReturn={profileFromHub ? () => {
          navigationVersion.current++; setPerson(conversation ? null : hubPreviousPerson.current); setFilterPersonId(hubPreviousFilter.current);
          setProfileFromHub(false); setProfileChildFocus(false); setProfileChartFocus(false);
          if (returnToAdvanced.current) {
            const next = returnToAdvanced.current; returnToAdvanced.current = null;
            advancedDraft.current = next.draft; setChartHub(next.choice);
          } else if (returnToPlanetary.current) {
            planetaryDraft.current = returnToPlanetary.current; returnToPlanetary.current = null;
            setChartHub('planetary_return');
          }
        } : undefined}
        startConversation={() => newChat(person.id)} openConversation={id => void openConversation(id)} onDeleted={() => {
        navigationVersion.current++; peopleRequestVersion.current++;
        archive.reset(); setPeople(old => old.filter(item => item.id !== person.id));
        setPerson(null); setFilterPersonId(null); setSearchQuery(''); setSearched('');
      }} /> : <section className={conversation ? 'conversation' : 'home'}
        data-kat-conversation-id={conversation?.id || ''}
        aria-label={conversation ? 'Conversation' : 'New conversation'}>
        <div className={`chat-reading-grid${selection.length ? ' has-chart-context' : ''}`}>
        {conversation ? <div className="messages"><div className="conversation-toolbar"><span>{conversation.people.map(item => item.name).join(' & ') || 'General'} · one archived thread</span>
          <details className="conversation-menu"><summary>Conversation options</summary><div className="conversation-controls">
            <button onClick={() => void renameConversation()} disabled={archive.busy}>Rename</button>
            <button onClick={() => void exportConversation()}>Export original JSONL</button>
            <button onClick={() => void deleteConversation()} disabled={archive.busy}>Delete conversation</button></div></details></div>
          {archive.turns.length ? archive.turns.map(turn => <TurnCard key={turn.id} turn={turn} people={people} workspace={workspace}
            conversationId={conversation.id} activeHead={conversation.active_head} actions={turnActions}
            eventFailure={archive.eventFailures[turn.id]} />) : !archive.localPending && <p className="conversation-empty">This conversation has no messages yet. Its selected people are ready.</p>}
          {archive.localPending?.conversationId === conversation.id && <LocalPendingMessage pending={archive.localPending}
            onRetry={() => void retryPending()} onReconnect={openSettings} disabled={archive.busy || preparingSend} />}
          {headNotLoaded && <p className="conversation-empty" role="status">The current saved message is on another page. Load more saved messages before editing or sending.</p>}
          {archive.nextOffset !== null && <button className="quiet-action" onClick={() => { if (archive.nextOffset !== null) void archive.open(conversation.id, archive.nextOffset); }}>Load more saved messages</button>}
        </div> : archive.localPending?.conversationId === pendingConversationId.current ?
          <div className="messages pending-messages"><LocalPendingMessage pending={archive.localPending}
            onRetry={() => void retryPending()} onReconnect={openSettings} disabled={archive.busy || preparingSend} /></div> :
          <div className="welcome"><div className="eyebrow">THE READING ROOM</div><h1>What’s on your mind?</h1><p>A chart, a question, or a thought to follow.</p></div>}
        <ContextChart selection={selection} people={people} turns={archive.turns} activeHead={conversation?.active_head || null} onOpenChart={openContextChart} />
        </div>
        <div className="composer-wrap" ref={chatComposer.dock}>{discuss && <p className="compose-context" role="status">
          Discuss {discuss.label} · saved result, not recalculated. Your draft is unchanged.
          <button type="button" onClick={() => setDiscuss(null)}>Remove result</button></p>}
          <form className="composer" onSubmit={sendMessage}>
          <ScopeChips selection={selection} people={people}
            remove={id => setSelection(selection.filter(item => item.person_id !== id))}
            open={() => setScopePicker(true)} />
          {editing && <p className="edit-note">Editing an earlier message. The original remains saved. <button type="button" onClick={() => { setEditing(null); setMessage(''); }}>Cancel edit</button></p>}
          <label className="sr-only" htmlFor="message">Message Kat</label><textarea ref={setMessageInput} id="message" rows={2} placeholder="Ask anything, or pick up a thread…" value={message}
            onChange={event => setMessage(event.target.value)}
            onKeyDown={event => {
              if (event.key !== 'Enter' || event.repeat || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey ||
                  event.nativeEvent.isComposing || event.keyCode === 229) return;
              event.preventDefault();
              if (message.trim() && !preparingSend && !archive.busy && !archive.hasPending && !headNotLoaded)
                void sendText(message);
            }} />
          <div className="compose-actions"><span>{archive.busy ? 'Reply in progress · keep drafting until it finishes' :
            'Enter to send · Shift+Enter for a new line'}</span>
            <button className="send" aria-label="Send message" type="submit" disabled={!message.trim() || preparingSend || archive.busy || archive.hasPending || headNotLoaded}>↑</button></div>
        </form>{!provider.status.connected && <button type="button" className="quiet-action" onClick={openSettings}>Connect ChatGPT plan to send</button>}
        {provider.error && <p className="error" role="alert">{provider.error}</p>}
        {archive.busy && archive.turns.some(turn => turn.status === 'open') && conversation && <button className="quiet-action" onClick={() => {
          const turn = archive.turns.find(item => item.status === 'open');
          if (turn) void api(`conversations/${conversation.id}/turns/${turn.id}/cancel`, workspace.csrf, 'POST')
            .catch(() => setNotice('Cancellation could not be confirmed. Check the archived status.'));
        }}>Stop response</button>}
        {archive.sendError && <p className="error" role="alert">{archive.sendError}</p>}
        {notice && <p className="error" role="alert">{notice}</p>}</div>
      </section>}
      </div>
      </div>
    </main>
    <CreatePersonDialog open={personDialog} workspace={workspace} onClose={created => {
      setPersonDialog(false);
      void refreshPeople().catch(() => setNotice('People could not be refreshed.'));
      if (!created) requestAnimationFrame(() => {
        const opener = personDialogOpener.current;
        if (opener?.closest('.sidebar') && window.matchMedia('(max-width:700px)').matches)
          menuButton.current?.focus();
        else if (opener?.getClientRects().length && !opener.closest('[inert]')) opener.focus();
        else menuButton.current?.focus();
      });
    }} onCreated={created => {
      setSettingsOpen(false);
      if (chartHub === 'natal' || chartHub === 'child') {
        setProfileFromHub(true); setProfileChildFocus(chartHub === 'child'); setChartHub(null);
      }
      setProfileEditorPersonId(created.id); setProfileEditorRequest(current => current + 1);
      setPerson(created); void refreshPeople();
    }} />
    <ScopePicker open={scopePicker} people={people} selected={selection} onClose={() => setScopePicker(false)}
      onApply={setSelection} />
  </div>;
}

createRoot(document.getElementById('root')!).render(<App />);
