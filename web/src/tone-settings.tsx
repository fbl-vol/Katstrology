import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';

type Profile = { id: string; version: number; name: string; voice_label: string;
  description: string; example: string };
type Preference = { tone_id: string; revision: number; default_id: string; profiles: Profile[] };

export function useTone(workspace: Workspace) {
  const [saved, setSaved] = useState<Preference | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const owner = useRef(workspace.owner);
  owner.current = workspace.owner;

  useEffect(() => {
    const current = workspace.owner;
    setSaved(null); setPreviewId(null); setError(''); setBusy(false);
    void api<Preference>('settings/tone').then(value => {
      if (owner.current === current) setSaved(value);
    }).catch(() => {
      if (owner.current === current) setError('Tone could not be loaded. Reopen Settings to try again.');
    });
  }, [workspace.owner]);

  async function choose(toneId: string) {
    if (!saved || busy || !saved.profiles.some(profile => profile.id === toneId)) return;
    const current = workspace.owner;
    setPreviewId(toneId); setBusy(true); setError('');
    try {
      const result = await api<{ tone_id: string; revision: number }>(
        'settings/tone', workspace.csrf, 'PUT', { tone_id: toneId, revision: saved.revision });
      if (owner.current === current) setSaved({ ...saved, ...result });
    } catch {
      try {
        const confirmed = await api<Preference>('settings/tone');
        if (owner.current === current) {
          setSaved(confirmed);
          setError(confirmed.tone_id === toneId && confirmed.revision > saved.revision ? '' :
            'Tone was not changed. The current choice is shown below; choose again if you still want this voice.');
        }
      } catch {
        if (owner.current === current) setError('Tone change could not be confirmed. Reopen Settings to check before trying again.');
      }
    } finally {
      if (owner.current === current) { setPreviewId(null); setBusy(false); }
    }
  }

  return { saved, previewId, busy, error, choose };
}

type Tone = ReturnType<typeof useTone>;

export function ToneSettings({ tone }: { tone: Tone }) {
  const { saved, previewId, busy, error } = tone;
  if (!saved) return <p role={error ? 'alert' : 'status'}>{error || 'Loading tone choices…'}</p>;
  const active = previewId || saved.tone_id;
  const profile = saved.profiles.find(item => item.id === active)!;
  return <section className="tone-picker" aria-label="Kat's tone">
    <p>Choose how Kat sounds. Facts, sources and permissions stay the same.</p>
    <div className="tone-options">{saved.profiles.map(item => <button key={item.id} type="button"
      aria-pressed={item.id === saved.tone_id} disabled={busy} onClick={() => void tone.choose(item.id)}>
      <span><strong>{item.voice_label}</strong><small>{item.name} · {item.description}</small></span>
      <span aria-hidden="true">{item.id === saved.tone_id ? '✓' : ''}</span>
    </button>)}</div>
    <div className="tone-example"><strong>A written example · {profile.voice_label}</strong>
      <p>What does a square mean in a birth chart?</p><p>{profile.example}</p></div>
    <p role={error ? 'alert' : 'status'}>{busy ? 'Saving tone…' : error ||
      `${saved.profiles.find(item => item.id === saved.tone_id)?.voice_label} is active for your next reply.`}</p>
    <p>Original Kat voices inspired by broad qualities, not celebrity impersonations or endorsements. Examples are prewritten; changing tone does not send a message.</p>
  </section>;
}
