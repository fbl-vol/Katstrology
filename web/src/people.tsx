import React, { useEffect, useId, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from './api';
import { BirthWorkflow, type Generation } from './birth-workflow';
import { NatalChart, type Chart } from './natal';
import { InsightNotebook } from './insights';
import { PersonTiming } from './person-timing';

export type Draft = { birth_date: string; birth_time: string; birthplace: string; time_unknown: boolean };
export type Person = {
  id: string; name: string; active_chart_id: string | null;
  drafts: { revision: number; details: Draft }[];
  birth_records: { id: string; wall_time: string | null; zone_name: string; earliest_utc: string | null; latest_utc: string | null }[];
  charts: Chart[];
  attachments: { id: string; filename: string; byte_count: number; media_type: string }[];
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
  initialEditorOpen = false, initialTab = 'basic', editorRequest = 0, childFocus = false, onReturn, returnLabel = 'workspace' }: {
  workspace: Workspace; person: Person; refresh: () => Promise<void>;
  startConversation: () => void; openConversation: (id: string) => void;
  onDeleted: () => void; initialEditorOpen?: boolean; initialTab?: 'basic' | 'charts'; editorRequest?: number;
  childFocus?: boolean; onReturn?: () => void; returnLabel?: string;
}) {
  const tabsId = useId();
  const [tab, setTab] = useState<'basic' | 'charts' | 'insights'>(initialEditorOpen ? 'charts' : initialTab);
  const [editorOpen, setEditorOpen] = useState(initialEditorOpen);
  const [generated, setGenerated] = useState<{ result: Generation; draft: Draft } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [fileOutcome, setFileOutcome] = useState<{
    id: string; message: string; conversations?: { id: string; title: string }[]; more?: boolean;
  } | null>(null);
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
    setTab((['basic', 'charts', 'insights'] as const)[next]);
    tabRefs.current[next]?.focus();
  }

  async function deleteFile(id: string) {
    setBusy(true); setFileOutcome(null);
    try {
      await api(`people/${person.id}/files/${id}`, workspace.csrf, 'DELETE');
      setFileOutcome({ id, message: 'Deletion accepted; refreshing the file list…' });
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'attachment_in_use') {
        setFileOutcome({ id, message: 'Not deleted: an archived turn still references this file. The original file and conversation remain. Inspect where it was used below.',
          conversations: cause.details.conversations, more: cause.details.more });
      } else {
        setFileOutcome({ id, message: 'File deletion was not confirmed. The file may still be present; check the archive before retrying.' });
      }
      setBusy(false);
      return;
    }
    try { await refresh(); }
    catch { setFileOutcome({ id, message: 'Deletion was accepted, but the file list could not refresh. Reopen this person to check the archive.' }); }
    finally { setBusy(false); }
  }

  return <section className="person-page" aria-labelledby="person-heading">
    {onReturn && <button type="button" className="profile-return" onClick={onReturn}>← Return to {returnLabel}</button>}
    {childFocus && <p className="profile-child-note">Child’s natal uses the same numerical natal chart. It adds no child-status field, diagnosis, paid interpretation or deterministic personality label. Any later discussion is a separate, explicit choice.</p>}
    <div className="profile-header"><div><span className="eyebrow">PERSON · LOCAL WORKSPACE</span>
      <h1 id="person-heading" tabIndex={-1}>{person.name}</h1>
      <p className="profile-summary">{latestDraft ? <>{latestDraft.birth_date || 'Date not supplied'} · {latestDraft.time_unknown ? 'Birth time unknown' : latestDraft.birth_time || 'Time not supplied'} · {latestDraft.birthplace || 'Place not supplied'} <small>(latest user-supplied details)</small></> :
        'Birth details have not been supplied. No time or place is inferred.'}</p>
      {activeChart?.source_status !== 'current' && activeChart && <p className="profile-caution">The active chart’s source is {activeChart.source_status}; inspect its original details before relying on it.</p>}
    </div><button ref={editButtonRef} type="button" className="profile-edit-action" onClick={openEditor} aria-controls={`${tabsId}-editor`} aria-expanded={editorOpen}>
      {hasActive ? 'Edit current chart' : 'Create first chart'}</button></div>
    <div className="profile-tabs" role="tablist" aria-label="Person sections">
      {(['basic', 'charts', 'insights'] as const).map((item, index) => <button key={item} type="button" role="tab"
        id={`${tabsId}-${item}-tab`} aria-controls={`${tabsId}-${item}-panel`} aria-selected={tab === item}
        tabIndex={tab === item ? 0 : -1} ref={element => { tabRefs.current[index] = element; }}
        onKeyDown={event => switchTab(event, index)} onClick={() => setTab(item)}>
        {item === 'basic' ? 'Basic info' : item === 'charts' ? 'Charts' : 'Insights'}</button>)}
    </div>
    <section id={`${tabsId}-basic-panel`} role="tabpanel" aria-labelledby={`${tabsId}-basic-tab`} hidden={tab !== 'basic'} className="profile-panel">
      <h2>Basic info</h2>
      {latestDraft ? <dl className="profile-facts"><div><dt>Birth date</dt><dd>{latestDraft.birth_date || 'Not supplied'}</dd></div>
        <div><dt>Birth time</dt><dd>{latestDraft.time_unknown ? 'Unknown — no Ascendant or houses are inferred' : latestDraft.birth_time || 'Not supplied'}</dd></div>
        <div><dt>Birthplace</dt><dd>{latestDraft.birthplace || 'Not supplied'}</dd></div></dl> :
        <p>No birth date, time or place has been supplied. You can still start a conversation without chart evidence.</p>}
      <details className="detail-section profile-secondary"><summary>Where am I now? · saved timing</summary>
        {tab === 'basic' && <PersonTiming workspace={workspace} person={person} />}
      </details>
      <section className="conversation-entry" aria-label="Conversation about this person">
        <p>{hasActive ? 'A new message uses the current generated natal, not an older version.' :
          'No generated natal is active; a conversation can still be general.'}</p>
        <button type="button" className="quiet-action" aria-label={`New conversation about ${person.name}`}
          onClick={startConversation}>Start conversation</button>
      </section>
      <details className="profile-secondary"><summary>Remove this person</summary>
        <p>Delete related conversations first. Removal is journaled; earlier external exports cannot be recalled.</p>
        <button type="button" disabled={busy} onClick={() => {
          if (!window.confirm(`Delete ${person.name} and their local chart versions and files? Related conversations must already be removed.`)) return;
          setBusy(true); setError('');
          void api(`people/${person.id}`, workspace.csrf, 'DELETE')
            .then(onDeleted)
            .catch(() => setError('Person deletion was blocked or unavailable. Delete related conversations first; the original records remain.'))
            .finally(() => setBusy(false));
        }}>Delete this person</button>
      </details>
    </section>
    <section id={`${tabsId}-charts-panel`} role="tabpanel" aria-labelledby={`${tabsId}-charts-tab`} hidden={tab !== 'charts'} className="profile-panel">
      <div className="profile-chart-heading"><div><h2>Current natal</h2>
        <p>{activeChart ? 'Current generated natal. Earlier charts stay in History.' :
          'No active generated natal. Nothing is guessed from a draft, an old chart or a file.'}</p></div>
        {activeChart && <button type="button" className="quiet-action" onClick={startConversation}>Discuss current natal</button>}
      </div>
      {activeChart ? <div className="profile-active-chart">{activeChart.result.natal ? <NatalChart chart={activeChart} /> :
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
      <details className="detail-section profile-secondary" aria-label="Chart references"><summary>Historical chart files · {person.attachments.length}</summary>
        <p>Saved files remain readable but are not used for new messages. No new uploads are accepted; an archived turn protects its referenced file from deletion.</p>
        {person.attachments.length ? <ul>{person.attachments.map(item => <li key={item.id}>{item.filename} · {item.byte_count} bytes <a href={`/api/people/${person.id}/files/${item.id}`} download>Download</a> <button type="button" disabled={busy} onClick={() => void deleteFile(item.id)}>Delete</button>
          {fileOutcome?.id === item.id && <div className="file-outcome" role="status"><p>{fileOutcome.message}</p>
            {!!fileOutcome.conversations?.length && <ul>{fileOutcome.conversations.map(thread => <li key={thread.id}>
              <button type="button" onClick={() => openConversation(thread.id)}>Open conversation: {thread.title || thread.id}</button>
            </li>)}</ul>}
            {fileOutcome.more && <p>Additional conversations also reference this file. No deletion was performed.</p>}
          </div>}
        </li>)}</ul> : <p>No chart files attached.</p>}
      </details>
    </section>
    <section id={`${tabsId}-insights-panel`} role="tabpanel" aria-labelledby={`${tabsId}-insights-tab`}
      hidden={tab !== 'insights'} className="profile-panel">
      <InsightNotebook workspace={workspace} personId={person.id} active={tab === 'insights'} openConversation={openConversation} />
    </section>
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
