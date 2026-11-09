import React, { useEffect, useId, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import { BirthWorkflow, type Generation } from './birth-workflow';
import { NatalChart, type Chart } from '../charts/natal';
import { InsightNotebook } from './insights';
import { PersonTiming } from './person-timing';
import { ChartLibrary, type LibraryMemory } from '../charts/chart-library';
import { useNestedNavigation } from '../../shared/nested-navigation';
import { PersonRecords } from './person-records';
import { PersonalContextPane, type ContextMemory } from './personal-context';
import { PersonalProfile, type ProfileMemory } from './personal-profile';
export type PersonMemory = { tab?: 'overview' | 'context' | 'charts' | 'saved'; context: ContextMemory; profile: ProfileMemory; charts?: LibraryMemory };
import { AstrologyHelp } from '../charts/astrology-help';
import type { SelectedResult } from '../conversation/archive';

export type Draft = { birth_date: string; birth_time: string; birthplace: string; time_unknown: boolean };
export type EditorLocation = { kind: 'catalogue' | 'manual' | 'review';
  latitude: number | null; longitude: number | null; zone: string; fold: number | null; provisional: boolean;
  place?: { id: string; name: string; region: string; country: string; latitude: number; longitude: number; zone: string };
  latitude_override?: number; longitude_override?: number; zone_override?: string | null };
export type Person = {
  id: string; name: string; active_chart_id: string | null; active_chart_draft_revision?: number | null;
  editor_location?: EditorLocation | null;
  drafts: { revision: number; details: Draft }[];
  birth_records: { id: string; wall_time: string | null; zone_name: string; earliest_utc: string | null; latest_utc: string | null }[];
  charts: Chart[];
};

export function CreatePersonDialog({ open, workspace, onClose, onCreated }: {
  open: boolean; workspace: Workspace; onClose: (created: boolean) => void; onCreated: (person: Person) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const formId = useId();
  const completed = useRef(false);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && !dialog.current?.open) { dialog.current?.showModal(); nameInput.current?.focus(); }
    if (!open && dialog.current?.open) dialog.current?.close();
  }, [open]);

  function reset() { setName(''); setError(''); }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    try {
      const person = await api<Person>('people', workspace.csrf, 'POST', { name });
      completed.current = true;
      onCreated(person);
      dialog.current?.close();
    } catch {
      setError('Person creation was not confirmed. Check this workspace before trying again; your name is still here.');
    } finally { setBusy(false); }
  }

  return <dialog ref={dialog} onClose={() => {
    const created = completed.current;
    completed.current = false;
    reset(); onClose(created);
  }} aria-labelledby={`${formId}-title`}>
    <form className="dialog-body" onSubmit={submit}>
      <div className="dialog-top"><h2 id={`${formId}-title`}>A space for someone new.</h2><button type="button" aria-label="Close new person form" onClick={() => dialog.current?.close()}>×</button></div>
      <p>Birth details are optional. You can add them later to calculate a chart.</p>
      <div className="field"><label htmlFor={`${formId}-name`}>Name</label><input id={`${formId}-name`} ref={nameInput} required maxLength={128} value={name} onChange={event => setName(event.target.value)} /></div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="dialog-footer"><button type="button" onClick={() => dialog.current?.close()}>Cancel</button><button type="submit" className="primary" disabled={busy}>{busy ? 'Saving…' : 'Create person'}</button></div>
    </form>
  </dialog>;
}

export function PersonDetail({ workspace, person, refresh, startConversation, openConversation, onDeleted,
  initialEditorOpen = false, initialTab = 'overview', editorRequest = 0, childFocus = false, onReturn, returnLabel = 'workspace',
  discussSavedResult, createChart, openSky, openPerson, memory, libraryRevision = 0 }: {
  workspace: Workspace; person: Person; refresh: () => Promise<void>; openPerson: (id: string) => void; memory: PersonMemory;
  startConversation: () => void; openConversation: (id: string) => void;
  discussSavedResult: (result: SelectedResult, label: string) => void;
  onDeleted: () => void; initialEditorOpen?: boolean; initialTab?: 'overview' | 'context' | 'charts'; editorRequest?: number;
  libraryRevision?: number; childFocus?: boolean; onReturn?: () => void; returnLabel?: string; createChart?: () => void; openSky?: () => void;
}) {
  const tabsId = useId();
  const tabNavigation = useNestedNavigation(`person-tab:${person.id}`);
  const defaultTab = initialEditorOpen || initialTab === 'charts' ? 'charts' : initialTab;
  const tab = (tabNavigation.value ?? defaultTab) as 'overview' | 'context' | 'charts' | 'saved';
  function setTab(value: typeof tab) { if (value !== tab) tabNavigation.change(value === defaultTab ? null : value); }
  memory.charts ??= { results: {} };
  memory.tab = tab;
  const [natalRequest, setNatalRequest] = useState(initialTab === 'charts' && !initialEditorOpen ? 1 : 0);
  const [savedSection, setSavedSection] = useState<'insights' | 'later' | 'journal'>('insights');
  const [savedOpenRequest, setSavedOpenRequest] = useState(0);
  const [openedCharts, setOpenedCharts] = useState<Set<string>>(() => new Set());
  const [timingOpen, setTimingOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(initialEditorOpen);
  const [watchVersion, setWatchVersion] = useState(0);
  const [generated, setGenerated] = useState<{ result: Generation; draft: Draft } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([null, null, null, null]);
  const editorRef = useRef<HTMLDivElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const activeChart = (generated && generated.result.active_chart_id === generated.result.chart.id ? generated.result.chart : null) ||
    person.charts.find(chart => chart.id === person.active_chart_id);
  const hasActive = !!(person.active_chart_id || activeChart);
  const generatedActive = !!generated && generated.result.active_chart_id === generated.result.chart.id;
  const activeRevision = generatedActive ? generated?.result.draft_revision : person.active_chart_draft_revision;
  const latestDraft = generatedActive && (!person.drafts[0] || person.drafts[0].revision <= generated!.result.draft_revision) ?
    generated!.draft : person.drafts[0]?.details;
  const newerDraft = !!activeChart && activeRevision != null && !!person.drafts[0] && person.drafts[0].revision > activeRevision;
  const savedBirth = activeChart && person.birth_records.find(record => record.id === activeChart.birth_id);
  const savedWallTime = savedBirth?.wall_time ?? activeChart?.result.birth.wall_time;
  const savedTime = savedWallTime ? savedWallTime.slice(11, 16) : savedWallTime === null ? 'unknown' : 'not recorded';
  const savedDate = savedWallTime?.slice(0, 10) ?? (generatedActive ? generated?.draft.birth_date :
    person.drafts.find(item => item.revision === activeRevision)?.details.birth_date);

  useEffect(() => {
    if (initialEditorOpen) {
      setTab('charts'); setEditorOpen(true);
      window.requestAnimationFrame(() => editorRef.current?.focus());
    } else setEditorOpen(false);
  }, [initialEditorOpen, editorRequest]);

  function openEditor() {
    setTab('charts'); setEditorOpen(true);
    window.requestAnimationFrame(() => editorRef.current?.focus());
  }

  function switchTab(event: React.KeyboardEvent, index: number) {
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 3 :
      event.key === 'ArrowRight' ? (index + 1) % 4 :
      event.key === 'ArrowLeft' ? (index + 3) % 4 : null;
    if (next === null) return;
    event.preventDefault();
    setTab((['overview', 'context', 'charts', 'saved'] as const)[next]);
    tabRefs.current[next]?.focus();
  }

  function openSaved(section: 'insights' | 'later' | 'journal') {
    setSavedSection(section);
    setSavedOpenRequest(request => request + 1);
    setTab('saved');
  }

  return <section className="person-page" data-active-section={tab} aria-labelledby="person-heading">
    {onReturn && <button type="button" className="profile-return" onClick={onReturn}>← Return to {returnLabel}</button>}
    {childFocus && <p className="profile-child-note">Child’s natal uses the same numerical natal chart. It adds no child-status field, diagnosis, paid interpretation or deterministic personality label. Any later discussion is a separate, explicit choice.</p>}
    <div className="profile-header"><div>
      <h1 id="person-heading" tabIndex={-1}>{person.name}</h1>
      <p className="profile-summary">{latestDraft ? <>{latestDraft.birth_date || 'Date not supplied'} · {latestDraft.time_unknown ? 'Birth time unknown' : latestDraft.birth_time || 'Time not supplied'} · {latestDraft.birthplace || 'Place not supplied'} <small>(latest user-supplied details)</small></> :
        'Birth details have not been supplied. No time or place is inferred.'}</p>
      {activeChart?.source_status !== 'current' && activeChart && <p className="profile-caution">The active chart’s source is {activeChart.source_status}; inspect its original details before relying on it.</p>}
      {newerDraft && <p className="profile-draft-notice" role="status"><strong>Latest details are not in the current chart.</strong> The saved chart still uses {savedTime === 'unknown' ? 'an unknown birth time' : savedTime === 'not recorded' ? 'birth inputs without a recorded time' : `the saved birth time of ${savedTime}`}{savedDate ? ` on ${savedDate}` : ''}. Start conversation still uses this saved chart until you calculate an updated version.</p>}
      <button ref={editButtonRef} type="button" className="profile-edit-action" onClick={openEditor} aria-controls={`${tabsId}-editor`} aria-expanded={editorOpen}>
        {hasActive ? 'Edit birth details' : 'Add birth details'}</button>
    </div><button type="button" className={`${tab === 'overview' ? 'primary ' : ''}profile-chat-action`} onClick={startConversation}>Start conversation</button></div>
    <div className="profile-tabs" role="tablist" aria-label="Person sections">
      {(['overview', 'context', 'charts', 'saved'] as const).map((item, index) => <button key={item} type="button" role="tab"
        id={`${tabsId}-${item}-tab`} aria-controls={`${tabsId}-${item}-panel`} aria-selected={tab === item}
        tabIndex={tab === item ? 0 : -1} ref={element => { tabRefs.current[index] = element; }}
        onKeyDown={event => switchTab(event, index)} onClick={() => setTab(item)}>
        {item === 'overview' ? 'Overview' : item === 'context' ? 'Context' : item === 'charts' ? 'Charts' : 'Saved'}</button>)}
    </div>
    <section id={`${tabsId}-overview-panel`} role="tabpanel" aria-labelledby={`${tabsId}-overview-tab`} hidden={tab !== 'overview'} className="profile-panel">
      <PersonalProfile workspace={workspace} personId={person.id} active={tab === 'overview'} openPerson={openPerson} memory={memory.profile} />
      <p className="profile-group-label">Explore</p>
      <div className="profile-quiet-group">
        <button type="button" className="profile-quiet-row" onClick={() => {
          if (hasActive) { setTab('charts'); setNatalRequest(value => value + 1); }
          else openEditor();
        }}>
          <span className="profile-row-icon" aria-hidden="true">☉</span><span><strong>{hasActive ? 'Birth chart' : 'First birth chart'}</strong>
            <small>{hasActive ? activeChart?.source_status !== 'current' ? 'Saved chart · source needs review' :
              activeChart?.result.natal?.status === 'unsupported_uncertain_birth_time' ? 'Limited chart · birth time unknown' :
                activeChart?.result.natal?.status === 'complete' ? 'Your current natal, placements and aspects' : 'Limited saved chart' :
              'Create a chart from the details you know'}</small></span><span className="profile-row-arrow" aria-hidden="true">›</span>
        </button>
        <details className="profile-timing-row" onToggle={event => setTimingOpen(event.currentTarget.open)}>
          <summary className="profile-quiet-row"><span className="profile-row-icon" aria-hidden="true">◷</span>
            <span><strong>Saved timing</strong><small>Explore calculations already saved for this person</small></span>
            <span className="profile-row-arrow" aria-hidden="true">›</span></summary>
          {timingOpen && <div className="profile-timing-content"><PersonTiming workspace={workspace} person={person}
            onDiscuss={discussSavedResult} onWatch={() => setWatchVersion(value => value + 1)} /></div>}
        </details>
      </div>
      <p className="profile-group-label">Saved</p>
      <div className="profile-quiet-group">
        {([['insights', '✧', 'Insights', 'Passages you chose to keep from conversations'],
          ['later', '⌑', 'Saved for later', 'Saved results and optional in-app reminders'],
          ['journal', '≋', 'Private journal', 'Your own dated reflections and notes']] as const).map(([key, icon, label, description]) =>
          <button key={key} type="button" className="profile-quiet-row" onClick={() => openSaved(key)}>
            <span className="profile-row-icon" aria-hidden="true">{icon}</span>
            <span><strong>{label}</strong><small>{description}</small></span>
            <span className="profile-row-arrow" aria-hidden="true">›</span>
          </button>)}
      </div>
      <p className="profile-overview-note">The chart, conversation and notes stay separate. Open what you want to explore.</p>
    </section>
    <section id={`${tabsId}-context-panel`} role="tabpanel" aria-labelledby={`${tabsId}-context-tab`} hidden={tab !== 'context'} className="profile-panel">
      <PersonalContextPane workspace={workspace} personId={person.id} active={tab === 'context'} memory={memory.context} />
    </section>
    <section id={`${tabsId}-charts-panel`} role="tabpanel" aria-labelledby={`${tabsId}-charts-tab`} hidden={tab !== 'charts'} className="profile-panel">
      {!editorOpen && <ChartLibrary key={person.id} memory={memory.charts} workspace={workspace} personId={person.id} refreshRevision={libraryRevision} activeChartId={activeChart?.id || person.active_chart_id}
        enabled={tab === 'charts'} natalRequest={natalRequest} onCreate={createChart || openEditor} onCreateNatal={openEditor} onDiscuss={discussSavedResult} onSky={openSky} />}
      {editorOpen && <>
      <div className="profile-chart-heading"><div><h2>{activeChart?.source_status !== 'current' ? 'Saved birth chart' : 'Current birth chart'}</h2>
        <p>{activeChart ? <>Calculated from saved birth details{savedDate && ` · ${savedDate}`} · {savedTime === 'unknown' ? 'birth time unknown' : savedTime === 'not recorded' ? 'birth time not recorded' : `saved birth time ${savedTime}`}. Earlier versions stay below.</> :
          'No active generated natal. Nothing is guessed from a draft or an earlier chart.'}</p></div>
      </div>
      {activeChart ? <div className="profile-active-chart">{activeChart.result.natal ? <NatalChart chart={activeChart} allowMotion explorationEnabled={tab === 'charts'} onSky={openSky} /> :
        <p>This generated chart has only supported partial/solar information. Birth time or houses were not inferred.</p>}</div> :
        <div className="profile-chart-empty"><p>Supply the birth details below to generate the first chart.</p></div>}
      </>}
      <div id={`${tabsId}-editor`} ref={editorRef} tabIndex={-1} hidden={!editorOpen} className="profile-editor">
        <div className="profile-editor-heading"><h2>{hasActive ? 'Update current natal' : 'Create first chart'}</h2>
          <button type="button" onClick={() => { setEditorOpen(false); editButtonRef.current?.focus(); }}>Close editor</button></div>
        <BirthWorkflow person={person} workspace={workspace} refresh={refresh}
          onGenerated={(result, draft) => setGenerated({ result, draft })} compact discussChart={startConversation} />
      </div>
      <details className="reference-disclosure chart-history"><summary>Earlier charts and birth details</summary>
        <p>Earlier versions stay here. They do not replace the current chart in a new conversation.</p>
        {person.drafts.length > 0 && <ul>{person.drafts.map((item, index) => <li key={item.revision}>Supplied details {index + 1} · {item.details.birth_date || 'Date not supplied'} · {item.details.time_unknown ? 'Time unknown' : item.details.birth_time || 'Time not supplied'} · {item.details.birthplace || 'Place not supplied'}</li>)}</ul>}
        {person.birth_records.length > 0 && <ul>{person.birth_records.map(item => <li key={item.id}>Recorded birth · {item.wall_time?.replace('T', ' ') || (item.earliest_utc && item.latest_utc ? `${item.earliest_utc} to ${item.latest_utc}` : 'Time unavailable')} · {item.zone_name}</li>)}</ul>}
        {person.charts.map((chart, index) => {
          const birth = person.birth_records.find(record => record.id === chart.birth_id);
          return <details key={chart.id} data-kat-chart-id={chart.id} onToggle={event => {
            if (event.currentTarget.open) setOpenedCharts(previous => new Set(previous).add(chart.id));
          }}><summary>{chart.id === person.active_chart_id ? 'Current natal' : 'Historical chart'} · {birth?.wall_time?.slice(0, 10) || birth?.earliest_utc?.slice(0, 10) || 'Birth date unavailable'} · Chart {index + 1}</summary>
            {chart.result.natal ? openedCharts.has(chart.id) && <NatalChart chart={chart} /> : <p>{chart.source_status !== 'current' ? `Source: ${chart.source_status}. ` : ''}A full natal wheel is unavailable for this saved chart. Its birth details are listed above.</p>}
          </details>;
        })}
      </details>
    </section>
    <section id={`${tabsId}-saved-panel`} role="tabpanel" aria-labelledby={`${tabsId}-saved-tab`}
      hidden={tab !== 'saved'} className="profile-panel">
      <div className="profile-saved-sections" aria-label="Saved sections">
        {([['insights', 'Insights'], ['later', 'Saved for later'], ['journal', 'Private journal']] as const).map(([key, label]) =>
          <button key={key} type="button" aria-pressed={savedSection === key} onClick={() => openSaved(key)}>{label}</button>)}
      </div>
      <div hidden={savedSection !== 'insights'}>
        <InsightNotebook workspace={workspace} personId={person.id} active={tab === 'saved' && savedSection === 'insights'} openConversation={openConversation} />
      </div>
      <PersonRecords workspace={workspace} personId={person.id} onDiscuss={discussSavedResult}
        watchVersion={watchVersion} section={tab === 'saved' ? savedSection : 'insights'} openRequest={savedOpenRequest} />
    </section>
    <div className="profile-footer"><AstrologyHelp />
      <details className="profile-secondary"><summary>Manage person</summary>
        <p>Delete related conversations first. Removal is journaled; earlier external exports cannot be recalled.</p>
        <button type="button" disabled={busy} onClick={() => {
          if (!window.confirm(`Delete ${person.name} and their saved chart versions? Related conversations must already be removed.`)) return;
          setBusy(true); setError('');
          void api(`people/${person.id}`, workspace.csrf, 'DELETE')
            .then(onDeleted)
            .catch(() => setError('Person deletion was blocked or unavailable. Delete related conversations first; the original records remain.'))
            .finally(() => setBusy(false));
        }}>Delete this person</button>
      </details>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
