import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type Workspace } from '../../shared/api';

const groups = {
  coming_up: 'Coming up', life_now: 'Life now', past_moments: 'Past moments',
  interests: 'Interests', goals: 'Goals', astrology_knowledge: 'Astrology knowledge',
  guidance_preferences: 'Guidance preferences',
};
type Group = keyof typeof groups;
type Content = { group: Group; title: string; notes: string; state: string | null;
  date: { text: string; precision: string; start: string | null; end: string | null } };
type Entry = { id: string; version: number; content: Content;
  source: { kind: string; statement?: string }; updated_at: string };
type Page = { entries: Entry[]; counts: Partial<Record<Group, number>>; next_offset: number | null };
type Draft = { id: string; version: number; content: Content; source?: Entry['source'] };
const life: Group[] = ['coming_up', 'life_now', 'past_moments'];
const learning: Group[] = ['interests', 'goals', 'astrology_knowledge', 'guidance_preferences'];

export type ContextMemory = { expanded?: Group | null; query?: string; draft?: Draft | null;
  attempt?: { key: string; operation: string } | null };

export function PersonalContextPane({ workspace, personId, active, memory }: {
  workspace: Workspace; personId: string; active: boolean; memory: ContextMemory;
}) {
  const [summary, setSummary] = useState<Page | null>(null);
  const [expanded, setExpanded] = useState<Group | null>(memory.expanded ?? null);
  const [query, setQuery] = useState(memory.query ?? '');
  const [page, setPage] = useState<Page | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [draft, setDraft] = useState<Draft | null>(memory.draft ?? null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const read = useRef(0);
  const attempt = useRef<{ key: string; operation: string } | null>(memory.attempt ?? null);
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useRef<HTMLInputElement>(null);
  const id = useId();
  const endpoint = `people/${personId}/context`;
  // Workspace-owned memory survives navigation, but never a logout or account switch.
  memory.expanded = expanded; memory.query = query; memory.draft = draft;
  memory.attempt = attempt.current;

  useEffect(() => {
    if (active) void load();
    return () => { read.current++; };
  }, [active, expanded, query, personId]);
  useEffect(() => {
    if (active && draft && !dialog.current?.open) { dialog.current?.showModal(); title.current?.focus(); }
    if ((!active || !draft) && dialog.current?.open) dialog.current.close();
  }, [active, !!draft]);

  async function load(offset = 0) {
    const request = ++read.current;
    setState('loading');
    if (expanded) setPage(old => old ? { ...old, next_offset: null } : old);
    try {
      // Search text is private request content, not URL/access-log material.
      const result = await api<Page>(`${endpoint}/search`, workspace.csrf, 'POST', {
        group: expanded, query, offset,
      });
      if (read.current !== request) return;
      if (expanded) setPage(old => offset && old ? { ...result, entries: [...old.entries, ...result.entries] } : result);
      else setSummary(result);
      setState('ready');
    } catch { if (read.current === request) setState('error'); }
  }

  function open(group: Group, entry?: Entry) {
    setError(''); attempt.current = null;
    setDraft(entry ? { ...entry, content: structuredClone(entry.content) } : {
      id: crypto.randomUUID(), version: 0,
      content: { group, title: '', notes: '', state: group === 'coming_up' ? 'tentative' : null,
        date: { text: '', precision: 'unknown', start: null, end: null } },
    });
  }
  function change(update: Partial<Content>) {
    setDraft(old => old ? { ...old, content: { ...old.content, ...update } } : old);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    const payload = { id: draft.id, expected_version: draft.version, content: draft.content };
    const key = JSON.stringify(payload);
    if (attempt.current?.key !== key) attempt.current = { key, operation: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      await api(endpoint, workspace.csrf, 'POST', { ...payload, operation_id: attempt.current.operation });
      setDraft(null); attempt.current = null; setNotice('Entry saved.');
      await load();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 409 ?
        'This entry changed or was removed. Your draft is still here. Close it and reopen the current entry before saving a new edit.' :
        'Save was not confirmed. Check the fields and retry the same values safely. Your draft is still here.');
    } finally { setBusy(false); }
  }
  async function remove() {
    if (!draft || busy || !window.confirm('Remove this context entry? Original conversations, archived answers and information already sent to a provider remain.')) return;
    setBusy(true); setError('');
    try {
      await api(`${endpoint}/${draft.id}`, workspace.csrf, 'DELETE', { expected_version: draft.version });
      setDraft(null); setNotice('Entry removed from personal context.'); await load();
    } catch { setError('Removal was not confirmed. The entry may have changed. Close and reopen it to check; your draft is retained.'); }
    finally { setBusy(false); }
  }
  const current = expanded ? page : summary;
  function collection(keys: Group[], label: string) {
    return <section className="context-collection" aria-label={label}>
      <div className="profile-editor-heading"><h2>{label}</h2><button type="button" onClick={() => open(expanded ?? keys[0])}>Add</button></div>
      {keys.map(group => {
        if (expanded && expanded !== group) return null;
        const entries = current?.entries.filter(entry => entry.content.group === group) || [];
        const count = current?.counts[group] || 0;
        if (!expanded && !count) return null;
        return <section key={group} className="context-group" aria-label={groups[group]}>
          <h3>{groups[group]}</h3>
          {entries.map(entry => <button type="button" key={entry.id} className="profile-quiet-row context-row" onClick={() => open(group, entry)}>
            <span><strong>{entry.content.title}</strong>
              {(entry.content.date.text || entry.content.date.start) && <small>{entry.content.date.text || entry.content.date.start}</small>}
              {entry.content.notes && <small>{entry.content.notes}</small>}</span><span aria-hidden="true">›</span>
          </button>)}
          {state === 'ready' && !count && <p className="muted">{query ? 'No matching entries.' : 'Nothing added yet.'}</p>}
          {!expanded && count > 2 && <button type="button" onClick={() => { setPage(null); setExpanded(group); }}>View all ({count}, {count - 2} more)</button>}
        </section>;
      })}
      {state === 'ready' && !expanded && !keys.some(group => current?.counts[group]) && <p className="muted">{query ? 'No matching entries.' : 'Nothing here yet. Add what matters to you.'}</p>}
    </section>;
  }
  return <div className="personal-context">
    <p>Details you choose to keep for more relevant conversations. No birth chart or chat connection is needed to edit them.</p>
    <label className="field">Search context<input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
    {expanded && <button type="button" onClick={() => { setExpanded(null); setPage(null); }}>Show less</button>}
    {state === 'loading' && <p role="status">Opening context…</p>}
    {state === 'error' && <p role="alert">Context could not be refreshed. This is not an empty collection. <button type="button" onClick={() => void load()}>Try again</button></p>}
    {notice && <p role="status">{notice}</p>}
    {(!expanded || life.includes(expanded)) && collection(life, 'Life & plans')}
    {(!expanded || learning.includes(expanded)) && collection(learning, 'Interests & learning')}
    {expanded && page?.next_offset != null && <button type="button" disabled={state === 'loading'} onClick={() => void load(page.next_offset!)}>More entries</button>}
    <p className="profile-overview-note">Removing an entry removes structured context, not its original conversation, past answers or information already sent to a provider.</p>
    <dialog ref={dialog} onCancel={event => { if (busy) event.preventDefault(); else setDraft(null); }} aria-label={draft?.version ? 'Edit entry' : 'Add context'}>
      {draft && <form className="dialog-body" onSubmit={event => void save(event)}>
        <div className="dialog-top"><h2 id={`${id}-title`}>{draft.version ? 'Edit entry' : 'Add context'}</h2><button type="button" disabled={busy} onClick={() => setDraft(null)} aria-label="Close entry">×</button></div>
        <label className="field">Group<select value={draft.content.group} onChange={event => change({ group: event.target.value as Group, state: null })}>
          {Object.entries(groups).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <label className="field">Title<input ref={title} required maxLength={256} value={draft.content.title} onChange={event => change({ title: event.target.value })} /></label>
        <label className="field">Supporting details (optional)<textarea maxLength={2048} value={draft.content.notes} onChange={event => change({ notes: event.target.value })} /></label>
        {life.includes(draft.content.group) && <label className="field">State<select value={draft.content.state || ''} onChange={event => change({ state: event.target.value || null })}>
          <option value="">Not specified</option>{['tentative', 'planned', 'ongoing', 'completed', 'cancelled'].map(value => <option key={value}>{value}</option>)}
        </select></label>}
        <label className="field">Date in your words (optional)<input maxLength={256} value={draft.content.date.text} onChange={event => change({ date: { ...draft.content.date, text: event.target.value } })} /></label>
        <label className="field">Date precision<select value={draft.content.date.precision} onChange={event => change({ date: { ...draft.content.date, precision: event.target.value, start: null, end: null } })}>
          <option value="unknown">Uncertain or not supplied</option><option value="exact">Exact day</option><option value="month">Approximate month</option><option value="year">Approximate year</option><option value="range">Date range</option>
        </select></label>
        {draft.content.date.precision !== 'unknown' && <label className="field">{draft.content.date.precision === 'year' ? 'Year (YYYY)' : 'Date'}<input required type={draft.content.date.precision === 'year' ? 'text' : draft.content.date.precision === 'month' ? 'month' : 'date'} value={draft.content.date.start || ''} onChange={event => change({ date: { ...draft.content.date, start: event.target.value } })} /></label>}
        {draft.content.date.precision === 'range' && <label className="field">Through<input required type="date" value={draft.content.date.end || ''} onChange={event => change({ date: { ...draft.content.date, end: event.target.value } })} /></label>}
        {draft.source && <details><summary>Source</summary><p>{draft.source.kind === 'manual' ? 'Entered directly by you.' : 'From a conversation.'}</p>{draft.source.statement && <blockquote>{draft.source.statement}</blockquote>}</details>}
        {error && <p role="alert" className="error">{error}</p>}
        <div className="dialog-footer">{draft.version > 0 && <button type="button" disabled={busy} onClick={() => void remove()}>Remove</button>}<button type="button" disabled={busy} onClick={() => setDraft(null)}>Cancel</button><button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save entry'}</button></div>
      </form>}
    </dialog>
  </div>;
}
