import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from '../shared/api';
import { NestedNavigation } from '../shared/nested-navigation';
import { useConversationWorkflow } from '../features/conversation/conversation-workflow';
import { LocalPendingMessage } from '../features/conversation/local-pending';
import { ConversationBrowseList, ScopeChips, ScopePicker } from '../features/conversation/conversation';
import { ContextChart } from '../features/conversation/context-chart';
import { ConversationMenu } from '../features/conversation/conversation-menu';
import { TurnCard } from '../features/conversation/turns';
import { CreatePersonDialog, PersonDetail, type Person, type PersonMemory } from '../features/people/people';
import { useProvider } from '../features/settings/provider';
import { SettingsView } from '../features/settings/settings';
import { BrandKitten, ReadingKitten } from '../shared/kitten';
import { TransitView } from '../features/charts/transit-view';
import { ChartHub } from '../features/charts/chart-hub';
import { AdvancedView } from '../features/charts/advanced-view';
import { McTransitsView } from '../features/charts/mc-transits-view';
import { ProgressionsView } from '../features/charts/progressions-view';
import { RelationshipDerivedView } from '../features/charts/relationship-derived-view';
import { SolarArcView } from '../features/charts/solar-arc-view';
import { ProgressedPhasesView } from '../features/charts/progressed-phases-view';
import { LunationsView } from '../features/charts/lunations-view';
import { PlanetaryReturnsView } from '../features/charts/planetary-returns-view';
import { useGrowingComposer } from '../features/conversation/chat-scroll';
import { SynastryView } from '../features/charts/synastry-view';
import { useWorkspaceNavigation } from './workspace-navigation';
import { useConversationDiscovery } from '../features/conversation/conversation-discovery';

export function WorkspaceShell({ workspace, onSignedOut }: { workspace: Workspace; onSignedOut: () => void }) {
  const [notice, setNotice] = useState('');
  const [people, setPeople] = useState<Person[]>([]);
  async function validateSession() {
    const session = await api<Workspace>('session');
    if (session.owner !== workspace.owner || session.csrf !== workspace.csrf) throw new ApiError(401, 'session_changed');
  }
  const navigation = useWorkspaceNavigation({ resetArchive: () => workflow.archive.reset(),
    invalidateSubmission: () => workflow.invalidateSubmission(),
    restoreConversation: (thread, version): Promise<void> => workflow.restoreConversation(thread, version), validateSession,
    unavailable: error => {
      if (error instanceof ApiError && error.status === 401) onSignedOut();
      else setNotice('That saved view is no longer available. Your unsent draft remains here.');
    } });
  const { drawer, person, skyOpen, skyFromHub, chartHub, profileChildFocus, profileFromHub,
    profileChartFocus, profileEditorRequest, profileEditorPersonId, settingsOpen,
    filterPersonId, conversation } = navigation;
  const navigationVersion = navigation.version;
  const personDialog = navigation.nested['create-person'] === 'open';
  const scopePicker = navigation.nested['scope-picker'] === 'open';
  const setPersonDialog = (open: boolean) => navigation.nestedNavigation.change('create-person', open ? 'open' : null);
  const setScopePicker = (open: boolean) => navigation.nestedNavigation.change('scope-picker', open ? 'open' : null);
  const discovery = useConversationDiscovery(workspace, navigation);
  const { conversations, searchQuery, setSearchQuery, searched, nextConversationOffset,
    listStatus } = discovery;
  const peopleRequestVersion = useRef(0);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const provider = useProvider(workspace);
  const workflow = useConversationWorkflow({ workspace, navigation, discovery,
    connected: provider.status.connected, setNotice, messageInput });
  const { archive, selection, setSelection, message, setMessage, discuss, setDiscuss, editing,
    pendingConversationId, preparingSend, headNotLoaded, turnActions, newChat, openConversation,
    discussSavedResult, sendText, retryPending, renameConversation, deleteConversation,
    exportConversation } = workflow;
  const workflowRef = useRef(workflow); workflowRef.current = workflow;
  useEffect(() => {
    let live = true, checking = false;
    async function resume() {
      if (document.visibilityState !== 'visible' || checking) return;
      checking = true;
      try {
        await validateSession();
        if (!live) return;
        await workflowRef.current.resumeConversation();
      } catch (error) {
        if (!live) return;
        if (error instanceof ApiError && error.status === 401) onSignedOut();
        else setNotice('Your workspace could not be checked after returning. Your draft is still here; no message was resent.');
      } finally { checking = false; }
    }
    const visibility = () => { void resume(); };
    const pageShow = (event: PageTransitionEvent) => { if (event.persisted) void resume(); };
    document.addEventListener('visibilitychange', visibility); window.addEventListener('pageshow', pageShow);
    return () => { live = false; document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pageshow', pageShow); };
  }, [workspace.owner, workspace.csrf]);
  const chatComposer = useGrowingComposer(message);
  const menuButton = useRef<HTMLButtonElement>(null);
  const chartNavButton = useRef<HTMLButtonElement>(null);
  const chartOpener = useRef<HTMLElement | null>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const settingsOpener = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const historyHeading = useRef<HTMLHeadingElement>(null);
  const focusProfile = navigation.focusProfile;
  const personMemories = useRef(new Map<string, PersonMemory>());
  function personMemory(id: string) {
    if (!personMemories.current.has(id)) personMemories.current.set(id, { context: {}, profile: {} });
    return personMemories.current.get(id)!;
  }
  const personDialogOpener = useRef<HTMLElement | null>(null);
  const wasDrawerOpen = useRef(false);
  const setMessageInput = useCallback((element: HTMLTextAreaElement | null) => {
    chatComposer.input(element);
    messageInput.current = element;
  }, [chatComposer.input]);

  const refreshPeople = useCallback(async () => {
    const version = ++peopleRequestVersion.current;
    const result = await api<{ people: Person[] }>('people');
    if (version !== peopleRequestVersion.current) return;
    setPeople(result.people);
    if (person) {
      const updated = await api<Person>(`people/${person.id}`);
      if (version === peopleRequestVersion.current)
        navigation.updatePerson(current => current?.id === person.id ? updated : current);
    }
  }, [person?.id]);

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

  function closeDrawer() { navigation.closeDrawer(); }

  function openSettings() {
    settingsOpener.current = document.activeElement as HTMLElement;
    navigation.openSettings();
  }

  function closeSettings() {
    const leavingFocus = document.activeElement;
    navigation.closeSettings();
    requestAnimationFrame(() => {
      // The reader may already be typing before this deferred restoration runs.
      if (document.activeElement !== document.body && document.activeElement !== leavingFocus) return;
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

  async function signOut() {
    if (!workspace) return;
    try {
      await api('logout', workspace.csrf, 'POST');
      discovery.reset(); peopleRequestVersion.current++;
      navigation.signOut(); workflow.resetDraft(); onSignedOut();
    } catch { setNotice('Sign-out did not complete. Try again.'); }
  }

  function allConversations() {
    workflow.allConversations();
    // The requested history is in this drawer on mobile: do not close it out of reach.
    if (!window.matchMedia('(max-width:700px)').matches) closeDrawer();
    requestAnimationFrame(() => historyHeading.current?.focus());
  }

  function openChartHub(originId: string | null = null) {
    chartOpener.current = document.activeElement as HTMLElement;
    navigation.openChartHub(originId);
  }

  function closeChartHub() {
    navigation.closeChartHub();
    window.requestAnimationFrame(() => {
      if (chartOpener.current?.getClientRects().length && getComputedStyle(chartOpener.current).visibility !== 'hidden') chartOpener.current.focus();
      else if (window.matchMedia('(max-width:700px)').matches) menuButton.current?.focus();
      else chartNavButton.current?.focus();
    });
  }

  async function inspectContext(id: string) {
    const version = navigation.beginHubPerson();
    try {
      const selected = await api<Person>(`people/${encodeURIComponent(id)}`);
      if (navigation.isCurrent(version)) navigation.openConversationPerson(selected, 'context');
    } catch { if (navigation.isCurrent(version)) setNotice('Context could not be opened. Your conversation is unchanged.'); }
  }

  function openContextChart(personRecord: Person) {
    navigation.openConversationPerson(personRecord, 'charts');
  }

  function openHubPerson(id: string, child = false) {
    const version = navigation.beginHubPerson();
    peopleRequestVersion.current++;
    void api<Person>(`people/${id}`).then(selected => {
      if (navigation.isCurrent(version)) navigation.showHubPerson(selected, child);
    }).catch(() => { if (navigation.isCurrent(version)) {
      navigation.abandonReturn();
      setNotice('That person could not be opened. Choose another person.');
    } });
  }

  const chartOrigin = people.find(item => item.id === navigation.chartOriginId);
  const needsNatal = chartOrigin && !chartOrigin.active_chart_id && chartHub &&
    !['hub', 'natal', 'child'].includes(chartHub);

  return <NestedNavigation.Provider value={navigation.nestedNavigation}><div className="app">
    {drawer && <button className="drawer-scrim" aria-label="Close navigation" onClick={closeDrawer} />}
    <aside className={`sidebar${drawer ? ' open' : ''}`} aria-label="Workspace navigation" onKeyDown={drawerKeys}>
      <div className="brand-row"><button className="brand" type="button" aria-label="katstrology. — New conversation" onClick={() => newChat()}><BrandKitten /><span>katstrology.</span></button><button className="side-close" ref={closeButton} aria-label="Close navigation" onClick={closeDrawer}>×</button></div>
      <div className="side-main-actions"><button className="new-chat" type="button" onClick={() => newChat()}>＋ &nbsp; New conversation</button>
        <button ref={chartNavButton} className="create-chart-nav" type="button" onClick={() => openChartHub()}>＋ &nbsp; Create chart</button></div>
      <nav aria-label="People"><div className="side-heading-row"><h2 className="side-heading">PEOPLE</h2><button aria-label="Add person" onClick={() => {
        personDialogOpener.current = document.activeElement as HTMLElement;
        navigation.openPersonDialog(); setPersonDialog(true);
      }}>＋</button></div>
        {people.length ? <div className="person-list">{people.map(item => <button key={item.id} className={`person-link${filterPersonId === item.id ? ' selected' : ''}`} onClick={() => {
          const version = navigation.beginSidebarPerson(item.id);
          peopleRequestVersion.current++;
          void api<Person>(`people/${item.id}`).then(selected => {
            if (navigation.isCurrent(version)) navigation.showSidebarPerson(selected);
          }).catch(() => { if (navigation.isCurrent(version)) setNotice('Person could not be opened.'); });
          discovery.clearSearch();
        }}><span className="initial">{item.name.charAt(0).toUpperCase()}</span><span>{item.name}</span></button>)}</div> : <p className="side-empty">No people yet.</p>}</nav>
      <nav aria-label="Recent conversations"><h2 className="side-heading" ref={historyHeading} tabIndex={-1}>RECENT CONVERSATIONS</h2>
        <button type="button" className="all-conversations-nav" onClick={allConversations}>All conversations</button>
        {filterPersonId && <p className="side-filter">For {people.find(p => p.id === filterPersonId)?.name || 'selected person'} <button onClick={() => { navigation.clearPersonFilter(); discovery.clearSearch(); }}>Show all</button></p>}
        <form className="search-conversations" onSubmit={e => { e.preventDefault(); discovery.search(); }}><label className="sr-only" htmlFor="thread-search">Search conversations</label><input id="thread-search" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search conversations" /><button type="submit">Search</button></form>
        {listStatus && <p className="side-filter" role="status">{listStatus}</p>}
        <div className="recent">{conversations.length ? <ConversationBrowseList conversations={conversations}
          selectedId={conversation?.id} zone={workspace.product.reporting_zone} onOpen={id => void openConversation(id)} /> :
          listStatus !== 'Loading conversations…' && !listStatus.startsWith('Conversations unavailable') &&
            <p className="side-empty">{searched ? 'No matches in current indexed conversations.' :
              filterPersonId ? 'No conversations for this person.' : 'No conversations yet.'}</p>}
          {nextConversationOffset !== null && <button onClick={() => void discovery.loadThreads(nextConversationOffset)}>Load older conversations</button>}</div>
      </nav>
      <div className="side-bottom"><button ref={settingsButton} type="button" onClick={openSettings}>Settings</button>
        <div className="account"><span className="initial">{workspace.owner.charAt(0).toUpperCase()}</span><span>{workspace.owner}<small>{workspace.workspace === 'personal' ? 'Personal workspace' : 'Local workspace'}</small></span></div><button type="button" onClick={signOut}>Sign out</button></div>
    </aside>
    <main className={`main${settingsOpen ? ' settings-main' : !person && !skyOpen && !chartHub ? ' chat-scroll-page' : ''}`} inert={drawer}>
      <header className="header"><div className="header-left"><button ref={menuButton} className="mobile-menu" aria-label="Open navigation" aria-expanded={drawer} onClick={navigation.openDrawer}>☰</button><span className="header-title">{settingsOpen ? 'Settings' : chartHub ? 'Create chart' : skyOpen ? 'Sky at a date' : person ? person.name : conversation?.title || 'New conversation'}</span></div><span className="model-label">{provider.error.startsWith('Connection status could not') ? 'ChatGPT connection unavailable' :
          provider.status.registration === 'offline' ?
            provider.status.connected ? 'ChatGPT account saved' : 'Chat not connected' :
            provider.status.connected ? 'ChatGPT connected' : 'Connect ChatGPT plan to send'}</span></header>
      {navigation.restoring && <p className="navigation-status" role="status">Opening saved view…</p>}
      {settingsOpen && <SettingsView workspace={workspace} provider={provider} onClose={closeSettings} />}
      <div className={settingsOpen ? 'settings-hidden' : 'settings-visible'} inert={settingsOpen}>
      {needsNatal ? <section className="chart-hub" aria-label="Natal required">
        <div className="chart-hub-heading"><div><h1>{chartOrigin.name} needs a current natal</h1>
          <p>Create a natal from this person’s supplied birth details to continue.</p></div>
          <button type="button" onClick={navigation.backToChartChoices}>Back to chart choices</button></div>
        <div className="chart-hub-people"><button type="button" className="primary" onClick={() => {
          navigation.createNatalForTechnique(chartHub); openHubPerson(chartOrigin.id);
        }}>Create natal for {chartOrigin.name}</button></div>
      </section> : <>
      {chartHub === 'synastry' && <SynastryView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        discussionDisabled={archive.hasPending || archive.busy}
        onClose={navigation.backToChartChoices} onCreate={id => openHubPerson(id)}
        onDiscuss={ids => {
          if (archive.hasPending || archive.busy) return;
          if (message.trim() && !window.confirm('Start a new discussion? Your current unsent draft will be cleared.')) return;
          newChat(ids);
        }} />}
      {(chartHub === 'solar_return' || chartHub === 'lunar_return') &&
        <AdvancedView key={chartHub} workspace={workspace} people={people} technique={chartHub}
          initialDraft={navigation.advancedDraft || undefined} initialPersonId={navigation.chartOriginId || undefined}
          onDiscuss={discussSavedResult}
          onClose={navigation.closeTechnique}
          onCreateNatal={(id, draft) => {
            navigation.createNatalFromAdvanced(chartHub, draft); openHubPerson(id);
          }} />}
      {chartHub === 'mc_transit' && <McTransitsView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'secondary_progression' && <ProgressionsView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'relationship_derived' && <RelationshipDerivedView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'true_solar_arc' && <SolarArcView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'progressed_lunar_phases' && <ProgressedPhasesView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'actual_lunations_eclipses' && <LunationsView workspace={workspace} people={people} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.backToChartChoices} />}
      {chartHub === 'planetary_return' && <PlanetaryReturnsView workspace={workspace} people={people}
        initialDraft={navigation.planetaryDraft || undefined} initialPersonId={navigation.chartOriginId || undefined}
        onClose={navigation.closeTechnique}
        onCreateNatal={(id, draft) => { navigation.createNatalFromPlanetary(draft); openHubPerson(id); }} />}
      {chartHub && chartHub !== 'synastry' && chartHub !== 'solar_return' &&
        chartHub !== 'lunar_return' && chartHub !== 'mc_transit' &&
        chartHub !== 'secondary_progression' && chartHub !== 'relationship_derived' &&
        chartHub !== 'true_solar_arc' && chartHub !== 'progressed_lunar_phases' &&
        chartHub !== 'actual_lunations_eclipses' && chartHub !== 'planetary_return' && <ChartHub choice={chartHub} people={people}
        onSelect={choice => {
          if (navigation.chartOriginId && (choice === 'natal' || choice === 'child')) {
            openHubPerson(navigation.chartOriginId, choice === 'child');
          } else navigation.selectChart(choice);
        }}
        onPerson={id => openHubPerson(id, chartHub === 'child')}
        onAddPerson={() => {
          personDialogOpener.current = document.activeElement as HTMLElement;
          setPersonDialog(true);
        }}
        onClose={() => chartHub === 'hub' ? closeChartHub() : navigation.backToChartChoices()} />}
      </>}
      {skyOpen && <TransitView workspace={workspace} people={people}
        initialPersonId={skyFromHub ? navigation.chartOriginId || undefined : person?.id || selection[0]?.person_id}
        returnLabel={skyFromHub ? 'Back to chart choices' : person ? 'Return to person' : 'Return to conversation'}
        onClose={navigation.closeSky} />}
      <div className={`reader-content${skyOpen || chartHub ? ' sky-hidden' : ''}`} inert={skyOpen || !!chartHub}>
      {person ? <PersonDetail key={person.id} workspace={workspace} person={person} refresh={refreshPeople} memory={personMemory(person.id)}
        openPerson={id => {
          const version = navigation.beginSidebarPerson(id);
          void api<Person>(`people/${id}`).then(selected => {
            if (navigation.isCurrent(version)) navigation.showSidebarPerson(selected);
          }).catch(() => setNotice('Person could not be opened.'));
        }}
        discussSavedResult={(selected, label) => discussSavedResult(person.id, selected, label)} createChart={() => openChartHub(person.id)} openSky={navigation.openPersonSky} libraryRevision={navigation.libraryRevision}
        initialEditorOpen={profileEditorPersonId === person.id} initialTab={profileChartFocus && profileFromHub ? 'charts' : 'overview'} editorRequest={profileEditorRequest}
        childFocus={profileChildFocus && profileFromHub} returnLabel={conversation ? 'conversation' : 'workspace'}
        onReturn={profileFromHub ? () => {
          navigation.returnFromPerson();
        } : undefined}
        startConversation={() => newChat(person.id)} openConversation={id => void openConversation(id)} onDeleted={() => {
        peopleRequestVersion.current++;
        personMemories.current.delete(person.id);
        navigation.personDeleted(person.id); setPeople(old => old.filter(item => item.id !== person.id));
        discovery.clearSearch();
      }} /> : <section className={conversation ? 'conversation' : 'home'}
        data-kat-conversation-id={conversation?.id || ''}
        aria-label={conversation ? 'Conversation' : 'New conversation'}>
        <div className={`chat-reading-grid${selection.length ? ' has-chart-context' : ''}`}>
        {conversation ? <div className="messages"><div className="conversation-toolbar"><span>{conversation.people.map(item => item.name).join(' & ') || 'General'} · one archived thread</span>
          <ConversationMenu>
            <button onClick={() => void renameConversation()} disabled={archive.busy}>Rename</button>
            <button onClick={() => void exportConversation()}>Export original JSONL</button>
            <button onClick={() => void deleteConversation()} disabled={archive.busy}>Delete conversation</button></ConversationMenu></div>
          {archive.turns.length ? archive.turns.map(turn => <TurnCard key={turn.id} turn={turn} people={people} workspace={workspace}
            conversationId={conversation.id} activeHead={conversation.active_head} actions={turnActions}
            eventFailure={archive.eventFailures[turn.id]} onInspectContext={inspectContext} />) : !archive.localPending && <p className="conversation-empty">This conversation has no messages yet. Its selected people are ready.</p>}
          {archive.localPending?.conversationId === conversation.id && <LocalPendingMessage pending={archive.localPending}
            onRetry={() => void retryPending()} onReconnect={openSettings} disabled={archive.busy || preparingSend} />}
          {headNotLoaded && <p className="conversation-empty" role="status">The current saved message is on another page. Load more saved messages before editing or sending.</p>}
          {archive.nextOffset !== null && <button className="quiet-action" onClick={() => { if (archive.nextOffset !== null) void archive.open(conversation.id, archive.nextOffset); }}>Load more saved messages</button>}
        </div> : archive.localPending?.conversationId === pendingConversationId.current ?
          <div className="messages pending-messages"><LocalPendingMessage pending={archive.localPending}
            onRetry={() => void retryPending()} onReconnect={openSettings} disabled={archive.busy || preparingSend} /></div> :
          <div className="welcome"><ReadingKitten /><div className="eyebrow">THE READING ROOM</div><h1>What’s on your mind?</h1><p>A chart, a question, or a thought to follow.</p></div>}
        <ContextChart selection={selection} people={people} turns={archive.turns} activeHead={conversation?.active_head || null} onOpenChart={openContextChart} />
        </div>
        <div className="composer-wrap" ref={chatComposer.dock}>{discuss && <p className="compose-context" role="status">
          Discuss {discuss.label} · saved result, not recalculated. Your draft is unchanged.
          <button type="button" onClick={() => setDiscuss(null)}>Remove result</button></p>}
          <form className="composer" onSubmit={event => { event.preventDefault(); void sendText(message); }}>
          <ScopeChips selection={selection} people={people}
            remove={id => setSelection(selection.filter(item => item.person_id !== id))}
            open={() => setScopePicker(true)} />
          {editing && <p className="edit-note">Editing an earlier message. The original remains saved. <button type="button" onClick={workflow.cancelEdit}>Cancel edit</button></p>}
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
        {archive.busy && archive.turns.some(turn => turn.status === 'open') && conversation && <button className="quiet-action" onClick={workflow.stopResponse}>Stop response</button>}
        {archive.sendError && <p className="error" role="alert">{archive.sendError}</p>}
        {archive.resumeError && <p className="error" role="status">{archive.resumeError} <button type="button"
          onClick={() => void archive.reconcile()}>Retry loading saved replies</button></p>}
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
      navigation.createdPerson(created); void refreshPeople();
    }} />
    {scopePicker && <ScopePicker people={people} selected={selection} onClose={() => setScopePicker(false)}
      onApply={setSelection} />}
  </div></NestedNavigation.Provider>;
}

