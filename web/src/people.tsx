import React, { useEffect, useId, useRef, useState } from 'react';
import { api, type Workspace } from './api';
import { BirthWorkflow, type Generation } from './birth-workflow';
import { NatalChart, type Chart } from './natal';
import { InsightNotebook } from './insights';
import { PersonTiming } from './person-timing';
import { PersonRecords } from './person-records';
import { AstrologyHelp } from './astrology-help';
import type { SelectedResult } from './archive';

export type Draft = { birth_date: string; birth_time: string; birthplace: string; time_unknown: boolean };
export type EditorLocation = { kind: 'catalogue' | 'manual' | 'review';
  latitude: number | null; longitude: number | null; zone: string; fold: number | null; provisional: boolean;
  place?: { id: string; name: string; region: string; country: string; latitude: number; longitude: number; zone: string };
  latitude_override?: number; longitude_override?: number; zone_override?: string | null };
export type Person = {
  id: string; name: string; active_chart_id: string | null;
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
  }} aria-labelledby="person-title">
    <form className="dialog-body" onSubmit={submit}>
      <div className="dialog-top"><h2 id="person-title">A space for someone new.</h2><button type="button" aria-label="Close new person form" onClick={() => dialog.current?.close()}>×</button></div>
      <p>Create the person, then enter birth details to generate their chart.</p>
      <div className="field"><label htmlFor="person-name">Name</label><input id="person-name" ref={nameInput} required maxLength={128} value={name} onChange={event => setName(event.target.value)} /></div>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="dialog-footer"><button type="button" onClick={() => dialog.current?.close()}>Cancel</button><button type="submit" className="primary" disabled={busy}>{busy ? 'Saving…' : 'Create person'}</button></div>
    </form>
  </dialog>;
}

export function PersonDetail({ workspace, person, refresh, startConversation, openConversation, onDeleted,
  initialEditorOpen = false, initialTab = 'overview', editorRequest = 0, childFocus = false, onReturn, returnLabel = 'workspace',
  discussSavedResult }: {
  workspace: Workspace; person: Person; refresh: () => Promise<void>;
  startConversation: () => void; openConversation: (id: string) => void;
  discussSavedResult: (result: SelectedResult, label: string) => void;
  onDeleted: () => void; initialEditorOpen?: boolean; initialTab?: 'overview' | 'charts'; editorRequest?: number;
  childFocus?: boolean; onReturn?: () => void; returnLabel?: string;
}) {
  const tabsId = useId();
  const [tab, setTab] = useState<'overview' | 'charts' | 'saved'>(initialEditorOpen ? 'charts' : initialTab);
  const [savedSection, setSavedSection] = useState<'insights' | 'later' | 'journal'>('insights');
  const [savedOpenRequest, setSavedOpenRequest] = useState(0);
  const [timingOpen, setTimingOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(initialEditorOpen);
  const [watchVersion, setWatchVersion] = useState(0);
  const [generated, setGenerated] = useState<{ result: Generation; draft: Draft } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([null, null, null]);
  const editorRef = useRef<HTMLDivElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const activeChart = (generated && generated.result.active_chart_id === generated.result.chart.id ? generated.result.chart : null) ||
    person.charts.find(chart => chart.id === person.active_chart_id);
  const hasActive = !!(person.active_chart_id || activeChart);
  const latestDraft = generated && generated.result.active_chart_id === generated.result.chart.id ? generated.draft : person.drafts[0]?.details;

  useEffect(() => {
    if (initialEditorOpen) {
      setTab('charts'); setEditorOpen(true);
      window.requestAnimationFrame(() => editorRef.current?.focus());
    }
  }, [initialEditorOpen, editorRequest]);

  function openEditor() {
    setTab('charts'); setEditorOpen(true);
    window.requestAnimationFrame(() => editorRef.current?.focus());
  }

  function switchTab(event: React.KeyboardEvent, index: number) {
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 :
      event.key === 'ArrowRight' ? (index + 1) % 3 :
      event.key === 'ArrowLeft' ? (index + 2) % 3 : null;
    if (next === null) return;
    event.preventDefault();
    setTab((['overview', 'charts', 'saved'] as const)[next]);
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
      <button ref={editButtonRef} type="button" className="profile-edit-action" onClick={openEditor} aria-controls={`${tabsId}-editor`} aria-expanded={editorOpen}>
        {hasActive ? 'Edit birth details' : 'Add birth details'}</button>
    </div><button type="button" className="primary profile-chat-action" onClick={startConversation}>Start conversation</button></div>
    <div className="profile-tabs" role="tablist" aria-label="Person sections">
      {(['overview', 'charts', 'saved'] as const).map((item, index) => <button key={item} type="button" role="tab"
        id={`${tabsId}-${item}-tab`} aria-controls={`${tabsId}-${item}-panel`} aria-selected={tab === item}
        tabIndex={tab === item ? 0 : -1} ref={element => { tabRefs.current[index] = element; }}
        onKeyDown={event => switchTab(event, index)} onClick={() => setTab(item)}>
        {item === 'overview' ? 'Overview' : item === 'charts' ? 'Charts' : 'Saved'}</button>)}
    </div>
    <section id={`${tabsId}-overview-panel`} role="tabpanel" aria-labelledby={`${tabsId}-overview-tab`} hidden={tab !== 'overview'} className="profile-panel">
      <p className="profile-group-label">Explore</p>
      <div className="profile-quiet-group">
        <button type="button" className="profile-quiet-row" onClick={() => hasActive ? setTab('charts') : openEditor()}>
          <span className="profile-row-icon" aria-hidden="true">☉</span><span><strong>{hasActive ? 'Birth chart' : 'First birth chart'}</strong>
            <small>{hasActive ? activeChart?.source_status !== 'current' ? 'Saved chart · source needs review' :
              latestDraft?.time_unknown ? 'Limited chart · birth time unknown' : 'Your current natal, placements and aspects' :
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
    <section id={`${tabsId}-charts-panel`} role="tabpanel" aria-labelledby={`${tabsId}-charts-tab`} hidden={tab !== 'charts'} className="profile-panel">
      <div className="profile-chart-heading"><div><h2>{activeChart?.source_status !== 'current' ? 'Saved birth chart' : 'Current birth chart'}</h2>
        <p>{activeChart ? 'Calculated from saved birth details. Earlier versions stay below.' :
          'No active generated natal. Nothing is guessed from a draft or an earlier chart.'}</p></div>
      </div>
      {activeChart ? <div className="profile-active-chart">{activeChart.result.natal ? <NatalChart chart={activeChart} allowMotion personLayout /> :
        <p>This generated chart has only supported partial/solar information. Birth time or houses were not inferred.</p>}</div> :
        <div className="profile-chart-empty"><p>{editorOpen ? 'Supply the birth details below to generate the first chart.' :
          'Choose Create first chart to supply birth details and generate a natal chart.'}</p>
          {!editorOpen && <button type="button" onClick={openEditor}>Create first chart</button>}</div>}
      <div id={`${tabsId}-editor`} ref={editorRef} tabIndex={-1} hidden={!editorOpen} className="profile-editor">
        <div className="profile-editor-heading"><h2>{hasActive ? 'Update current natal' : 'Create first chart'}</h2>
          <button type="button" onClick={() => { setEditorOpen(false); editButtonRef.current?.focus(); }}>Close editor</button></div>
        <BirthWorkflow person={person} workspace={workspace} refresh={refresh}
          onGenerated={(result, draft) => setGenerated({ result, draft })} compact discussChart={startConversation} />
      </div>
      <details className="detail-section chart-history"><summary>Earlier charts and birth details</summary>
        <p>Earlier versions stay here. They do not replace the current chart in a new conversation.</p>
        {person.drafts.length > 0 && <ul>{person.drafts.map((item, index) => <li key={item.revision}>Supplied details {index + 1} · {item.details.birth_date || 'Date not supplied'} · {item.details.time_unknown ? 'Time unknown' : item.details.birth_time || 'Time not supplied'} · {item.details.birthplace || 'Place not supplied'}</li>)}</ul>}
        {person.birth_records.length > 0 && <ul>{person.birth_records.map(item => <li key={item.id}>Recorded birth · {item.wall_time?.replace('T', ' ') || (item.earliest_utc && item.latest_utc ? `${item.earliest_utc} to ${item.latest_utc}` : 'Time unavailable')} · {item.zone_name}</li>)}</ul>}
        {person.charts.map((chart, index) => {
          const birth = person.birth_records.find(record => record.id === chart.birth_id);
          return <details key={chart.id} data-kat-chart-id={chart.id}><summary>{chart.id === person.active_chart_id ? 'Current natal' : 'Historical chart'} · {birth?.wall_time?.slice(0, 10) || birth?.earliest_utc?.slice(0, 10) || 'Birth date unavailable'} · Chart {index + 1}</summary>
            {chart.result.natal ? <NatalChart chart={chart} /> : <p>{chart.source_status !== 'current' ? `Source: ${chart.source_status}. ` : ''}A full natal wheel is unavailable for this saved chart. Its birth details are listed above.</p>}
          </details>;
        })}
      </details>
    </section>
    <section id={`${tabsId}-saved-panel`} role="tabpanel" aria-labelledby={`${tabsId}-saved-tab`}
      hidden={tab !== 'saved'} className="profile-panel">
      <div className="profile-saved-sections" aria-label="Saved sections">
        {([['insights', 'Insights'], ['later', 'Saved for later'], ['journal', 'Private journal']] as const).map(([key, label]) =>
          <button key={key} type="button" aria-pressed={savedSection === key} onClick={() => setSavedSection(key)}>{label}</button>)}
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
