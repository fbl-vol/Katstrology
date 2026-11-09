import { useRef, useState, type SetStateAction } from 'react';
import { api } from '../shared/api';
import { useBrowserHistory } from './browser-history';
import type { Conversation } from '../features/conversation/conversation';
import type { Person } from '../features/people/people';
import type { ChartChoice } from '../features/charts/chart-hub';
import type { AdvancedDraft } from '../features/charts/advanced-view';
import type { PlanetaryReturnDraft } from '../features/charts/planetary-returns-view';

type ReturnIntent =
  | { kind: 'advanced'; choice: 'solar_return' | 'lunar_return'; draft: AdvancedDraft }
  | { kind: 'planetary'; draft: PlanetaryReturnDraft }
  | { kind: 'chart'; choice: ChartChoice };

type Navigation = {
  person: Person | null; conversation: Conversation | null; chartHub: ChartChoice | null;
  skyOpen: boolean; skyFromHub: boolean; settingsOpen: boolean; drawer: boolean;
  filterPersonId: string | null; profileFromHub: boolean; profileChartFocus: boolean;
  profileChildFocus: boolean; profileEditorPersonId: string | null; profileEditorRequest: number;
  advancedDraft: AdvancedDraft | null; planetaryDraft: PlanetaryReturnDraft | null;
  chartOriginId: string | null; libraryRevision: number;
  nested: Record<string, string>;
};

const initial: Navigation = {
  person: null, conversation: null, chartHub: null, skyOpen: false, skyFromHub: false,
  settingsOpen: false, drawer: false, filterPersonId: null, profileFromHub: false,
  profileChartFocus: false, profileChildFocus: false, profileEditorPersonId: null,
  profileEditorRequest: 0, advancedDraft: null, planetaryDraft: null,
  chartOriginId: null, libraryRevision: 0, nested: {},
};

function routeOf(view: Navigation, memory?: { intent: ReturnIntent | null; previousPersonId: string | null; previousFilter: string | null }) {
  const { person, conversation, libraryRevision: _library, profileEditorRequest: _editor, ...route } = view;
  // Drafts/return intents stay in this mounted session's RAM journal, never in
  // window.history.state, a URL or persistent storage. People are re-resolved.
  return { ...route, nested: Object.fromEntries(Object.entries(route.nested).sort(([a], [b]) => a.localeCompare(b))),
    personId: person?.id ?? null, conversationId: conversation?.id ?? null,
    returnIntent: memory?.intent ?? null, previousPersonId: memory?.previousPersonId ?? null,
    previousFilter: memory?.previousFilter ?? null };
}
type Route = ReturnType<typeof routeOf>;
function destination(route: Route) {
  return JSON.stringify([route.personId, route.conversationId, route.chartHub, route.skyOpen]);
}

/** Owns view/overlay transitions and return intents, not chat transport or thread creation. */
export function useWorkspaceNavigation(effects: { resetArchive: () => void; invalidateSubmission: () => void;
  restoreConversation: (conversation: Conversation | null, version: number) => Promise<void>;
  validateSession: () => Promise<void>;
  unavailable: (error: unknown) => void;
}) {
  const [view, setViewState] = useState<Navigation>(initial);
  const [restoring, setRestoring] = useState(false);
  const viewRef = useRef(view); viewRef.current = view;
  const pendingRoute = useRef<number | null>(null);
  const restorationVersion = useRef(0);
  const effectsRef = useRef(effects);
  effectsRef.current = effects;
  const version = useRef(0);
  const previousPerson = useRef<Person | null>(null);
  const previousFilter = useRef<string | null>(null);
  const returnIntent = useRef<ReturnIntent | null>(null);
  const focusProfile = useRef<{ id: string; navigation: number } | null>(null);

  function snapshot(view: Navigation) {
    return routeOf(view, { intent: returnIntent.current, previousPersonId: previousPerson.current?.id ?? null,
      previousFilter: previousFilter.current });
  }

  async function restore(route: Route): Promise<Route> {
    const current = viewRef.current;
    const restoration = ++restorationVersion.current;
    const live = () => restoration === restorationVersion.current && isCurrent(request);
    const sameDestination = destination(route) === destination(routeOf(current));
    const request = sameDestination && pendingRoute.current !== version.current ? version.current : ++version.current;
    pendingRoute.current = null;
    setRestoring(true);
    try {
      await effectsRef.current.validateSession();
      if (!live()) return routeOf(viewRef.current);
      let person = current.person, conversation = current.conversation;
      if (!sameDestination) {
        person = route.personId ? await api<Person>(`people/${encodeURIComponent(route.personId)}`) : null;
        conversation = route.conversationId ? await api<Conversation>(`conversations/${encodeURIComponent(route.conversationId)}`) : null;
        for (const id of new Set([route.chartOriginId, route.filterPersonId]))
          if (id && id !== route.personId) await api<Person>(`people/${encodeURIComponent(id)}`);
      }
      let priorPerson = previousPerson.current;
      if (priorPerson?.id !== route.previousPersonId)
        priorPerson = route.previousPersonId ? await api<Person>(`people/${encodeURIComponent(route.previousPersonId)}`) : null;
      if (!live()) return snapshot(viewRef.current);
      previousPerson.current = priorPerson; previousFilter.current = route.previousFilter;
      returnIntent.current = route.returnIntent;
      const next: Navigation = { ...current, ...route, person, conversation,
        profileEditorRequest: current.profileEditorRequest + (route.profileEditorPersonId !== current.profileEditorPersonId ? 1 : 0) };
      setViewState(next);
      if (conversation?.id !== current.conversation?.id) await effectsRef.current.restoreConversation(conversation, request);
      if (!live()) return routeOf(viewRef.current);
      return snapshot(next);
    } catch (error) {
      if (!live()) return routeOf(viewRef.current);
      leaveChat(); returnIntent.current = null; previousPerson.current = null; previousFilter.current = null;
      setViewState(initial); effectsRef.current.unavailable(error);
      return routeOf(initial);
    } finally { if (restoration === restorationVersion.current) setRestoring(false); }
  }
  const journey = useBrowserHistory(snapshot(view), routeOf(initial), pendingRoute.current === version.current,
    restore, (previous, next) => (previous.drawer && !next.drawer) ||
      (!!previous.nested['create-person'] && !next.nested['create-person'] && destination(previous) !== destination(next)));
  function setView(update: SetStateAction<Navigation>) {
    restorationVersion.current++; setRestoring(false);
    journey.cancelRestoration(); journey.remember(); setViewState(update);
  }
  function changeNested(key: string, value: string | null, replace = false, descendants: readonly string[] = []) {
    if ((view.nested[key] ?? null) === value && !descendants.some(child => child in view.nested)) return;
    if (replace) journey.replaceNext();
    if (value === null && !key.startsWith('person-tab:')) journey.backNext();
    setView(current => {
      const nested = { ...current.nested };
      if (value === null) {
        delete nested[key];
        for (const child of descendants) delete nested[child];
      } else nested[key] = value;
      return { ...current, nested };
    });
  }

  function leaveChat() {
    effectsRef.current.resetArchive();
    effectsRef.current.invalidateSubmission();
  }

  function signOut() {
    version.current++;
    returnIntent.current = null;
    leaveChat();
    setView(initial);
  }

  function allConversations() {
    version.current++;
    leaveChat();
    returnIntent.current = null;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, skyFromHub: false,
      chartHub: null, chartOriginId: null, person: null, conversation: null, filterPersonId: null,
      profileFromHub: false, profileChartFocus: false, profileChildFocus: false,
      advancedDraft: null, planetaryDraft: null }));
  }

  function newConversation() {
    version.current++;
    leaveChat();
    returnIntent.current = null;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: null,
      chartOriginId: null, profileChartFocus: false, person: null, conversation: null, drawer: false }));
  }

  function beginConversation() {
    const request = ++version.current;
    pendingRoute.current = request;
    returnIntent.current = null;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: null, chartOriginId: null }));
    return request;
  }

  function isCurrent(request: number) { return request === version.current; }

  function showConversation(thread: Conversation) {
    pendingRoute.current = null;
    setView(current => ({ ...current, conversation: thread, person: null, drawer: false }));
  }

  function openChartHub(originId: string | null = null) {
    version.current++;
    returnIntent.current = null;
    previousPerson.current = view.person;
    previousFilter.current = view.filterPersonId;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: 'hub',
      advancedDraft: null, planetaryDraft: null, drawer: false, chartOriginId: originId }));
  }

  function selectChart(choice: ChartChoice | 'transits') {
    if (choice === 'transits') {
      setView(current => ({ ...current, chartHub: null, skyFromHub: true, skyOpen: true }));
    } else setView(current => ({ ...current, chartHub: choice }));
  }

  function backToChartChoices() { journey.backNext(); setView(current => ({ ...current, chartHub: 'hub' })); }
  function closeChartHub() {
    journey.backNext();
    returnIntent.current = null;
    setView(current => ({ ...current, chartHub: null, chartOriginId: null,
      libraryRevision: current.libraryRevision + 1 }));
  }
  function closeTechnique() {
    journey.backNext();
    setView(current => ({ ...current, chartHub: 'hub', advancedDraft: null, planetaryDraft: null }));
  }
  function closeSky() {
    journey.backNext();
    setView(current => ({ ...current, skyOpen: false, skyFromHub: false,
      chartHub: current.skyFromHub ? 'hub' : current.chartHub }));
  }

  function openConversationPerson(person: Person, tab: 'charts' | 'context') {
    version.current++;
    previousPerson.current = null;
    previousFilter.current = view.filterPersonId;
    setView(current => ({ ...current, person, filterPersonId: person.id,
      profileFromHub: true, profileChartFocus: tab === 'charts', profileChildFocus: false,
      nested: { ...current.nested, [`person-tab:${person.id}`]: tab },
      profileEditorPersonId: null, skyOpen: false, chartHub: null, chartOriginId: null, drawer: false }));
  }

  function beginHubPerson() {
    const request = ++version.current;
    pendingRoute.current = request;
    setView(current => ({ ...current, settingsOpen: false }));
    return request;
  }

  function showHubPerson(person: Person, child: boolean) {
    pendingRoute.current = null;
    setView(current => ({ ...current, person, profileEditorPersonId: person.id,
      profileEditorRequest: current.profileEditorRequest + 1, profileChildFocus: child,
      profileFromHub: true, profileChartFocus: false, filterPersonId: person.id,
      chartHub: null, drawer: false }));
  }

  function abandonReturn() { returnIntent.current = null; }
  function createNatalForTechnique(choice: ChartChoice) {
    returnIntent.current = { kind: 'chart', choice };
  }
  function createNatalFromAdvanced(choice: 'solar_return' | 'lunar_return', draft: AdvancedDraft) {
    journey.remember({ ...snapshot(view), advancedDraft: draft });
    returnIntent.current = { kind: 'advanced', choice, draft };
  }
  function createNatalFromPlanetary(draft: PlanetaryReturnDraft) {
    journey.remember({ ...snapshot(view), planetaryDraft: draft });
    returnIntent.current = { kind: 'planetary', draft };
  }

  function returnFromPerson() {
    journey.backNext();
    version.current++;
    const resume = returnIntent.current;
    returnIntent.current = null;
    setView(current => ({ ...current,
      person: current.conversation ? null : current.person?.id === previousPerson.current?.id ? current.person : previousPerson.current,
      filterPersonId: previousFilter.current, profileFromHub: false,
      profileChildFocus: false, profileChartFocus: false,
      chartHub: resume?.kind === 'advanced' || resume?.kind === 'chart' ? resume.choice : resume?.kind === 'planetary' ? 'planetary_return' : current.chartHub,
      chartOriginId: resume ? current.chartOriginId : null, profileEditorPersonId: null,
      libraryRevision: current.libraryRevision + 1,
      advancedDraft: resume?.kind === 'advanced' ? resume.draft : current.advancedDraft,
      planetaryDraft: resume?.kind === 'planetary' ? resume.draft : current.planetaryDraft }));
  }

  function beginSidebarPerson(id: string) {
    const request = ++version.current;
    pendingRoute.current = request;
    returnIntent.current = null;
    focusProfile.current = { id, navigation: request };
    effectsRef.current.resetArchive();
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, skyFromHub: false,
      chartHub: null, chartOriginId: null, person: null, profileEditorPersonId: null, profileFromHub: false,
      profileChartFocus: false, profileChildFocus: false, filterPersonId: id,
      conversation: null, drawer: false,
      nested: Object.fromEntries(Object.entries(current.nested).filter(([key]) =>
        !key.startsWith('natal:') && !key.startsWith('library:') && !key.startsWith('library-history:'))) }));
    return request;
  }

  function showSidebarPerson(person: Person) {
    pendingRoute.current = null;
    setView(current => ({ ...current, person }));
  }

  function createdPerson(person: Person) {
    setView(current => ({ ...current, settingsOpen: false,
      chartHub: current.chartHub === 'natal' || current.chartHub === 'child' ? null : current.chartHub,
      profileFromHub: current.chartHub === 'natal' || current.chartHub === 'child' ? true : current.profileFromHub,
      profileChildFocus: current.chartHub === 'child' ? true : current.profileChildFocus,
      profileEditorPersonId: person.id, profileEditorRequest: current.profileEditorRequest + 1,
      person }));
  }

  function personDeleted(id: string) {
    version.current++;
    effectsRef.current.resetArchive();
    returnIntent.current = null;
    setView(current => current.person?.id !== id ? current : ({ ...current,
      person: null, filterPersonId: null }));
  }

  function discussResult() {
    version.current++;
    leaveChat();
    setView(current => ({ ...current, settingsOpen: false, chartHub: null, skyOpen: false,
      person: null, conversation: null, drawer: false, chartOriginId: null }));
  }

  return { ...view, restoring, nestedNavigation: { state: view.nested, change: changeNested }, version, focusProfile, isCurrent, signOut, allConversations, newConversation,
    beginConversation, showConversation, openChartHub, selectChart, backToChartChoices,
    closeChartHub, closeTechnique, closeSky, openConversationPerson, beginHubPerson, showHubPerson,
    openPersonSky: () => setView(current => ({ ...current, skyOpen: true, skyFromHub: false })),
    abandonReturn, createNatalForTechnique, createNatalFromAdvanced, createNatalFromPlanetary, returnFromPerson,
    beginSidebarPerson, showSidebarPerson, createdPerson, personDeleted, discussResult,
    openDrawer: () => setView(current => ({ ...current, drawer: true })),
    closeDrawer: () => { journey.backNext(); setView(current => ({ ...current, drawer: false })); },
    openSettings: () => setView(current => ({ ...current, settingsOpen: true, drawer: false })),
    closeSettings: () => { journey.backNext(); setView(current => ({ ...current, settingsOpen: false })); },
    openPersonDialog: () => setView(current => ({ ...current, settingsOpen: false, drawer: false })),
    clearPersonFilter: () => setView(current => ({ ...current, filterPersonId: null })),
    updatePerson: (update: (current: Person | null) => Person | null) =>
      setViewState(current => ({ ...current, person: update(current.person) })),
    updateConversation: (update: (current: Conversation | null) => Conversation | null) =>
      setViewState(current => ({ ...current, conversation: update(current.conversation) })),
  };
}
