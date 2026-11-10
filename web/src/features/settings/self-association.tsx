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
    if (!saved || saved.version !== 0 || !selected.id || busy || error) return;
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
    <p>You can choose your own person once so ordinary “I” statements can be attributed to you. This account is yours alone; the choice cannot be switched to someone else. It does not turn on automatic context or select anyone for a conversation.</p>
    {saved && <p>{person.id ? <>Saved association: <strong>{person.picker_label ?? `${person.name} · ${person.id}`}</strong></> : saved.version > 0 ? 'Your previously chosen person is unavailable. The one-time choice cannot be reassigned.' : 'No self association saved.'}</p>}
    {editing && saved?.version === 0 ? <fieldset disabled={busy || !!error}>
      <legend>Explicitly identify yourself</legend>
      <OwnedPersonPicker workspace={workspace} excludedId="" selected={choice} onSelect={setChoice} purpose="self" />
      <div className="form-actions"><button type="button" className="self-confirm" disabled={!choice.id} onClick={() => void save(choice)}>Use this person as me</button>
        <button type="button" onClick={() => { setChoice(person); setEditing(false); }}>Cancel</button></div>
    </fieldset> : saved?.version === 0 && <div className="form-actions">
      <button type="button" disabled={busy || !!error} onClick={() => setEditing(true)}>Choose who is me</button>
    </div>}
    {busy && <p role="status">Checking or saving your self association…</p>}
    {error && <p role="alert">{error} <button type="button" disabled={busy} onClick={() => void load()}>Refresh association</button></p>}
    <p>This helps Kat understand “I” and “my” when remembering your life. You do not need to select that person’s chart. Naming someone else does not change this choice. Earlier messages are not reinterpreted as yours when you make this choice. Saved entries and archived replies are not moved.</p>
  </section>;
}
