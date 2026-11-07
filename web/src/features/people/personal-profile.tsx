import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import { CreatePersonDialog, type Person } from './people';

type Details = { pronouns: string; home: string; occupation: string; about: string };
type Link = { id: string; other_person_id: string; name: string; label: string; dates: string; version: number };
type Profile = { version: number; details: Details; links: Link[] };

export type ProfileMemory = { details?: Details | null; link?: Link | null; version?: number;
  attempt?: { key: string; id: string } | null };
export function PersonalProfile({ workspace, personId, active, openPerson, memory }: {
  workspace: Workspace; personId: string; active: boolean; openPerson: (id: string) => void; memory: ProfileMemory;
}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [details, setDetails] = useState<Details | null>(memory.details ?? null);
  const [link, setLink] = useState<Link | null>(memory.link ?? null);
  const [people, setPeople] = useState<{ id: string; name: string }[]>([]);
  const [creating, setCreating] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const attempt = useRef<{ key: string; id: string } | null>(memory.attempt ?? null);
  const dialog = useRef<HTMLDialogElement>(null);
  const read = useRef(0);
  const path = `people/${personId}/personal-profile`;
  memory.details = details; memory.link = link; memory.attempt = attempt.current;
  useEffect(() => { if (active && !loaded) void load(); return () => { read.current++; }; }, [active, personId]);
  useEffect(() => {
    if (active && (details || link) && !dialog.current?.open) dialog.current?.showModal();
    if ((!active || (!details && !link)) && dialog.current?.open) dialog.current.close();
  }, [active, !!details, !!link]);
  async function load() {
    const request = ++read.current;
    try {
      const [result, choices] = await Promise.all([api<Profile>(path), api<{ people: { id: string; name: string }[] }>('people')]);
      if (read.current !== request) return;
      setProfile(result); setPeople(choices.people); setLoaded(true); setError('');
    } catch { if (read.current === request) setError('Personal details could not be loaded. Your edits are retained.'); }
  }
  async function save(change: unknown) {
    const key = JSON.stringify(change);
    if (attempt.current?.key !== key) attempt.current = { key, id: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      await api(path, workspace.csrf, 'POST', { operation_id: attempt.current.id, change });
      attempt.current = null; setDetails(null); setLink(null); await load();
    } catch { setError('Change was not confirmed. Check the details or reopen the latest version if another edit was saved. Your input is retained.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Personal details and linked people">
    {!loaded && !error && <p role="status">Opening personal details…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => void load()}>Refresh saved details</button></p>}
    {profile && <>
      <div className="profile-editor-heading"><h2>Personal details</h2><button type="button" onClick={() => { memory.version = profile.version; setDetails({ ...profile.details }); }}>Edit</button></div>
      <dl className="profile-facts">{Object.entries(profile.details).filter(([, value]) => value).map(([key, value]) => <div key={key}><dt>{key === 'home' ? 'Based in' : key[0].toUpperCase() + key.slice(1)}</dt><dd>{value}</dd></div>)}</dl>
      {!Object.values(profile.details).some(Boolean) && <p>Optional details, at your pace.</p>}
      <div className="profile-editor-heading"><h2>Linked people</h2><button type="button" onClick={() => setLink({ id: crypto.randomUUID(), other_person_id: '', name: '', label: '', dates: '', version: 0 })}>Link person</button></div>
      {profile.links.map(item => <div key={item.id} className="profile-quiet-group">
        <button type="button" className="profile-quiet-row" onClick={() => openPerson(item.other_person_id)}><span><strong>{item.name}</strong><small>{item.label}{item.dates && ` · ${item.dates}`}</small></span><span aria-hidden="true">›</span></button>
        <button type="button" onClick={() => setLink({ ...item })}>Edit relationship with {item.name}</button>
      </div>)}
      {!profile.links.length && <p>No people linked. Links stay within your workspace and do not share accounts.</p>}
    </>}
    <dialog ref={dialog} aria-label={details ? 'Edit personal details' : 'Link person'} onCancel={event => {
      if (busy) event.preventDefault(); else { setDetails(null); setLink(null); }
    }}>
      <form className="dialog-body" onSubmit={event => { event.preventDefault(); if (!busy) void save(details ? { kind: 'details', expected_version: memory.version ?? profile!.version, details } : { kind: 'link', id: link!.id, expected_version: link!.version, other_person_id: link!.other_person_id, label: link!.label, dates: link!.dates }); }}>
        <h2>{details ? 'Personal details' : 'Linked person'}</h2>
        {details && (Object.keys(details) as (keyof Details)[]).map(key => <label className="field" key={key}>{key === 'home' ? 'Based in' : key[0].toUpperCase() + key.slice(1)}<input maxLength={1024} value={details[key]} onChange={event => setDetails({ ...details, [key]: event.target.value })} /></label>)}
        {link && <>
          <label className="field">Person<select required value={link.other_person_id} onChange={event => setLink({ ...link, other_person_id: event.target.value })}>
            <option value="">Choose an existing person</option>{people.filter(person => person.id !== personId).map((person, index) => <option key={person.id} value={person.id}>{person.name}{people.filter(other => other.name === person.name).length > 1 ? ` (person ${index + 1})` : ''}</option>)}
          </select></label>
          <button type="button" onClick={() => setCreating(true)}>Create a new person</button>
          <label className="field">Their relationship to this person<input required maxLength={128} placeholder="For example, sibling" value={link.label} onChange={event => setLink({ ...link, label: event.target.value })} /></label>
          <label className="field">Dates (optional)<input maxLength={256} value={link.dates} onChange={event => setLink({ ...link, dates: event.target.value })} /></label>
          <p>This directional label does not create an inverse relationship or select their context for chat.</p>
        </>}
        {error && <p role="alert">{error}</p>}
        <div className="dialog-footer">{link && link.version > 0 && <button type="button" disabled={busy} onClick={() => void save({ kind: 'unlink', id: link.id, expected_version: link.version })}>Unlink</button>}
          <button type="button" disabled={busy} onClick={() => { setDetails(null); setLink(null); }}>Cancel</button><button className="primary" disabled={busy}>Save</button></div>
      </form>
    </dialog>
    <CreatePersonDialog open={creating} workspace={workspace} onClose={() => setCreating(false)} onCreated={(person: Person) => { setPeople(old => [...old, person]); setLink(old => old ? { ...old, other_person_id: person.id } : old); }} />
  </section>;
}
