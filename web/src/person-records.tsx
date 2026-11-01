import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type Workspace } from './api';
import { useApplicationUtcDate } from './manual-chart-intent';
import type { SelectedResult } from './archive';

type Reminder = { wall_time: string; zone: string; fold: number | null; instant_utc: string };
type Watch = { id: string; result_id: string; event_index: number | null; note: string;
  reminder: Reminder | null; source_status: string; reminder_status: string; technique: string;
  window_utc: string[] | null; event: { instant_utc?: string; phase?: string } | null };
type Reflection = { id: string; kind: string; local_date: string; instant_utc: string | null;
  zone_name: string | null; linked_result_id: string | null; linked_source_status: string | null;
  text: string; attribution: string };
type Page<T> = { next_offset: number | null; items?: T[]; entries?: T[] };
const names: Record<string, string> = {
  solar_return: 'Solar return', lunar_return: 'Lunar return', planetary_return: 'Planetary return',
  mc_transit: 'Transit to natal MC', actual_lunations_eclipses: 'Lunation or eclipse',
  secondary_progression: 'Secondary progression', progressed_mc_contacts: 'Progressed MC contact',
  progressed_lunar_phases: 'Progressed lunar phase', true_solar_arc: 'Solar arc',
};

export function PersonRecords({ workspace, personId, onDiscuss, watchVersion }: {
  workspace: Workspace; personId: string; onDiscuss: (result: SelectedResult, label: string) => void;
  watchVersion: number;
}) {
  const clock = useApplicationUtcDate();
  const [watchOpen, setWatchOpen] = useState(false);
  const [journalOpen, setJournalOpen] = useState(false);
  const [watch, setWatch] = useState<Watch[]>([]);
  const [watchNext, setWatchNext] = useState<number | null>(null);
  const [journal, setJournal] = useState<Reflection[]>([]);
  const [journalNext, setJournalNext] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [kind, setKind] = useState<'date' | 'instant' | 'uncertain'>('date');
  const [day, setDay] = useState('');
  const [time, setTime] = useState('');
  const [zone, setZone] = useState(workspace.product.reporting_zone);
  const [fold, setFold] = useState<number | null>(null);
  const [linked, setLinked] = useState('');
  const journalAttempt = useRef<{ key: string; id: string } | null>(null);
  const editAttempt = useRef<{ key: string; id: string } | null>(null);
  const watchAttempt = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => { if (clock.today) setDay(value => value || clock.today!); }, [clock.today]);
  useEffect(() => { if (watchOpen) void loadWatch(); }, [watchVersion, watchOpen, personId]);
  useEffect(() => {
    if (journalOpen) { void loadJournal(); void loadWatch(); }
  }, [journalOpen, personId]);

  async function loadWatch(offset = 0) {
    try {
      const page = await api<Page<Watch>>(`people/${personId}/watchlist?offset=${offset}`);
      setWatch(old => offset ? [...old, ...(page.items || [])] : (page.items || []));
      setWatchNext(page.next_offset);
    } catch { setError('Saved items could not be opened. Retry by reopening this section.'); }
  }
  async function loadJournal(offset = 0) {
    try {
      const page = await api<Page<Reflection>>(`people/${personId}/journal?offset=${offset}`);
      setJournal(old => offset ? [...old, ...(page.entries || [])] : (page.entries || []));
      setJournalNext(page.next_offset);
    } catch { setError('Private notes could not be opened. Retry by reopening this section.'); }
  }

  async function changeWatch(item: Watch) {
    const nextNote = window.prompt('Your note (optional, up to 512 characters)', item.note);
    if (nextNote === null) return;
    const wantsReminder = window.confirm('Show this item as due in Kat on a future visit? Cancel keeps reminders off. No message arrives while Kat is closed.');
    let reminder: { wall_time: string; zone: string; fold: number | null } | null = null;
    if (wantsReminder) {
      const wall = window.prompt('Local reminder time (YYYY-MM-DDTHH:MM). Leave blank to keep it off.', item.reminder?.wall_time || '');
      if (wall === null) return;
      if (wall) {
        const location = window.prompt('IANA timezone for this local time', item.reminder?.zone || workspace.product.reporting_zone);
        if (location === null) return;
        const occurrence = window.prompt('If this local clock hour repeats: earlier, later or blank to check ambiguity',
          item.reminder?.fold === 0 ? 'earlier' : item.reminder?.fold === 1 ? 'later' : '');
        if (occurrence === null) return;
        if (!['', 'earlier', 'later'].includes(occurrence)) { setError('Choose earlier, later or leave the repeated-hour choice blank.'); return; }
        reminder = { wall_time: wall, zone: location,
          fold: occurrence === '' ? null : occurrence === 'earlier' ? 0 : 1 };
      }
    }
    const key = JSON.stringify({ item: item.id, nextNote, reminder });
    if (watchAttempt.current?.key !== key) watchAttempt.current = { key, id: `watch-edit-${crypto.randomUUID()}` };
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/watchlist/${item.id}`, workspace.csrf, 'PATCH', {
        id: watchAttempt.current.id, note: nextNote, reminder,
      });
      watchAttempt.current = null;
      await loadWatch();
    } catch { setError('Change not confirmed. Repeat with the same values to retry safely.'); }
    finally { setBusy(false); }
  }

  async function deleteRecord(kind: 'watchlist' | 'journal', id: string) {
    if (!window.confirm(kind === 'journal' ? 'Permanently remove this private reflection?' : 'Remove this saved item and its reminder?')) return;
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/${kind}/${id}`, workspace.csrf, 'DELETE');
      if (kind === 'journal') await loadJournal(); else await loadWatch();
    } catch { setError('Removal was not confirmed. Check the list before trying again.'); }
    finally { setBusy(false); }
  }

  async function addReflection(event: FormEvent) {
    event.preventDefault();
    const payload = { kind, local_date: day, wall_time: kind === 'instant' ? time : null,
      zone: kind === 'instant' ? zone : null, fold: kind === 'instant' ? fold : null,
      linked_result_id: linked || null, text: note };
    const key = JSON.stringify(payload);
    if (journalAttempt.current?.key !== key) journalAttempt.current = { key, id: `journal-${crypto.randomUUID()}` };
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/journal`, workspace.csrf, 'POST', { id: journalAttempt.current.id, ...payload });
      journalAttempt.current = null; setNote(''); setLinked('');
      await loadJournal();
    } catch { setError('The reflection was not confirmed. Correct the date/time if needed, or retry the same text without creating a second entry.'); }
    finally { setBusy(false); }
  }

  async function editReflection(item: Reflection) {
    const next = window.prompt('Edit your reflection', item.text);
    if (next === null || next === item.text) return;
    const key = JSON.stringify({ entry: item.id, text: next });
    if (editAttempt.current?.key !== key) editAttempt.current = { key, id: `journal-edit-${crypto.randomUUID()}` };
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/journal/${item.id}`, workspace.csrf, 'PATCH', { id: editAttempt.current.id, text: next });
      editAttempt.current = null;
      await loadJournal();
    } catch { setError('Edit was not confirmed. Check the saved text before trying again.'); }
    finally { setBusy(false); }
  }

  return <section className="person-records" aria-label="Saved timing and private reflections">
    <details className="detail-section profile-secondary" onToggle={event => setWatchOpen(event.currentTarget.open)}>
      <summary>Saved for later · in-app reminders</summary>
      {watchOpen && <><p>Reminders are off unless chosen per item. Due items appear here only when Kat is open; there are no external alerts.</p>
        {watch.length ? <ul>{watch.map(item => <li key={item.id}>
          <strong>{names[item.technique] || 'Saved result'}</strong>{item.event?.instant_utc && ` · ${item.event.instant_utc.slice(0, 10)} UTC`}
          {item.note && <p>{item.note}</p>}
          <p>{item.source_status === 'historical' ? 'Historical source. Review this saved calculation before relying on a reminder.' : 'Current source.'}
            {' '}{item.reminder_status === 'off' ? 'Reminder off.' : item.reminder_status === 'needs_review' ? 'Reminder needs review.' :
              item.reminder_status === 'due' ? 'Due in Kat now.' : `In-app reminder set for ${item.reminder?.wall_time} ${item.reminder?.zone}.`}</p>
          <button type="button" onClick={() => onDiscuss({ result_id: item.result_id, event_index: item.event_index },
            names[item.technique] || 'saved result')}>Discuss this result</button>
          <button type="button" disabled={busy} onClick={() => void changeWatch(item)}>Edit note or reminder</button>
          <button type="button" disabled={busy} onClick={() => void deleteRecord('watchlist', item.id)}>Remove</button>
        </li>)}</ul> : <p>No saved items yet. Choose Save for later from a dated result.</p>}
        {watchNext !== null && <button type="button" onClick={() => void loadWatch(watchNext)}>Load more saved items</button>}
      </>}
    </details>
    <details className="detail-section profile-secondary" onToggle={event => setJournalOpen(event.currentTarget.open)}>
      <summary>Private event journal</summary>
      {journalOpen && <><p>Optional self-reported reflections. Not sent to Kat's model, tools or automatic recall. A linked calculation does not establish why something happened.</p>
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
            <option value="">No link</option>{watch.map(item => <option key={item.id} value={item.result_id}>{names[item.technique] || 'Saved calculation'} · {item.event?.instant_utc?.slice(0, 10) || 'saved period'}</option>)}
          </select></label>
          <label className="journal-note">Your reflection <textarea required maxLength={4096} value={note} onChange={event => setNote(event.target.value)} /></label>
          <button type="submit" disabled={busy || !note.trim() || !day}>Save private reflection</button>
        </form>
        {journal.length ? <ul>{journal.map(item => <li key={item.id}>
          <strong>{item.local_date}{item.kind === 'uncertain' && ' · approximate day'}{item.kind === 'instant' && ` · ${item.instant_utc} (recorded instant)`}</strong>
          <p>{item.text}</p>{item.linked_result_id && <p>{item.linked_source_status === 'historical' ? 'Linked calculation is historical; your reflection remains yours.' : 'Linked saved calculation.'}</p>}
          <button type="button" disabled={busy} onClick={() => void editReflection(item)}>Edit text</button>
          <button type="button" disabled={busy} onClick={() => void deleteRecord('journal', item.id)}>Delete reflection</button>
        </li>)}</ul> : <p>No private reflections saved.</p>}
        {journalNext !== null && <button type="button" onClick={() => void loadJournal(journalNext)}>Load more reflections</button>}
      </>}
    </details>
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
