import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import type { SelectedResult } from '../conversation/archive';
import { ChartLibraryPreview } from './chart-library-preview';
import { ChartLibraryReader } from './chart-library-reader';
import { libraryDate, libraryPlace, libraryTitles, libraryVariant,
  type LibrarySummary, type LibraryHistory, type LibraryResult, type LibraryTechnique } from './chart-library-data';
import './chart-library.css';

const preferenceKey = 'kat-chart-library-layout-v1';
function preferredLayout(): 'list' | 'gallery' {
  try { return localStorage.getItem(preferenceKey) === 'gallery' ? 'gallery' : 'list'; }
  catch { return 'list'; }
}

function ResultSummary({ result, personId }: { result: LibraryResult; personId: string }) {
  const variant = libraryVariant(result, personId);
  return <><p className="library-date">{libraryDate(result)}</p>
    {variant && <p className="library-variant">{variant}</p>}
    <p className="library-place">{libraryPlace(result)}</p>
    {result.source_status !== 'current' && <p className="library-source">Historical source · original saved values</p>}</>;
}

function ChartLibraryHistory({ personId, technique, onOpen, onBack }: {
  personId: string; technique: LibraryTechnique; onOpen: (result: LibraryResult) => void; onBack: () => void;
}) {
  const [rows, setRows] = useState<LibraryResult[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const version = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  async function load(before: string | null) {
    const request = ++version.current;
    setBusy(true); setError(false);
    try {
      const page = await api<LibraryHistory>(`people/${encodeURIComponent(personId)}/chart-library/${technique}${before ? `?before=${encodeURIComponent(before)}` : ''}`);
      if (request !== version.current) return;
      setRows(previous => before ? [...previous, ...page.entries] : page.entries);
      setNext(page.next_before); setLoaded(true);
    } catch { if (request === version.current) setError(true); }
    finally { if (request === version.current) setBusy(false); }
  }
  useEffect(() => {
    void load(null); heading.current?.focus();
    return () => { version.current++; };
  }, [personId, technique]);
  return <section className="library-history" aria-label={`${libraryTitles[technique]} history`}>
    <button type="button" onClick={onBack}>← Back to chart library</button>
    <h2 tabIndex={-1} ref={heading}>{libraryTitles[technique]} · History</h2>
    <p>All saved versions, newest save first. Opening one never replaces the active natal or rewrites a result.</p>
    <ol>{rows.map(row => <li key={row.id} data-result-id={row.id}>
      <div><strong>Saved {new Date(row.created_at).toISOString().slice(0, 19).replace('T', ' ')} UTC</strong>
        <ResultSummary result={row} personId={personId} /><p className="library-place">Version {row.id}</p></div>
      <button type="button" onClick={() => onOpen(row)} aria-label={`Open saved ${libraryTitles[technique]} ${row.id}`}>Open</button>
    </li>)}</ol>
    {busy && <p role="status">Loading saved history…</p>}
    {error && <div role="alert"><p>History could not be loaded. Already listed versions are still available.</p>
      <button type="button" onClick={() => void load(loaded ? next : null)}>Retry history</button></div>}
    {!busy && !error && loaded && !rows.length && <p>No saved versions for this type.</p>}
    {!error && next && <button type="button" disabled={busy} onClick={() => void load(next)}>Load older results</button>}
  </section>;
}

export function ChartLibrary({ workspace, personId, activeChartId, enabled, onCreate, onDiscuss, onCreateNatal, natalRequest = 0 }: {
  workspace: Workspace; personId: string; activeChartId: string | null; enabled: boolean;
  onCreate: () => void; onCreateNatal: () => void; onDiscuss: (result: SelectedResult, label: string) => void; natalRequest?: number;
}) {
  const [layout, setLayout] = useState(preferredLayout);
  const [summary, setSummary] = useState<LibrarySummary | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [visited, setVisited] = useState(enabled);
  const [selected, setSelected] = useState<LibraryResult | null>(null);
  const [history, setHistory] = useState<LibraryTechnique | null>(null);
  const collectionHeading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const historyOpener = useRef<HTMLElement | null>(null);
  const handledNatalRequest = useRef(0);
  const hasVisited = visited || enabled;
  useEffect(() => { if (enabled) setVisited(true); }, [enabled]);
  useEffect(() => {
    if (!hasVisited) return;
    let current = true;
    setSummary(null); setError(false);
    void api<LibrarySummary>(`people/${encodeURIComponent(personId)}/chart-library`)
      .then(value => { if (current) setSummary(value); })
      .catch(() => { if (current) setError(true); });
    return () => { current = false; };
  }, [personId, activeChartId, hasVisited, attempt]);

  useEffect(() => {
    if (!summary || natalRequest <= handledNatalRequest.current) return;
    handledNatalRequest.current = natalRequest;
    const natal = summary.entries.find(entry => entry.technique === 'natal')?.representative;
    if (natal) { setHistory(null); setSelected(natal); }
  }, [summary, natalRequest]);

  function chooseLayout(next: 'list' | 'gallery') {
    setLayout(next);
    try { localStorage.setItem(preferenceKey, next); } catch { /* Local preference is optional. */ }
  }
  function open(result: LibraryResult) {
    opener.current = document.activeElement as HTMLElement;
    setSelected(result);
  }
  function backToCollection() {
    setSelected(null);
    requestAnimationFrame(() => {
      if (opener.current?.getClientRects().length) opener.current.focus();
      else collectionHeading.current?.focus();
    });
  }
  return <div className="chart-library">
    <div hidden={!!selected || !!history}>
      <div className="library-heading"><div><h2 ref={collectionHeading} tabIndex={-1}>Your chart collection</h2>
        <p>Current natal and latest saved results. Earlier versions stay in History.</p></div>
        <button type="button" onClick={onCreate}>Create chart</button></div>
      <div className="library-toolbar"><p>{summary ? `${summary.entries.length} saved chart types` : 'Saved chart library'}</p>
        <div className="library-view-toggle" role="group" aria-label="Chart library layout">
          <button type="button" aria-pressed={layout === 'list'} onClick={() => chooseLayout('list')}>List</button>
          <button type="button" aria-pressed={layout === 'gallery'} onClick={() => chooseLayout('gallery')}>Gallery</button>
        </div></div>
      {!summary && !error && hasVisited && <p role="status">Loading saved chart library…</p>}
      {error && <div role="alert"><p>The saved chart library could not be loaded. Nothing was recalculated.</p>
        <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry chart library</button></div>}
      {summary && !summary.entries.length && <div className="library-empty"><h3>No saved charts yet</h3>
        <p>Create a chart using supplied birth details. Unsaved calculations do not appear here.</p></div>}
      {!activeChartId && <div className="library-empty"><p>No active generated natal. Nothing is guessed from a draft or an earlier chart.</p>
        <button type="button" onClick={onCreateNatal}>Create first chart</button></div>}
      <div className="library-collection" data-view={layout}>{summary?.entries.map(entry => {
        const result = entry.representative;
        return <article className="library-card" key={entry.technique} data-technique={entry.technique}
          data-result-id={result?.id} aria-label={libraryTitles[entry.technique]}>
          {result && <ChartLibraryPreview preview={result.preview} label={libraryTitles[entry.technique]} />}
          <div className="library-card-copy"><span className="library-label">{entry.technique === 'natal' ? result ? 'Current natal' : 'Saved natal versions' : 'Latest saved'}</span>
            <h3>{libraryTitles[entry.technique]}</h3>
            {result ? <ResultSummary result={result} personId={personId} /> : <p>No active natal. Earlier saved versions remain in History.</p>}
            <button type="button" className="library-history-link" aria-label={`${libraryTitles[entry.technique]} history, ${entry.count} saved`}
              onClick={() => { historyOpener.current = document.activeElement as HTMLElement; setHistory(entry.technique); }}>
              History · {entry.count} saved{entry.variants > 1 ? ` · ${entry.variants} variants` : ''}</button>
          </div>
          {result && <button type="button" className="library-open" onClick={() => open(result)}
            aria-label={`Open ${libraryTitles[entry.technique]}`}>Open<span className="library-open-suffix"> chart</span></button>}
        </article>;
      })}</div>
    </div>
    {history && <div hidden={!!selected}><ChartLibraryHistory key={history} personId={personId} technique={history}
      onOpen={open} onBack={() => { setHistory(null); requestAnimationFrame(() => historyOpener.current?.focus()); }} /></div>}
    {selected && <ChartLibraryReader key={`${selected.technique}:${selected.id}`} workspace={workspace} selected={selected}
      isActiveNatal={selected.id === activeChartId} onBack={backToCollection} onDiscuss={onDiscuss} />}
  </div>;
}
