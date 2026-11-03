import { useState } from 'react';
import { applyTheme, initializeTheme, themes, type ThemeId } from './themes';

export function AppearanceSettings({ onChange }: { onChange: (theme: ThemeId) => void }) {
  const [selected, setSelected] = useState<ThemeId>(initializeTheme);
  const [mode, setMode] = useState<'light' | 'dark'>(() =>
    themes.find(theme => theme.id === selected)!.mode);
  return <section className="settings-picker" aria-label="Appearance">
    <p>Choose a reading palette. Your choice stays in this browser, including after sign-out.</p>
    <div className="settings-mode" role="group" aria-label="Palette groups">
      {(['light', 'dark'] as const).map(group => <button key={group} type="button"
        aria-pressed={mode === group} onClick={() => setMode(group)}>{group === 'light' ? 'Light' : 'Dark'}</button>)}
    </div>
    <div className="appearance-options" aria-label={`${mode} palettes`}>
      {themes.filter(theme => theme.mode === mode).map(theme =>
        <button key={theme.id} type="button" className="appearance-option"
          aria-pressed={selected === theme.id} onClick={() => {
            applyTheme(theme.id); setSelected(theme.id); onChange(theme.id);
          }}>
          <span className="appearance-swatch" data-preview={theme.id} aria-hidden="true"><span /></span>
          <span className="appearance-option-text"><strong>{theme.label}</strong><small>{theme.description}</small></span>
          <span className="appearance-current" aria-hidden="true">{selected === theme.id ? '✓' : ''}</span>
        </button>)}
    </div>
  </section>;
}
