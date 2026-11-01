import { useEffect, useRef } from 'react';
import type { Workspace } from './api';
import { AppearanceSettings } from './appearance';
import { ProviderSettings, useProvider } from './provider';
import { SourceNotice } from './source-notice';

export function SettingsView({ workspace, provider, onClose }: {
  workspace: Workspace; provider: ReturnType<typeof useProvider>; onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, []);
  return <section className="settings-page" aria-label="Settings">
    <button className="quiet-action" type="button" onClick={onClose}>Back to workspace</button>
    <div className="eyebrow">YOUR WORKSPACE</div><h1 ref={heading} tabIndex={-1}>Settings</h1>
    <ProviderSettings provider={provider} workspace={workspace} />
    <AppearanceSettings />
    <section className="settings-section" aria-label="About and source">
      <h2>About and source</h2>
      <SourceNotice />
    </section>
  </section>;
}
