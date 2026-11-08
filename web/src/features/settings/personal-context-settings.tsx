import { useEffect, useState } from 'react';
import { api, type Workspace } from '../../shared/api';

type Preference = { enabled: boolean; version: number };
export function PersonalContextSettings({ workspace }: { workspace: Workspace }) {
  const [saved, setSaved] = useState<Preference | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<boolean | null>(null);
  async function load() {
    try { setSaved(await api<Preference>('personal-context-preference')); setError(''); }
    catch { setError('Personal-context setting could not be loaded.'); }
  }
  useEffect(() => { void load(); }, []);
  async function change(enabled: boolean) {
    if (!saved || busy) return;
    setBusy(true); setPending(enabled); setError('');
    try { setSaved(await api<Preference>('personal-context-preference', workspace.csrf, 'POST', { enabled, expected_version: saved.version })); }
    catch { setError('Setting change was not confirmed. Refresh to check the saved choice before trying again.'); }
    finally { setBusy(false); setPending(null); }
  }
  return <section aria-label="Personal context settings">
    <p>Allow Kat to use and collect personal context in conversations. Relevant details for selected people can be sent to your connected provider.</p>
    <p>Manual editing is always available. Journals, unselected people, relationship links and birth details are never collected automatically.</p>
    {saved ? <label><input type="checkbox" checked={pending ?? saved.enabled} disabled={busy || !!error} onChange={event => void change(event.target.checked)} /> Use and collect personal context automatically</label> : !error && <p role="status">Loading choice…</p>}
    {busy && <p role="status">Saving your choice…</p>}
    <p>Speak naturally about an explicitly identified selected person. Selecting a person does not tell Kat who you are; introduce yourself when using “I”. Kat should omit or clarify ambiguity, but automatic interpretation can sometimes be wrong. You can inspect and correct entries in Context.</p>
    <p>Turning this off affects subsequent turns, not archived answers. Removing context does not erase original conversations or information already sent to a provider; retained conversation history may still contain it.</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => void load()}>Refresh choice</button></p>}
  </section>;
}
