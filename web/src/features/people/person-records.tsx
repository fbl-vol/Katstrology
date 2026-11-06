import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type Workspace } from '../../shared/api';
import { useApplicationUtcDate } from '../charts/manual-chart-intent';
import type { SelectedResult } from '../conversation/archive';

type Reminder = { wall_time: string; zone: string; fold: number | null; instant_utc: string };
type Watch = { id: string; result_id: string; event_index: number | null; note: string;
  reminder: Reminder | null; source_status: string; reminder_status: string; technique: string;
  window_utc: string[] | null; event: { instant_utc?: string; maximum_utc?: string;
    effective_utc?: string; phase?: string } | null };
type Reflection = { id: string; kind: string; local_date: string; instant_utc: string | null;
  zone_name: string | null; linked_result_id: string | null; linked_source_status: string | null;
  text: string; attribution: string };
type Page<T> = { next_offset: number | null; items?: T[]; entries?: T[] };
type WatchDraft = { id: string; note: string; enabled: boolean; wall: string; zone: string;
  fold: number | null; showFold: boolean };
type JournalDraft = { id: string; text: string };
const names: Record<string, string> = {
  solar_return: 'Solar return', lunar_return: 'Lunar return', planetary_return: 'Planetary return',
  mc_transit: 'Transit to natal MC', actual_lunations_eclipses: 'Lunation or eclipse',
  secondary_progression: 'Secondary progression', progressed_mc_contacts: 'Progressed MC contact',
  progressed_lunar_phases: 'Progressed lunar phase', true_solar_arc: 'Solar arc',
};

export function PersonRecords({ workspace, personId, onDiscuss, watchVersion, section, openRequest }: {
  workspace: Workspace; personId: string; onDiscuss: (result: SelectedResult, label: string) => void;
  watchVersion: number; section: 'insights' | 'later' | 'journal'; openRequest: number;
}) {
  const clock = useApplicationUtcDate();
  const [watchOpen, setWatchOpen] = useState(false);
  const [journalOpen, setJournalOpen] = useState(false);
  const watchDetails = useRef<HTMLDetailsElement>(null);
  const journalDetails = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (!openRequest) return;
    const selected = section === 'later' ? watchDetails.current : section === 'journal' ? journalDetails.current : null;
    if (selected) selected.open = true;
  }, [openRequest]);
  const [watch, setWatch] = useState<Watch[]>([]);
  const [watchNext, setWatchNext] = useState<number | null>(null);
  const [journal, setJournal] = useState<Reflection[]>([]);
  const [journalNext, setJournalNext] = useState<number | null>(null);
  const [watchState, setWatchState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [journalState, setJournalState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const watchRead = useRef(0);
  const watchDemand = useRef({ version: watchVersion, watchOpen, journalOpen });
  const journalRead = useRef(0);
  const watchPage = useRef<{ read: number; next: number | null } | null>(null);
  const journalPage = useRef<{ read: number; next: number | null } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [kind, setKind] = useState<'date' | 'instant' | 'uncertain'>('date');
  const [day, setDay] = useState('');
  const [time, setTime] = useState('');
  const [zone, setZone] = useState(workspace.product.reporting_zone);
  const [fold, setFold] = useState<number | null>(null);
  const [linked, setLinked] = useState('');
  const [watchDraft, setWatchDraft] = useState<WatchDraft | null>(null);
  const [journalDraft, setJournalDraft] = useState<JournalDraft | null>(null);
  const journalAttempt = useRef<{ key: string; id: string } | null>(null);
  const editAttempt = useRef<{ key: string; id: string } | null>(null);
  const watchAttempt = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => { if (clock.today) setDay(value => value || clock.today!); }, [clock.today]);
  useEffect(() => {
    const previous = watchDemand.current;
    const changed = previous.version !== watchVersion;
    const openedWatch = watchOpen && !previous.watchOpen;
    const openedJournal = journalOpen && !previous.journalOpen;
    watchDemand.current = { version: watchVersion, watchOpen, journalOpen };
    if (changed) {
      // A save invalidates even an in-flight read. Do not fetch while both
      // sections are closed; the first opened section will request fresh links.
      watchRead.current++; watchPage.current = null; setWatchNext(null);
      setWatchState('idle');
    }
    if ((changed && (watchOpen || journalOpen)) ||
        (openedWatch && watchState !== 'loading') ||
        (openedJournal && watchState !== 'ready' && watchState !== 'loading')) void loadWatch();
  }, [watchVersion, watchOpen, journalOpen, personId]);
  useEffect(() => () => {
    watchRead.current++; journalRead.current++;
    watchPage.current = null; journalPage.current = null;
  }, [workspace, personId]);
  useEffect(() => { if (journalOpen) void loadJournal(); }, [journalOpen, personId]);

  async function loadWatch(offset = 0) {
    // A continuation belongs only to the last accepted page, never a pending
    // replacement or a mutation's pre-write cursor (including a stale click).
    if (offset && (watchPage.current?.read !== watchRead.current || watchPage.current.next !== offset)) return;
    watchPage.current = null; setWatchNext(null);
    const read = ++watchRead.current;
    setWatchState('loading');
    try {
      const page = await api<Page<Watch>>(`people/${personId}/watchlist?offset=${offset}`);
      if (read !== watchRead.current) return;
      setWatch(old => offset ? [...old, ...(page.items || [])] : (page.items || []));
      setWatchNext(page.next_offset);
      watchPage.current = { read, next: page.next_offset };
      setWatchState('ready');
    } catch { if (read === watchRead.current) setWatchState('error'); }
  }
  async function loadJournal(offset = 0) {
    if (offset && (journalPage.current?.read !== journalRead.current || journalPage.current.next !== offset)) return;
    journalPage.current = null; setJournalNext(null);
    const read = ++journalRead.current;
    setJournalState('loading');
    try {
      const page = await api<Page<Reflection>>(`people/${personId}/journal?offset=${offset}`);
      if (read !== journalRead.current) return;
      setJournal(old => offset ? [...old, ...(page.entries || [])] : (page.entries || []));
      setJournalNext(page.next_offset);
      journalPage.current = { read, next: page.next_offset };
      setJournalState('ready');
    } catch { if (read === journalRead.current) setJournalState('error'); }
  }

  async function changeWatch(event: FormEvent) {
    event.preventDefault();
    if (!watchDraft) return;
    const reminder = watchDraft.enabled ? {
      wall_time: watchDraft.wall, zone: watchDraft.zone, fold: watchDraft.fold,
    } : null;
    const key = JSON.stringify({ item: watchDraft.id, note: watchDraft.note, reminder });
    if (watchAttempt.current?.key !== key) watchAttempt.current = { key, id: `watch-edit-${crypto.randomUUID()}` };
    watchRead.current++; watchPage.current = null; setWatchNext(null); setWatchState('loading');
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/watchlist/${watchDraft.id}`, workspace.csrf, 'PATCH', {
        id: watchAttempt.current.id, note: watchDraft.note, reminder,
      });
      watchAttempt.current = null;
      await loadWatch();
      setWatchDraft(null);
    } catch {
      setWatchState('error');
      setError('Change not confirmed. Check the local time and timezone; if the hour repeats, choose earlier or later. Retry with the same values safely.');
      setWatchDraft(draft => draft ? { ...draft, showFold: true } : draft);
    } finally { setBusy(false); }
  }

  async function deleteRecord(kind: 'watchlist' | 'journal', id: string) {
    if (!window.confirm(kind === 'journal' ? 'Permanently remove this private reflection?' : 'Remove this saved item and its reminder?')) return;
    if (kind === 'journal') {
      journalRead.current++; journalPage.current = null; setJournalNext(null); setJournalState('loading');
    } else {
      watchRead.current++; watchPage.current = null; setWatchNext(null); setWatchState('loading');
    }
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/${kind}/${id}`, workspace.csrf, 'DELETE');
      if (kind === 'journal') await loadJournal(); else await loadWatch();
    } catch {
      if (kind === 'journal') setJournalState('error'); else setWatchState('error');
      setError('Removal was not confirmed. Check the list before trying again.');
    }
    finally { setBusy(false); }
  }

  async function addReflection(event: FormEvent) {
    event.preventDefault();
    const payload = { kind, local_date: day, wall_time: kind === 'instant' ? time : null,
      zone: kind === 'instant' ? zone : null, fold: kind === 'instant' ? fold : null,
      linked_result_id: linked || null, text: note };
    const key = JSON.stringify(payload);
    if (journalAttempt.current?.key !== key) journalAttempt.current = { key, id: `journal-${crypto.randomUUID()}` };
    journalRead.current++; journalPage.current = null; setJournalNext(null); setJournalState('loading');
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/journal`, workspace.csrf, 'POST', { id: journalAttempt.current.id, ...payload });
      journalAttempt.current = null; setNote(''); setLinked('');
      await loadJournal();
    } catch {
      setJournalState('error');
      setError('The reflection was not confirmed. Correct the date/time if needed, or retry the same text without creating a second entry.');
    }
    finally { setBusy(false); }
  }

  async function editReflection(event: FormEvent) {
    event.preventDefault();
    if (!journalDraft) return;
    const key = JSON.stringify({ entry: journalDraft.id, text: journalDraft.text });
    if (editAttempt.current?.key !== key) editAttempt.current = { key, id: `journal-edit-${crypto.randomUUID()}` };
    journalRead.current++; journalPage.current = null; setJournalNext(null); setJournalState('loading');
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/journal/${journalDraft.id}`, workspace.csrf, 'PATCH', {
        id: editAttempt.current.id, text: journalDraft.text,
      });
      editAttempt.current = null;
      await loadJournal();
      setJournalDraft(null);
    } catch {
      setJournalState('error');
      setError('Edit was not confirmed. Check the saved text before trying again.');
    }
    finally { setBusy(false); }
  }

  return <section className="person-records" aria-label="Saved timing and private reflections" hidden={section === 'insights'}>
    <details ref={watchDetails} hidden={section !== 'later'} className="detail-section profile-secondary" onToggle={event => setWatchOpen(event.currentTarget.open)}>
      <summary>Saved for later · in-app reminders</summary>
      {watchOpen && <><p>Reminders are off unless chosen per item. Due items appear here only when Kat is open; there are no external alerts.</p>
        {watchState === 'loading' && <p role="status">Opening saved items…</p>}
        {watchState === 'error' && <p role="alert">Saved items could not be refreshed. <button type="button" onClick={() => void loadWatch()}>Try again</button></p>}
        {watch.length ? <ul>{watch.map(item => <li key={item.id}>
          <strong>{names[item.technique] || 'Saved result'}</strong>{(item.event?.maximum_utc || item.event?.instant_utc || item.event?.effective_utc) &&
            ` · ${(item.event?.maximum_utc || item.event?.instant_utc || item.event?.effective_utc)?.slice(0, 10)} UTC`}
          {item.note && <p>{item.note}</p>}
          <p>{item.source_status === 'historical' ? 'Historical source. Review this saved calculation before relying on a reminder.' : 'Current source.'}
            {' '}{item.reminder_status === 'off' ? 'Reminder off.' : item.reminder_status === 'needs_review' ? 'Reminder needs review.' :
              item.reminder_status === 'due' ? 'Due in Kat now.' : `In-app reminder set for ${item.reminder?.wall_time} ${item.reminder?.zone}.`}</p>
          <button type="button" onClick={() => onDiscuss({ result_id: item.result_id, event_index: item.event_index },
            names[item.technique] || 'saved result')}>Discuss this result</button>
          <button type="button" disabled={busy} onClick={() => {
            setError(''); setWatchDraft({ id: item.id, note: item.note,
              enabled: !!item.reminder, wall: item.reminder?.wall_time || '',
              zone: item.reminder?.zone || workspace.product.reporting_zone,
              fold: item.reminder?.fold ?? null, showFold: item.reminder?.fold != null });
          }}>Edit note or reminder</button>
          <button type="button" disabled={busy} onClick={() => void deleteRecord('watchlist', item.id)}>Remove</button>
          {watchDraft?.id === item.id && <form className="journal-form" aria-label="Edit saved item" onSubmit={event => void changeWatch(event)}>
            <label className="journal-note">Private note (optional) <textarea autoFocus maxLength={512} value={watchDraft.note}
              onChange={event => setWatchDraft({ ...watchDraft, note: event.target.value })} /></label>
            <label className="journal-note reminder-opt-in"><input type="checkbox" checked={watchDraft.enabled}
              onChange={event => setWatchDraft({ ...watchDraft, enabled: event.target.checked })} />
              Remind me in Kat when open</label>
            {watchDraft.enabled && <><p className="journal-note">No message is sent when Kat is closed. Your source must still be reviewed if it becomes historical.</p>
              <label>Local reminder time <input type="datetime-local" required value={watchDraft.wall}
                onChange={event => setWatchDraft({ ...watchDraft, wall: event.target.value })} /></label>
              <label>Timezone (IANA) <input required value={watchDraft.zone}
                onChange={event => setWatchDraft({ ...watchDraft, zone: event.target.value })} /></label>
              {watchDraft.showFold ? <label>Repeated clock hour <select value={watchDraft.fold ?? ''}
                onChange={event => setWatchDraft({ ...watchDraft,
                  fold: event.target.value === '' ? null : Number(event.target.value) })}>
                <option value="">Check for ambiguity</option><option value="0">Earlier occurrence</option>
                <option value="1">Later occurrence</option></select></label> :
                <button type="button" onClick={() => setWatchDraft({ ...watchDraft, showFold: true })}>Choose a repeated hour</button>}</>}
            <div className="journal-form-actions"><button type="button" disabled={busy} onClick={() => { setWatchDraft(null); setError(''); }}>Cancel</button>
              <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save item'}</button></div>
          </form>}
        </li>)}</ul> : watchState === 'ready' && <p>No saved items yet. Choose Save for later from a dated result.</p>}
        {watchNext !== null && <button type="button" disabled={busy || watchState !== 'ready'}
          onClick={() => void loadWatch(watchNext)}>Load more saved items</button>}
      </>}
    </details>
    <details ref={journalDetails} hidden={section !== 'journal'} className="detail-section profile-secondary" onToggle={event => setJournalOpen(event.currentTarget.open)}>
      <summary>Private event journal</summary>
      {journalOpen && <><p>Optional self-reported reflections. Not sent to Kat's model, tools or automatic recall. A linked calculation does not establish why something happened.</p>
        {journalState === 'loading' && <p role="status">Opening private reflections…</p>}
        {journalState === 'error' && <p role="alert">Private reflections could not be refreshed. <button type="button" onClick={() => void loadJournal()}>Try again</button></p>}
        <form className="journal-form" onSubmit={event => void addReflection(event)}>
          <label>Date <input type="date" required value={day} onChange={event => setDay(event.target.value)} /></label>
          <label>Date certainty <select value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
            <option value="date">Day only</option><option value="uncertain">Approximate day</option><option value="instant">Exact local time</option>
          </select></label>
          {kind === 'instant' && <><label>Local time <input type="datetime-local" required value={time} onChange={event => setTime(event.target.value)} /></label>
            <label>Timezone (IANA) <input required value={zone} onChange={event => setZone(event.target.value)} /></label>
            <label>Repeated hour <select value={fold === null ? '' : String(fold)} onChange={event => setFold(event.target.value ? Number(event.target.value) : null)}>
              <option value="">Check for ambiguity</option><option value="0">Earlier occurrence</option><option value="1">Later occurrence</option>
            </select></label></>}
          <label>Link a saved item (optional) <select value={linked} onChange={event => setLinked(event.target.value)}>
            <option value="">No link</option>{watch.map(item => <option key={item.id} value={item.result_id}>{names[item.technique] || 'Saved calculation'} · {(item.event?.maximum_utc || item.event?.instant_utc || item.event?.effective_utc)?.slice(0, 10) || 'saved period'}</option>)}
          </select></label>
          <label className="journal-note">Your reflection <textarea required maxLength={4096} value={note} onChange={event => setNote(event.target.value)} /></label>
          <button type="submit" disabled={busy || !note.trim() || !day}>Save private reflection</button>
        </form>
        {journal.length ? <ul>{journal.map(item => <li key={item.id}>
          <strong>{item.local_date}{item.kind === 'uncertain' && ' · approximate day'}{item.kind === 'instant' && ` · ${item.instant_utc} (recorded instant)`}</strong>
          <p>{item.text}</p>{item.linked_result_id && <p>{item.linked_source_status === 'historical' ? 'Linked calculation is historical; your reflection remains yours.' : 'Linked saved calculation.'}</p>}
          <button type="button" disabled={busy} onClick={() => { setError(''); setJournalDraft({ id: item.id, text: item.text }); }}>Edit text</button>
          <button type="button" disabled={busy} onClick={() => void deleteRecord('journal', item.id)}>Delete reflection</button>
          {journalDraft?.id === item.id && <form className="journal-form" aria-label="Edit private reflection" onSubmit={event => void editReflection(event)}>
            <label className="journal-note">Your reflection <textarea autoFocus required maxLength={4096} value={journalDraft.text}
              onChange={event => setJournalDraft({ ...journalDraft, text: event.target.value })} /></label>
            <div className="journal-form-actions"><button type="button" disabled={busy} onClick={() => { setJournalDraft(null); setError(''); }}>Cancel</button>
              <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save edit'}</button></div>
          </form>}
        </li>)}</ul> : journalState === 'ready' && <p>No private reflections saved.</p>}
        {journalNext !== null && <button type="button" disabled={busy || journalState !== 'ready'}
          onClick={() => void loadJournal(journalNext)}>Load more reflections</button>}
      </>}
    </details>
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
