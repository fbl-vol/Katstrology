import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../../shared/api';
import type { Chart, NatalResult } from './natal';
import { catalogue, categories, patternExplanation, type Category, type Entry, type Exploration } from './exploration-data';
import { Highlight, type WheelOverlay } from './exploration-geometry';
import { ExplorationTargets, type WheelChoice } from './exploration-targets';
import './natal-explorer.css';

function focusHeading(heading: HTMLHeadingElement | null) {
  if (!heading) return;
  heading.focus({ preventScroll: true });
  const rect = heading.getBoundingClientRect();
  if (rect.top < 96 || rect.bottom > window.innerHeight)
    heading.scrollIntoView({ block: 'start' });
}

export function NatalExplorer({ chart, natal, wheel, enabled }: { chart: Chart; natal: NatalResult; enabled: boolean;
  wheel: (overlay: WheelOverlay, selected: boolean) => ReactNode }) {
  const [opened, setOpened] = useState(enabled);
  useEffect(() => { if (enabled) setOpened(true); }, [enabled]);
  const [category, setCategory] = useState<Category>('positions');
  const [queries, setQueries] = useState<Record<Category, string>>({ positions: '', houses: '', aspects: '', patterns: '' });
  const [selected, setSelected] = useState<Entry | null>(null);
  const [detail, setDetail] = useState(false);
  const [choices, setChoices] = useState<WheelChoice | null>(null);
  const choiceHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (choices) focusHeading(choiceHeading.current); }, [choices]);
  const [projection, setProjection] = useState<Exploration | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const listFocus = useRef<string | null>(null);
  const [focusList, setFocusList] = useState(0);
  useEffect(() => {
    if (!opened) return;
    let current = true;
    setProjection(null); setFailed(false);
    api<Exploration>(`charts/${encodeURIComponent(chart.id)}/exploration`).then(value => {
      if (current && value.chart_id === chart.id) setProjection(value);
    }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [chart.id, chart.source_status, attempt, opened]);
  useEffect(() => {
    if (detail) focusHeading(heading.current);
  }, [detail, selected]);
  useEffect(() => {
    if (!focusList) return;
    const buttons = panel.current?.querySelectorAll<HTMLButtonElement>('[data-entry]');
    const previous = Array.from(buttons ?? []).find(b => b.dataset.entry === listFocus.current);
    (previous ?? panel.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]'))?.focus();
  }, [focusList]);

  const entries = catalogue(chart, natal, projection?.status === 'supported' ? projection.patterns : []);
  const query = queries[category].trim().toLowerCase();
  const visible = entries[category].filter(e => `${e.title} ${e.subtitle} ${e.facts.flat().join(' ')}`.toLowerCase().includes(query));
  const index = selected ? entries[selected.category].findIndex(e => e.id === selected.id) : -1;
  function choose(entry: Entry) {
    setChoices(null); setCategory(entry.category); setSelected(entry); setDetail(true); listFocus.current = entry.id;
  }
  function browse() { setChoices(null); setDetail(false); setFocusList(n => n + 1); }
  function entryButton(entry: Entry) {
    return <button type="button" className="explorer-entry" key={entry.id} data-entry={entry.id} onClick={() => choose(entry)}>
      <span><strong>{entry.title}</strong><small>{entry.subtitle}</small></span><span aria-hidden="true">›</span>
    </button>;
  }
  function patternList(items: Entry[]) {
    const parents = items.filter(e => !e.pattern?.contained_by.length);
    const children = items.filter(e => e.pattern?.contained_by.length);
    return <>{parents.map(entryButton)}{children.length > 0 && <details className="explorer-contained"
      open={!!query || children.some(e => e.id === listFocus.current) || undefined}>
      <summary>{children.length} contained T-squares</summary>
      <p>These reuse connections within Grand Crosses, not separate events. Each detail lists every containing formation.</p>
      {children.map(child => <div key={child.id}>{entryButton(child)}
        <p className="explorer-note">Within {entries.patterns.filter(parent => child.pattern!.contained_by.includes(parent.id))
          .map(parent => `${parent.title} (${parent.subtitle})`).join('; ')}</p></div>)}
    </details>}</>;
  }
  const unavailable = projection?.reason === 'legacy_chart' ? 'Patterns are unavailable for this older Sun-only chart.' :
    projection?.reason === 'historical_source' ? 'Patterns are unavailable for a historical source.' :
    'Patterns need established natal positions and aspects from an exact birth time.';

  return <div className="natal-explorer">
    <div className="explorer-chart">
      {wheel(geometry => <>
        <Highlight natal={natal} geometry={geometry} entry={choices ? null : selected} />
        <ExplorationTargets natal={natal} geometry={geometry} entries={entries} choose={choose} overlap={setChoices} />
        {choices && <circle className="exploration-marker" cx={choices.location.x} cy={choices.location.y} r="5"
          fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-angle, #304f3b)" strokeWidth="2" pointerEvents="none" />}
      </>, !!selected && !choices)}
      <p className="explorer-note">Choose a symbol, house number or connection. Inside a formation, choose a pattern. The directory offers the same details without precise pointing.</p>
      <div className="explorer-selection"><span>{choices ? 'Choose at this point' : selected?.title ?? 'Nothing selected'}<small>{choices ? 'Several details share this location.' : selected?.subtitle ?? 'Choose a detail from the directory.'}</small></span>
        <button type="button" onClick={browse}>Browse all</button></div>
    </div>
    <section ref={panel} className="explorer-panel" aria-label="Chart browser and selected detail">
      {choices ? <>
        <h3 ref={choiceHeading} tabIndex={-1}>{choices.entries[0].category === 'patterns' ? 'Patterns' : 'Details'} at this point</h3>
        <p>These overlap. Choose which one to explore.</p>
        <p className="explorer-note">{choices.entries.length} matching {choices.entries[0].category}</p>
        {choices.entries[0].category === 'patterns' ? patternList(choices.entries) : choices.entries.map(entryButton)}
        <button type="button" className="explorer-cancel" onClick={() => {
          const origin = choices.origin; setChoices(null);
          requestAnimationFrame(() => { origin.scrollIntoView({ block: 'center' }); origin.focus({ preventScroll: true }); });
        }}>Back without choosing</button>
      </> : detail && selected ? <>
        <div className="explorer-back"><button type="button" onClick={browse}>← All {category}</button>
          <small>{index + 1} / {entries[category].length} {category}</small></div>
        <h3 tabIndex={-1} ref={heading}>{selected.title}</h3><p>{selected.subtitle}</p>
        <dl className="explorer-facts">{selected.facts.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
        {selected.pattern && <>
          <p>{patternExplanation(selected.pattern)}</p>
          <details className="explorer-connections"><summary>{selected.edges.length} connections and saved orb limits</summary>
            {entries.aspects.filter(e => selected.edges.includes(e.id)).map(entryButton)}</details>
          {selected.pattern.contained_by.length > 0 && <div className="explorer-parent"><p>Also part of these Grand Crosses:</p>
            {entries.patterns.filter(e => selected.pattern!.contained_by.includes(e.id)).map(entryButton)}</div>}
          {entries.patterns.some(e => e.pattern?.contained_by.includes(selected.id)) && <details><summary>T-squares within this formation</summary>
            {entries.patterns.filter(e => e.pattern?.contained_by.includes(selected.id)).map(entryButton)}</details>}
          <p className="explorer-note">Geometric patterns use this saved chart’s selected aspects and orb limits. Only the ten planets and luminaries participate. No strength score or prediction is implied.</p>
        </>}
        {selected.house && <p>The shaded sector uses this chart’s actual cusp boundaries. Empty houses remain part of the chart.</p>}
        {selected.category === 'aspects' && <p>{selected.id.startsWith('conjunction:') ? 'The arc and endpoint rings mark this conjunction.' : 'The highlighted connection joins these exact positions. Oppositions use a dashed line.'}</p>}
        <nav className="explorer-next" aria-label={`Browse all ${category}`}>
          {[-1, 1].map(delta => <button type="button" key={delta} onClick={() => {
            const list = entries[category]; choose(list[(index + delta + list.length) % list.length]);
          }}>{delta < 0 ? '← Previous' : 'Next →'} {category.slice(0, -1)}</button>)}
        </nav>
      </> : <>
        <h3>Browse this chart</h3><p className="explorer-note">Positions, houses, connections and formations.</p>
        <div className="explorer-tabs" role="tablist" aria-label="Chart detail categories">
          {categories.map((name, i) => <button type="button" key={name} role="tab" id={`${chart.id}-explore-${name}`}
            aria-controls={`${chart.id}-explore-list`} aria-selected={category === name} tabIndex={category === name ? 0 : -1}
            onClick={() => setCategory(name)} onKeyDown={event => {
              const next = event.key === 'ArrowRight' ? (i + 1) % 4 : event.key === 'ArrowLeft' ? (i + 3) % 4 : event.key === 'Home' ? 0 : event.key === 'End' ? 3 : null;
              if (next === null) return;
              event.preventDefault(); setCategory(categories[next]);
              (event.currentTarget.parentElement?.children[next] as HTMLButtonElement).focus();
            }}>{name[0].toUpperCase() + name.slice(1)} <small>{name !== 'patterns' || projection?.status === 'supported' ? entries[name].length : projection || failed ? '–' : '…'}</small></button>)}
        </div>
        <div role="tabpanel" id={`${chart.id}-explore-list`} aria-labelledby={`${chart.id}-explore-${category}`}>
          <label className="explorer-search">Find in {category}<input type="search" value={queries[category]}
            onChange={e => setQueries({ ...queries, [category]: e.target.value })} /></label>
          {queries[category] && <button type="button" onClick={() => setQueries({ ...queries, [category]: '' })}>Clear search</button>}
          {(category !== 'patterns' || projection?.status === 'supported') &&
            <p className="explorer-note" role="status">{visible.length} of {entries[category].length} {category}{category === 'houses' ? ' and angles' : ''}</p>}
          {category === 'patterns' && (!projection ? <p role="status">{failed ? <>Patterns could not be loaded. <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry patterns</button></> : 'Loading patterns…'}</p> :
            projection.status !== 'supported' ? <p>{unavailable}</p> : !entries.patterns.length ? <p>No supported patterns match this chart’s settings.</p> : null)}
          {category === 'houses' && !entries.houses.length && <p>Houses and angles are unavailable. No substitute cusps were calculated.</p>}
          {query && !visible.length && <p>No matching details. Try another name or clear your search.</p>}
          {category === 'patterns' ? patternList(visible) : visible.map(entryButton)}
        </div>
      </>}
    </section>
  </div>;
}
