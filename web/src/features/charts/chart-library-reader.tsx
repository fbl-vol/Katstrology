import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../shared/api';
import { NatalChart, type Chart } from './natal';
import { SavedResultDetail, type SavedCalculation } from './saved-result-detail';
import { RelationshipDerivedView, type Derived } from './relationship-derived-view';
import { SynastryView, type SynastryData } from './synastry-view';
import { libraryDate, libraryTitles, type LibraryResult } from './chart-library-data';
import type { SelectedResult } from '../conversation/archive';

type Saved = { id: string; technique: string; source_status: string;
  result: SavedCalculation | Derived | SynastryData };

/** Mount with the immutable result ID as key; reads never resolve a newer active result. */
export function ChartLibraryReader({ workspace, selected, onBack, onDiscuss, isActiveNatal }: {
  workspace: Workspace; selected: LibraryResult; onBack: () => void; isActiveNatal: boolean;
  onDiscuss: (result: SelectedResult, label: string) => void;
}) {
  const [chart, setChart] = useState<Chart | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let current = true;
    setError(false);
    const request = selected.technique === 'natal'
      ? api<Chart>(`charts/${encodeURIComponent(selected.id)}`).then(value => { if (current) setChart(value); })
      : api<Saved>(`advanced-results/${encodeURIComponent(selected.id)}`).then(value => { if (current) setSaved(value); });
    void request.catch(() => { if (current) setError(true); });
    heading.current?.focus();
    return () => { current = false; };
  }, [selected.id, selected.technique, attempt]);
  const people = selected.people.map(person => ({ ...person, active_chart_id: null }));
  if (saved && (selected.technique === 'midpoint_composite' || selected.technique === 'uncorrected_davison')) {
    return <RelationshipDerivedView workspace={workspace} people={people} onClose={onBack}
      savedResult={{ ...saved.result as Derived, id: saved.id, source_status: saved.source_status }} />;
  }
  if (saved && selected.technique === 'synastry_overlay') {
    return <SynastryView workspace={workspace} people={people} onClose={onBack}
      savedResult={{ ...saved.result as SynastryData, id: saved.id, source_status: saved.source_status }} />;
  }
  return <section className="library-reader" aria-label="Saved chart reader" data-result-id={selected.id}>
    <button type="button" onClick={onBack}>← Back to chart library</button>
    <div className={selected.technique === 'natal' ? 'profile-chart-heading' : undefined}><div>
      <h2 ref={heading} tabIndex={-1}>{selected.technique === 'natal' ? isActiveNatal ? 'Current birth chart' : 'Saved birth chart' : libraryTitles[selected.technique]}</h2>
      {selected.technique === 'natal' && <p>{libraryDate(selected)} · {selected.date ? `saved birth time ${selected.date.slice(11, 16)}` : 'birth time unknown'}.</p>}
    </div></div>
    {error ? <div role="alert"><p>This saved result could not be loaded. Nothing was recalculated.</p>
      <button type="button" onClick={() => setAttempt(n => n + 1)}>Retry saved result</button></div> :
      !chart && !saved && <p role="status">Loading saved result…</p>}
    {chart && <div className="profile-active-chart">
      {chart.result.natal ? <NatalChart chart={chart} allowMotion /> :
        <p role="status">{chart.source_status !== 'current' && 'Historical source. '}This saved version contains only solar information. A full natal wheel is unavailable.</p>}</div>}
    {saved && <><SavedResultDetail result={saved.result as SavedCalculation} resultId={saved.id}
      technique={saved.technique} sourceStatus={saved.source_status} />
      <button type="button" onClick={() => onDiscuss({ result_id: saved.id, event_index: null },
        libraryTitles[selected.technique])}>Discuss this saved result</button></>}
  </section>;
}
