import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';
import type { Person } from './people';
import type { Turn } from './turns';

type Insight = { id: string; conversation_id: string; source_turn_id: string; statement: string;
  epistemic_status: string; note: string; source_status: 'current' | 'historical'; created_at: string };
type InsightPage = { entries: Insight[]; next_offset: number | null };

export function SaveInsight({ turn, conversationId, people, workspace }: {
  turn: Turn; conversationId: string; people: Person[]; workspace: Workspace;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const personInput = useRef<HTMLSelectElement>(null);
  const requestId = useRef<string | null>(null);
  const original = useRef<HTMLTextAreaElement>(null);
  const [personId, setPersonId] = useState('');
  const [kind, setKind] = useState<'user' | 'assistant'>('user');
  const [quote, setQuote] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState('');
  const user = String(turn.events.find(event => event.kind === 'user')?.payload.content || '');
  const assistant = turn.events.filter(event => event.kind === 'assistant_chunk')
    .map(event => String(event.payload.content || '')).join('');
  const source = kind === 'user' ? user : assistant;

  function open() {
    setPersonId(people.find(person => turn.selected_people.some(selected => selected.person_id === person.id))?.id || people[0]?.id || '');
    setKind('user'); setQuote(''); setNote(''); setError(''); setAttempted(false);
    requestId.current = crypto.randomUUID();
    dialog.current?.showModal();
    personInput.current?.focus();
  }
  function selectPassage() {
    const field = original.current;
    if (!field) return;
    const selected = source.slice(field.selectionStart, field.selectionEnd).trim();
    if (!selected) { setError('Select the passage in the original text first.'); return; }
    if (new TextEncoder().encode(selected).length > 512) {
      setError('Choose a shorter passage (at most 512 bytes).'); return;
    }
    setQuote(selected); setError('');
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!requestId.current || !personId || !quote || busy) return;
    setBusy(true); setAttempted(true); setError('');
    try {
      await api(`people/${personId}/insights`, workspace.csrf, 'POST', {
        id: `insight-${requestId.current}`, conversation_id: conversationId,
        source_turn_id: turn.id, kind, quote, note,
      });
      dialog.current?.close();
    } catch {
      setError('Save was not confirmed. Retry this same passage, or check the person’s Insights before trying a new save.');
    } finally { setBusy(false); }
  }
  return <><button type="button" onClick={open} disabled={!people.length || turn.next_event_offset !== null}>
    Save passage</button>
    <dialog ref={dialog} aria-label="Save conversation passage" onClose={() => setError('')}>
      <form className="dialog-body insight-save" onSubmit={event => void save(event)}>
        <div className="dialog-top"><h2>Save a passage</h2><button type="button" aria-label="Close passage form" onClick={() => dialog.current?.close()}>×</button></div>
        <p>Choose exact wording from this archived message. Your note is personal context, not calculated chart evidence. The original discussion stays unchanged.</p>
        <label>For person<select ref={personInput} required value={personId} disabled={busy || attempted} onChange={event => setPersonId(event.target.value)}>
          {people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}
        </select></label>
        <label>From<select value={kind} disabled={busy || attempted} onChange={event => { setKind(event.target.value as 'user' | 'assistant'); setQuote(''); }}>
          <option value="user">Your original message</option>{assistant && <option value="assistant">Kat’s reply (not verified facts)</option>}
        </select></label>
        <label>Original archived wording<textarea ref={original} readOnly value={source} rows={6} /></label>
        <button type="button" disabled={busy || attempted} onClick={selectPassage}>Use selected text</button>
        {quote && <blockquote>{quote}</blockquote>}
        <label>Optional personal note<textarea value={note} disabled={busy || attempted} maxLength={512} onChange={event => setNote(event.target.value)} rows={3} /></label>
        {error && <p role="alert" className="error">{error}</p>}
        <div className="dialog-footer"><button type="button" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button>
          <button type="submit" className="primary" disabled={!quote || busy}>{busy ? 'Saving…' : 'Save for this person'}</button></div>
      </form>
    </dialog>
  </>;
}

export function InsightNotebook({ workspace, personId, active, openConversation }: {
  workspace: Workspace; personId: string; active: boolean; openConversation: (id: string) => void;
}) {
  const [entries, setEntries] = useState<Insight[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const actionId = useRef<string | null>(null);
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setError('');
    void api<InsightPage>(`people/${personId}/insights`).then(page => {
      if (!cancelled) { setEntries(page.entries); setNextOffset(page.next_offset); }
    }).catch(() => { if (!cancelled) setError('Insights could not be loaded. Return to this tab to retry.'); });
    return () => { cancelled = true; };
  }, [active, personId]);
  async function older() {
    if (nextOffset === null || busy) return;
    setBusy(true); setError('');
    try {
      const page = await api<InsightPage>(`people/${personId}/insights?offset=${nextOffset}`);
      setEntries(old => [...old, ...page.entries]); setNextOffset(page.next_offset);
    } catch { setError('Older insights could not be loaded. Retry when ready.'); }
    finally { setBusy(false); }
  }
  async function change(entry: Insight, action: 'edit' | 'remove') {
    if (busy) return;
    if (action === 'remove' && !window.confirm('Remove this passage from Insights? The original discussion and saved action history remain.')) return;
    actionId.current ||= `insight-action-${crypto.randomUUID()}`;
    setBusy(true); setError('');
    try {
      await api(`people/${personId}/insights/${entry.id}`, workspace.csrf, 'PATCH',
        { id: actionId.current, action, note: action === 'edit' ? note : '' });
      if (action === 'remove') {
        const page = await api<InsightPage>(`people/${personId}/insights`);
        setEntries(page.entries); setNextOffset(page.next_offset);
      } else {
        setEntries(old => old.map(item => item.id === entry.id ? { ...item, note } : item));
      }
      setEditing(null); actionId.current = null;
    } catch { setError('This change was not confirmed. Retry the exact same action or reopen Insights to check its state.'); }
    finally { setBusy(false); }
  }
  return <div className="insight-notebook">
    <h2>Saved insights</h2><p>Only passages you choose are kept here. Original messages and attribution remain in their discussion; historical sources are not current context.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {!entries.length && !error && <p>No saved passages for this person yet. Open a completed conversation and choose Save passage.</p>}
    {entries.map(entry => <article className="insight-entry" key={entry.id}>
      <p className="insight-source">{entry.epistemic_status === 'saved_assistant_passage' ? 'Kat’s wording · not verified facts' : 'Your original wording'} · {entry.source_status === 'current' ? 'Current source' : 'Historical source · excluded from current recall'}</p>
      <blockquote>{entry.statement}</blockquote>
      {entry.note && <p className="insight-note">Your note: {entry.note}</p>}
      <details className="insight-source"><summary>Source details · saved {new Date(entry.created_at).toLocaleDateString()}</summary>
        <p>Discussion {entry.conversation_id} · message {entry.source_turn_id}</p></details>
      <div className="insight-actions"><button type="button" onClick={() => openConversation(entry.conversation_id)}>Open original discussion</button>
        <button type="button" disabled={busy} onClick={() => { setEditing(entry.id); setNote(entry.note); actionId.current = null; }}>Edit note</button>
        <button type="button" disabled={busy} onClick={() => void change(entry, 'remove')}>Remove insight</button></div>
      {editing === entry.id && <div className="insight-edit"><label>Personal note<textarea value={note} maxLength={512} disabled={busy}
        onChange={event => { setNote(event.target.value); actionId.current = null; }} /></label>
        <button type="button" disabled={busy} onClick={() => void change(entry, 'edit')}>Save note</button>
        <button type="button" disabled={busy} onClick={() => { setEditing(null); actionId.current = null; }}>Cancel</button></div>}
    </article>)}
    {nextOffset !== null && <button type="button" disabled={busy} onClick={() => void older()}>Load older insights</button>}
  </div>;
}
