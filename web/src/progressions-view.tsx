import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type Workspace } from './api';
import { useApplicationUtcDate, useManualChartIntent } from './manual-chart-intent';
import { bodyLabel } from './chart-symbols';
import { zodiac } from './natal';
import { SymbolicComparisonWheel } from './symbolic-comparison-wheel';
import { ProgressedMcTimeline } from './progressed-mc-timeline';
import type { Person } from './people';

type Position = { id: string; longitude_degrees: number; speed_degrees_per_symbolic_day?: number;
  retrograde_at_mapped_time?: boolean };
type Contact = { first: string; second: string; kind: string; orb_degrees: number };
type NatalAspect = { a_body_id: string; b_body_id: string; aspect: string; orb_degrees: number };
type Progression = { id?: string; status: string; source_status?: string; chart_id: string;
  method_version: string; source_birth_id: string; effective_utc: string;
  mapped_ephemeris_utc: string; anniversary_bracket_utc: string[]; age_completed_years: number;
  anniversary_fraction: number; positions: Position[]; natal_positions: Position[];
  natal_aspects: NatalAspect[]; natal_aspects_total: number; natal_aspects_truncated: boolean;
  natal_mc_degrees: number | null; mcp_degrees: number | null; mc_status: string;
  mcp_contacts: Contact[]; mcr_contacts: Contact[]; ephemeris_sha256: Record<string, string>;
  profile_id: string; profile_revision: number; engine_version: string };



export function ProgressionsView({ workspace, people, onClose }: {
  workspace: Workspace; people: Person[]; onClose: () => void;
}) {
  const [personId, setPersonId] = useState('');
  const [date, setDate] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => { if (clock.today) setDate(current => current || clock.today); }, [clock.today]);
  const [result, setResult] = useState<Progression | null>(null);
  const intent = useManualChartIntent(result);
  const [history, setHistory] = useState<{ id: string; created_at: string; first_utc?: string }[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef<{ id: string; key: string } | null>(null);
  const version = useRef(0);
  useEffect(() => () => { version.current++; }, []);
  function change() { version.current++; setResult(null); setError(''); setBusy(false); request.current = null; }
  async function choosePerson(id: string) {
    change(); setPersonId(id); setHistory([]);
    const current = version.current;
    if (!id) return;
    try {
      const saved = await api<{ results: { id: string; created_at: string; first_utc?: string }[] }>(
        `advanced-results?person_id=${encodeURIComponent(id)}&technique=secondary_progression`);
      if (current === version.current) setHistory(saved.results);
    } catch { if (current === version.current) setError('Saved progressions could not be listed. Calculation remains available.'); }
  }
  async function calculate(event: FormEvent) {
    event.preventDefault();
    const current = ++version.current;
    setBusy(true); setResult(null); setError(''); intent.revealResult();
    const key = `${personId}:${date}`;
    const id = request.current?.key === key ? request.current.id : `progression-${crypto.randomUUID()}`;
    request.current = { id, key };
    try {
      const calculated = await api<Progression>('advanced-results', workspace.csrf, 'POST', {
        id, person_id: personId, technique: 'secondary_progression',
        parameters: { effective_utc: `${date}T00:00:00+00:00` },
      });
      if (current !== version.current) return;
      if (calculated.status === 'supported') {
        setResult(calculated);
        setHistory(rows => rows.some(row => row.id === id) ? rows : [
          { id, created_at: new Date().toISOString(), first_utc: calculated.effective_utc }, ...rows]);
      } else setError(calculated.status === 'no_active_natal' ? 'Choose a person with a current generated natal.' :
        'This source cannot supply an exact-time progression. Nothing was inferred from an uncertain or stale natal.');
    } catch (cause) { if (current === version.current) {
      if (cause instanceof ApiError && cause.status === 400) {
        request.current = null;
        setError('Choose a supported effective UTC date after the saved birth instant. No progression was saved.');
      } else setError('Saving was not confirmed. Retry the same request or check saved progressions before starting another.');
    } }
    finally { if (current === version.current) setBusy(false); }
  }
  async function openSaved(id: string) {
    const current = ++version.current;
    setResult(null); setError(''); setBusy(false); intent.revealResult();
    try {
      const saved = await api<{ result: Progression; source_status: string }>(`advanced-results/${encodeURIComponent(id)}`);
      if (current === version.current) setResult({ ...saved.result, id, source_status: saved.source_status });
    } catch { if (current === version.current) setError('Could not open the archived progression.'); }
  }
  return <section className="advanced-view" aria-label="Secondary progression chart">
    <div className="transit-heading"><div><span className="eyebrow">SYMBOLIC TIMING</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Secondary progressions</h1><p>One ephemeris day per lived UTC anniversary year. This is not the actual sky at the effective date.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select value={personId} required onChange={event => void choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.filter(item => item.active_chart_id).map(item =>
          <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Effective date (UTC midnight)<input type="date" required min="1900-01-01" max="2099-12-31" value={date}
        onChange={event => { change(); setDate(event.target.value); }} /></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose an effective UTC date yourself.</p>}
      <button type="submit" className="primary" disabled={busy || !personId}>{busy ? 'Calculating…' : 'Calculate progression'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved progressions"><h2>Saved progressions</h2>
      {history.map(item => <button key={item.id} type="button" onClick={() => void openSaved(item.id)}>
        Open saved progression · {(item.first_utc || item.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p role="alert" className="error">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Progression result">
      {result.source_status === 'historical' && <p role="status" className="error">Historical progression: the source natal is no longer current. These archived positions were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>Progressed {people.find(item => item.id === personId)?.name || 'person'} · {result.effective_utc.slice(0, 10)} UTC</h2>
      <p>Symbolic positions for age {result.age_completed_years}, not the sky at this date.</p>
      <SymbolicComparisonWheel label="Progressed" description="Planets are sampled at the symbolic mapped ephemeris date; no progressed houses or Ascendant are asserted."
        positions={result.positions} natalPositions={result.natal_positions}
        stem={`kat-progression-${result.id || 'preview'}`} provenance={{
          method_version: result.method_version, chart_id: result.chart_id,
          source_birth_id: result.source_birth_id, effective_utc: result.effective_utc,
          mapped_ephemeris_utc: result.mapped_ephemeris_utc,
          anniversary_bracket_utc: result.anniversary_bracket_utc,
          age_completed_years: result.age_completed_years,
          anniversary_fraction: result.anniversary_fraction, mc_status: result.mc_status,
          mcp_degrees: result.mcp_degrees, natal_mc_degrees: result.natal_mc_degrees,
          positions: result.positions, natal_positions: result.natal_positions,
          source_status: result.source_status, engine_version: result.engine_version,
          ephemeris_sha256: result.ephemeris_sha256, profile_id: result.profile_id,
          profile_revision: result.profile_revision,
        }} />
      {(result.mc_status !== 'supported' || result.mcp_degrees === null || result.natal_mc_degrees === null) &&
        <p role="status">MCp/MCr are unavailable ({result.mc_status}). No axis or house substitute was invented; progressed planets remain available.</p>}
      <details className="chart-supporting-data"><summary>Positions, natal aspects and MC contacts</summary>
      <p>Mapped ephemeris date: {result.mapped_ephemeris_utc}. Completed anniversary years: {result.age_completed_years}, fraction {result.anniversary_fraction.toFixed(6)}.</p>
      <div className="transit-tables"><table><caption>Progressed planetary positions · tropical longitude</caption>
        <thead><tr><th scope="col">Planet</th><th scope="col">Progressed degree</th><th scope="col">Motion at mapped instant</th></tr></thead>
        <tbody>{result.positions.map(item => <tr key={item.id}><th scope="row">{bodyLabel(item.id)}</th>
          <td>{zodiac(item.longitude_degrees)}</td><td>{item.retrograde_at_mapped_time ? 'Retrograde' : 'Direct'} · {item.speed_degrees_per_symbolic_day?.toFixed(5)}°/symbolic day</td></tr>)}</tbody></table></div>
      <div className="transit-tables"><table><caption>Progressed planets compared with saved natal planets · {result.natal_aspects_total} aspects, {result.natal_aspects.length} shown</caption>
        <thead><tr><th scope="col">Progressed</th><th scope="col">Aspect</th><th scope="col">Natal</th><th scope="col">Orb</th></tr></thead>
        <tbody>{result.natal_aspects.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.a_body_id)}</th>
          <td>{item.aspect}</td><td>{bodyLabel(item.b_body_id)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
        {result.natal_aspects_truncated && <p>Only the first 24 closest aspects are shown; more were calculated.</p>}</div>
      {result.mc_status === 'supported' && result.mcp_degrees !== null && result.natal_mc_degrees !== null ? <>
        <p>Fixed natal astronomical MC: {zodiac(result.natal_mc_degrees)}. Calendar-bracket progressed MC (MCp): {zodiac(result.mcp_degrees)}. No progressed Ascendant or houses are claimed.</p>
        {([['MCp · progressed MC to natal planets', result.mcp_contacts],
           ['MCr · progressed planets to fixed natal MC', result.mcr_contacts]] as const).map(([title, contacts]) =>
          <div className="transit-tables" key={title}><table><caption>{title} · within declared natal orbs</caption>
            <thead><tr><th scope="col">From</th><th scope="col">Aspect</th><th scope="col">To</th><th scope="col">Orb</th></tr></thead>
            <tbody>{contacts.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.first)}</th>
              <td>{item.kind}</td><td>{bodyLabel(item.second)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
            {!contacts.length && <p>No contacts within declared orbs at this date; no exact event date is implied.</p>}</div>)}</> :
        null}
      <p className="transit-scroll-hint">Swipe tables sideways on narrow screens. MCp and MCr are separate symbolic branches, not transiting planets or an event forecast.</p>
      </details>
    </div>}
    {personId && <details className="chart-supporting-data progressed-search">
      <summary>Search exact progressed MC dates · separate method</summary>
      <ProgressedMcTimeline key={personId} workspace={workspace} personId={personId} />
    </details>}
  </section>;
}
