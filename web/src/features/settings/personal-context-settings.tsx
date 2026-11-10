import { useEffect, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import { SelfAssociation } from './self-association';
import './personal-context-settings.css';

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
    <p>Let Kat remember useful facts you share about anyone saved in your account, including people you add later. You do not need to select a chart or ask to save each fact.</p>
    <p>With this on, recent messages and relevant saved context can be sent to your connected provider for processing after a reply. You can keep chatting while it runs.</p>
    {saved ? <label className="personal-context-consent"><input type="checkbox" checked={pending ?? saved.enabled} disabled={busy || !!error} onChange={event => void change(event.target.checked)} /><span>Use and collect personal context automatically</span></label> : !error && <p role="status">Loading choice…</p>}
    {busy && <p role="status">Saving your choice…</p>}
    <SelfAssociation workspace={workspace} />
    <p>Inspect, edit or remove saved details in each person’s Context. Memory can miss or misunderstand things; ambiguous names, quotes and hypothetical examples are skipped. This uses conversation, not your journals, and does not change birth details or relationship links.</p>
    <p>Turning this off stops future automatic updates, including pending ones. It does not remove saved context or conversations, or recall information already sent to your provider.</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => void load()}>Refresh choice</button></p>}
  </section>;
}
