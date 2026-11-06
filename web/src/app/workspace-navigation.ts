import { useRef, useState } from 'react';
import type { Conversation } from '../conversation';
import type { Person } from '../people';
import type { ChartChoice } from '../chart-hub';
import type { AdvancedDraft } from '../advanced-view';
import type { PlanetaryReturnDraft } from '../planetary-returns-view';

type ReturnIntent =
  | { kind: 'advanced'; choice: 'solar_return' | 'lunar_return'; draft: AdvancedDraft }
  | { kind: 'planetary'; draft: PlanetaryReturnDraft };

type Navigation = {
  person: Person | null; conversation: Conversation | null; chartHub: ChartChoice | null;
  skyOpen: boolean; skyFromHub: boolean; settingsOpen: boolean; drawer: boolean;
  filterPersonId: string | null; profileFromHub: boolean; profileChartFocus: boolean;
  profileChildFocus: boolean; profileEditorPersonId: string | null; profileEditorRequest: number;
  advancedDraft: AdvancedDraft | null; planetaryDraft: PlanetaryReturnDraft | null;
};

const initial: Navigation = {
  person: null, conversation: null, chartHub: null, skyOpen: false, skyFromHub: false,
  settingsOpen: false, drawer: false, filterPersonId: null, profileFromHub: false,
  profileChartFocus: false, profileChildFocus: false, profileEditorPersonId: null,
  profileEditorRequest: 0, advancedDraft: null, planetaryDraft: null,
};

/** Owns view/overlay transitions and return intents, not chat transport or thread creation. */
export function useWorkspaceNavigation(effects: { resetArchive: () => void; invalidateSubmission: () => void }) {
  const [view, setView] = useState<Navigation>(initial);
  const effectsRef = useRef(effects);
  effectsRef.current = effects;
  const version = useRef(0);
  const previousPerson = useRef<Person | null>(null);
  const previousFilter = useRef<string | null>(null);
  const returnIntent = useRef<ReturnIntent | null>(null);
  const focusProfile = useRef<{ id: string; navigation: number } | null>(null);

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
      chartHub: null, person: null, conversation: null, filterPersonId: null,
      profileFromHub: false, profileChartFocus: false, profileChildFocus: false,
      advancedDraft: null, planetaryDraft: null }));
  }

  function newConversation() {
    version.current++;
    leaveChat();
    returnIntent.current = null;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: null,
      profileChartFocus: false, person: null, conversation: null, drawer: false }));
  }

  function beginConversation() {
    const request = ++version.current;
    returnIntent.current = null;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: null }));
    return request;
  }

  function isCurrent(request: number) { return request === version.current; }

  function showConversation(thread: Conversation) {
    setView(current => ({ ...current, conversation: thread, person: null, drawer: false }));
  }

  function openChartHub() {
    version.current++;
    returnIntent.current = null;
    previousPerson.current = view.person;
    previousFilter.current = view.filterPersonId;
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, chartHub: 'hub',
      advancedDraft: null, planetaryDraft: null, drawer: false }));
  }

  function selectChart(choice: ChartChoice | 'transits') {
    if (choice === 'transits') {
      setView(current => ({ ...current, chartHub: null, skyFromHub: true, skyOpen: true }));
    } else setView(current => ({ ...current, chartHub: choice }));
  }

  function backToChartChoices() { setView(current => ({ ...current, chartHub: 'hub' })); }
  function closeChartHub() { setView(current => ({ ...current, chartHub: null })); }
  function closeTechnique() {
    setView(current => ({ ...current, chartHub: 'hub', advancedDraft: null, planetaryDraft: null }));
  }
  function closeSky() {
    setView(current => ({ ...current, skyOpen: false, skyFromHub: false,
      chartHub: current.skyFromHub ? 'hub' : current.chartHub }));
  }

  function openContextChart(person: Person) {
    version.current++;
    previousPerson.current = null;
    previousFilter.current = view.filterPersonId;
    setView(current => ({ ...current, person, filterPersonId: person.id,
      profileFromHub: true, profileChartFocus: true, profileChildFocus: false,
      profileEditorPersonId: null, skyOpen: false, chartHub: null, drawer: false }));
  }

  function beginHubPerson() {
    const request = ++version.current;
    setView(current => ({ ...current, settingsOpen: false }));
    return request;
  }

  function showHubPerson(person: Person, child: boolean) {
    setView(current => ({ ...current, person, profileEditorPersonId: person.id,
      profileEditorRequest: current.profileEditorRequest + 1, profileChildFocus: child,
      profileFromHub: true, profileChartFocus: false, filterPersonId: person.id,
      chartHub: null, drawer: false }));
  }

  function abandonReturn() { returnIntent.current = null; }
  function createNatalFromAdvanced(choice: 'solar_return' | 'lunar_return', draft: AdvancedDraft) {
    returnIntent.current = { kind: 'advanced', choice, draft };
  }
  function createNatalFromPlanetary(draft: PlanetaryReturnDraft) {
    returnIntent.current = { kind: 'planetary', draft };
  }

  function returnFromPerson() {
    version.current++;
    const resume = returnIntent.current;
    returnIntent.current = null;
    setView(current => ({ ...current, person: current.conversation ? null : previousPerson.current,
      filterPersonId: previousFilter.current, profileFromHub: false,
      profileChildFocus: false, profileChartFocus: false,
      chartHub: resume?.kind === 'advanced' ? resume.choice : resume?.kind === 'planetary' ? 'planetary_return' : current.chartHub,
      advancedDraft: resume?.kind === 'advanced' ? resume.draft : current.advancedDraft,
      planetaryDraft: resume?.kind === 'planetary' ? resume.draft : current.planetaryDraft }));
  }

  function beginSidebarPerson(id: string) {
    const request = ++version.current;
    returnIntent.current = null;
    focusProfile.current = { id, navigation: request };
    effectsRef.current.resetArchive();
    setView(current => ({ ...current, settingsOpen: false, skyOpen: false, skyFromHub: false,
      chartHub: null, profileEditorPersonId: null, profileFromHub: false,
      profileChartFocus: false, profileChildFocus: false, filterPersonId: id,
      conversation: null, drawer: false }));
    return request;
  }

  function showSidebarPerson(person: Person) {
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
      person: null, conversation: null, drawer: false }));
  }

  return { ...view, version, focusProfile, isCurrent, signOut, allConversations, newConversation,
    beginConversation, showConversation, openChartHub, selectChart, backToChartChoices,
    closeChartHub, closeTechnique, closeSky, openContextChart, beginHubPerson, showHubPerson,
    abandonReturn, createNatalFromAdvanced, createNatalFromPlanetary, returnFromPerson,
    beginSidebarPerson, showSidebarPerson, createdPerson, personDeleted, discussResult,
    openDrawer: () => setView(current => ({ ...current, drawer: true })),
    closeDrawer: () => setView(current => ({ ...current, drawer: false })),
    openSettings: () => setView(current => ({ ...current, settingsOpen: true, drawer: false })),
    closeSettings: () => setView(current => ({ ...current, settingsOpen: false })),
    openPersonDialog: () => setView(current => ({ ...current, settingsOpen: false, drawer: false })),
    clearPersonFilter: () => setView(current => ({ ...current, filterPersonId: null })),
    updatePerson: (update: (current: Person | null) => Person | null) =>
      setView(current => ({ ...current, person: update(current.person) })),
    updateConversation: (update: (current: Conversation | null) => Conversation | null) =>
      setView(current => ({ ...current, conversation: update(current.conversation) })),
  };
}
