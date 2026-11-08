import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';

type Choice = { id: string; name: string; picker_label?: string };
type Page = { people: Choice[]; total: number; next_after: string | null };

export function OwnedPersonPicker({ workspace, excludedId, selected, onSelect, purpose = 'relationship' }: {
  workspace: Workspace; excludedId: string; selected: Choice; onSelect: (person: Choice) => void;
  purpose?: 'relationship' | 'self';
}) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState<Page | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const read = useRef(0);
  useEffect(() => { void load(); return () => { read.current++; }; }, [query]);
  async function load(after: string | null = null) {
    const request = ++read.current;
    setState('loading');
    try {
      const result = await api<Page>('people/picker', workspace.csrf, 'POST', { query, after });
      if (read.current !== request) return;
      setPage(old => after && old ? { ...result, people: [...old.people, ...result.people] } : result);
      setState('ready');
    } catch { if (read.current === request) setState('error'); }
  }
  const choices = page?.people.filter(person => person.id !== excludedId) ?? [];
  // Keep the selected identity reachable when paging/search changes the choices.
  if (selected.id && !choices.some(person => person.id === selected.id)) choices.unshift(selected);
  return <>
    <label className="field">Search owned people<input type="search" value={query} onChange={event => { setPage(null); setQuery(event.target.value); }} /></label>
    <label className="field">Person<select required value={selected.id} onChange={event => {
      onSelect(choices.find(person => person.id === event.target.value) ?? { id: '', name: '' });
    }}><option value="">Choose an existing person</option>{choices.map(person =>
      <option key={person.id} value={person.id}>{person.picker_label ?? person.name}</option>)}
    </select></label>
    {state === 'loading' && <p role="status">Finding owned people…</p>}
    {state === 'error' && <p role="alert">People could not be refreshed. Your {purpose === 'relationship' ? 'selection and relationship draft are' : 'choice is'} retained. <button type="button" onClick={() => void load()}>Retry people search</button></p>}
    {page && <p>{page.people.length} of {page.total} matching owned people loaded{purpose === 'relationship' ? '; this person cannot link to itself.' : '.'}</p>}
    {page?.next_after && <button type="button" disabled={state !== 'ready'} onClick={() => void load(page.next_after)}>More people</button>}
  </>;
}
