import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import { OwnedPersonPicker } from '../people/owned-person-picker';
import './self-association.css';

type Association = { person_id: string | null; version: number };
type Choice = { id: string; name: string; picker_label?: string };
const empty: Choice = { id: '', name: '' };

export function SelfAssociation({ workspace }: { workspace: Workspace }) {
  const [saved, setSaved] = useState<Association | null>(null);
  const [person, setPerson] = useState<Choice>(empty);
  const [choice, setChoice] = useState<Choice>(empty);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  async function load() {
    const version = ++request.current;
    setBusy(true);
    try {
      const result = await api<Association>('personal-context-self');
      const selected = result.person_id ? await api<Choice>(`people/${encodeURIComponent(result.person_id)}`) : empty;
      if (request.current !== version) return;
      setSaved(result); setPerson(selected); setChoice(selected); setEditing(false); setError('');
    } catch { if (request.current === version) setError('Your saved self association could not be checked.'); }
    finally { if (request.current === version) setBusy(false); }
  }
  useEffect(() => { void load(); return () => { request.current++; }; }, []);
  async function save(selected: Choice) {
    if (!saved || busy || error) return;
    const version = ++request.current;
    setBusy(true);
    try {
      const result = await api<Association>('personal-context-self', workspace.csrf, 'POST', {
        person_id: selected.id || null, expected_version: saved.version,
      });
      if (request.current !== version) return;
      setSaved(result); setPerson(selected); setChoice(selected); setEditing(false);
    } catch { if (request.current === version) setError('The change was not confirmed. Refresh the saved association before trying again.'); }
    finally { if (request.current === version) setBusy(false); }
  }
  return <section className="self-association" aria-label="Who is me?">
    <h3>Who is me?</h3>
    <p>Choose your own person once so ordinary “I” statements can be attributed to you. This does not turn on automatic context or select anyone for a conversation.</p>
    {saved && <p>{person.id ? <>Saved association: <strong>{person.picker_label ?? `${person.name} · ${person.id}`}</strong></> : 'No self association saved.'}</p>}
    {editing ? <fieldset disabled={busy || !!error}>
      <legend>Explicitly identify yourself</legend>
      <OwnedPersonPicker workspace={workspace} excludedId="" selected={choice} onSelect={setChoice} purpose="self" />
      <div className="form-actions"><button type="button" className="self-confirm" disabled={!choice.id} onClick={() => void save(choice)}>Use this person as me</button>
        <button type="button" onClick={() => { setChoice(person); setEditing(false); }}>Cancel</button></div>
    </fieldset> : saved && <div className="form-actions">
      <button type="button" disabled={busy || !!error} onClick={() => setEditing(true)}>{person.id ? 'Change who is me' : 'Choose who is me'}</button>
      {person.id && <button type="button" disabled={busy || !!error} onClick={() => void save(empty)}>Clear self association</button>}
    </div>}
    {busy && <p role="status">Checking or saving your self association…</p>}
    {error && <p role="alert">{error} <button type="button" disabled={busy} onClick={() => void load()}>Refresh association</button></p>}
    <p>With automatic context enabled, keep that person selected when discussing your life. Changing or clearing this association stops in-flight self updates; it does not move old entries or change archived replies.</p>
  </section>;
}
