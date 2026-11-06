import { useEffect, useRef, useState } from 'react';
import type { Workspace } from '../../api';
import { AppearanceSettings } from '../../appearance';
import { ProviderSettings, useProvider } from './provider';
import { SourceNotice } from '../../source-notice';
import { themes, readTheme } from '../../themes';
import { ToneSettings, useTone } from './tone-settings';

type Panel = 'appearance' | 'tone' | 'connection' | 'about';

function connectionSummary(provider: ReturnType<typeof useProvider>): string {
  const { status, error } = provider;
  if (error) return 'Connection status unavailable';
  if (!status.available) return 'Chat connection disabled';
  const selected = status.accounts.find(account => account.selected);
  if (!selected) return 'Not connected';
  if (status.phase === 'reauthorization_required') return 'Authorization needs renewing';
  if (status.phase === 'identity_only' || !selected.plan_enabled) return 'Plan permission not granted';
  if (status.phase === 'refresh_required') return 'Account saved · refresh needed';
  if (!status.connected) return 'Account saved · not connected';
  return status.registration === 'offline' ? 'Account saved · checked when used' : 'Connected · plan permission granted';
}

export function SettingsView({ workspace, provider, onClose }: {
  workspace: Workspace; provider: ReturnType<typeof useProvider>; onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [palette, setPalette] = useState(readTheme);
  const tone = useTone(workspace);
  const selectedTone = tone.saved?.profiles.find(item => item.id === tone.saved?.tone_id);

  useEffect(() => {
    const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    if (panel && !dialog.current?.open) dialog.current?.showModal();
    if (!panel && dialog.current?.open) dialog.current.close();
  }, [panel]);

  function open(next: Panel, button: HTMLButtonElement) {
    opener.current = button;
    setPanel(next);
  }
  function close() { dialog.current?.close(); }

  return <section className="settings-page" aria-label="Settings">
    <button className="quiet-action" type="button" onClick={onClose}>Back to workspace</button>
    <div className="eyebrow">YOUR WORKSPACE</div><h1 ref={heading} tabIndex={-1}>Settings</h1>
    <p className="settings-intro">A comfortable space, made yours.</p>
    <h2 className="settings-caption">Make it yours</h2>
    <div className="settings-rows">
      <button type="button" className="settings-row" onClick={event => open('appearance', event.currentTarget)}>
        <span className="settings-icon" aria-hidden="true">◐</span><strong>Appearance</strong>
        <span className="settings-value"><span className="settings-swatch" data-preview={palette} aria-hidden="true" />
          {themes.find(theme => theme.id === palette)?.label}<span aria-hidden="true">›</span></span>
      </button>
      <button type="button" className="settings-row" onClick={event => open('tone', event.currentTarget)}>
        <span className="settings-icon settings-voice" aria-hidden="true">Aa</span>
        <span className="settings-row-main"><strong>Kat's tone</strong><small>{tone.error && !tone.saved ? 'Status unavailable' :
          selectedTone?.description || 'Loading choice…'}</small></span>
        <span className="settings-value">{selectedTone?.voice_label || 'Choose'} <span aria-hidden="true">›</span></span>
      </button>
    </div>
    <h2 className="settings-caption">Your connection</h2>
    <div className="settings-rows">
      <button type="button" className="settings-row" onClick={event => open('connection', event.currentTarget)}>
        <span className="settings-icon" aria-hidden="true">↗</span>
        <span className="settings-row-main"><strong>ChatGPT</strong><small>{connectionSummary(provider)}</small></span>
        <span className="settings-value">Manage <span aria-hidden="true">›</span></span>
      </button>
    </div>
    <button className="settings-about" type="button" onClick={event => open('about', event.currentTarget)}>About Kat &amp; source</button>

    <dialog ref={dialog} className="settings-dialog" aria-labelledby="settings-dialog-title"
      onClose={() => { setPanel(null); opener.current?.focus(); }}
      onClick={event => {
        if (event.target !== dialog.current) return;
        const bounds = dialog.current.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) close();
      }}>
      <div className="dialog-body">
        <div className="dialog-top"><h2 id="settings-dialog-title">{panel === 'appearance' ? 'Choose a palette' :
          panel === 'tone' ? 'How should Kat sound?' :
          panel === 'connection' ? 'Chat connection' : 'About Kat'}</h2>
          <button type="button" aria-label="Close settings panel" onClick={close}>×</button></div>
        {panel === 'appearance' && <AppearanceSettings onChange={setPalette} />}
        {panel === 'tone' && <ToneSettings tone={tone} />}
        {panel === 'connection' && <ProviderSettings provider={provider} workspace={workspace} />}
        {panel === 'about' && <section aria-label="About and source"><p>Kat brings your charts, questions and conversations together.</p><SourceNotice /></section>}
      </div>
    </dialog>
  </section>;
}
