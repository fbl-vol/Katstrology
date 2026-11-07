import { useEffect, useState, type FormEvent } from 'react';
import type { Workspace } from '../../shared/api';
import { useApplicationUtcDate, useManualChartIntent } from './manual-chart-intent';
import { bodyLabel } from './chart-symbols';
import { zodiac } from './natal';
import { SymbolicComparisonWheel } from './symbolic-comparison-wheel';
import { unavailableCalculation } from './advanced-result-status';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import type { Person } from '../people/people';

type Direction = { id: string; longitude_degrees: number; source_longitude_degrees: number;
  point_kind: string };
type Aspect = { a_body_id: string; b_body_id: string; aspect: string; orb_degrees: number };
type SolarArcResult = { id?: string; status: string; source_status?: string; chart_id: string;
  method_version: string; source_birth_id: string; effective_utc: string;
  mapped_ephemeris_utc: string; anniversary_bracket_utc: string[];
  age_completed_years: number; anniversary_fraction: number; arc_degrees: number;
  natal_sun_degrees: number; progressed_sun_degrees: number; arc_policy: string;
  positions: Direction[]; natal_positions: { id: string; longitude_degrees: number }[];
  axis_status: string; directed_natal_aspects: Aspect[];
  directed_natal_aspects_total: number; directed_natal_aspects_truncated: boolean;
  ephemeris_sha256: Record<string, string>; profile_id: string;
  profile_revision: number; engine_version: string };

export function SolarArcView({ workspace, people, onClose, initialPersonId }: {
  workspace: Workspace; people: Person[]; onClose: () => void; initialPersonId?: string;
}) {
  const [personId, setPersonId] = useState('');
  const [date, setDate] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => { if (clock.today) setDate(current => current || clock.today); }, [clock.today]);
  const { result, history, error, busy, change, setError,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<SolarArcResult, { id: string; first_utc?: string; created_at: string }>(workspace);
  const intent = useManualChartIntent(result);
  useEffect(() => { if (initialPersonId) choosePerson(initialPersonId); }, [initialPersonId]);
  function choosePerson(id: string) {
    setPersonId(id);
    loadPerson(id, 'true_solar_arc', 'Could not list saved solar arcs.');
  }
  async function calculate(event: FormEvent) {
    event.preventDefault(); intent.revealResult();
    await saveResult(personId, 'true_solar_arc', { effective_utc: `${date}T00:00:00+00:00` }, {
      prefix: 'solar-arc',
      firstRow: (data, id) => ({ id, first_utc: data.effective_utc, created_at: new Date().toISOString() }),
      unavailable: status => unavailableCalculation('Solar-arc directions', status),
      invalid: 'Choose a supported effective UTC date after the saved birth instant. No solar arc was saved.',
      uncertain: 'Saving was not confirmed. Retry the same request or check saved solar arcs before starting another.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open saved solar arc.');
  }
  return <section className="advanced-view" aria-label="True solar-arc directions">
    <div className="transit-heading"><div><span className="eyebrow">SYMBOLIC DIRECTIONS</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Solar-arc directions</h1><p>Move every natal planet and qualified axis by the actual secondary progressed Sun's forward displacement, not by a fixed 1° per year.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select value={personId} required onChange={event => void choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.filter(person => person.active_chart_id).map(person =>
          <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>Effective date (UTC midnight)<input type="date" required min="1900-01-01" max="2099-12-31" value={date}
        onChange={event => { change(); setDate(event.target.value); }} /></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose an effective UTC date yourself.</p>}
      <button className="primary" type="submit" disabled={busy || !personId}>{busy ? 'Calculating…' : 'Calculate solar arc'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved solar arcs"><h2>Saved solar arcs</h2>
      {history.map(row => <button key={row.id} type="button" onClick={() => void openSaved(row.id)}>
        Open saved solar arc · {(row.first_utc || row.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p className="error" role="alert">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Solar-arc result">
      {result.source_status === 'historical' && <p role="status" className="error">Historical source natal. Archived directions were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>Solar arc · {people.find(person => person.id === personId)?.name || 'saved person'} · {result.effective_utc.slice(0, 10)} UTC</h2>
      <p>True forward arc {result.arc_degrees.toFixed(5)}°. Saved natal Sun {zodiac(result.natal_sun_degrees)}; directly progressed Sun {zodiac(result.progressed_sun_degrees)} at symbolic ephemeris instant {result.mapped_ephemeris_utc}. Age {result.age_completed_years} + {result.anniversary_fraction.toFixed(6)} anniversary years.</p>
      <p>These directed points are symbolic, not a simultaneous sky. They do not show houses, motion or retrograde state. Natal axes: {result.axis_status}.</p>
      <SymbolicComparisonWheel positions={result.positions} natalPositions={result.natal_positions}
        label="Directed" description="Each direction is a saved natal degree plus one true forward solar arc. These are not sampled planetary positions or progressed houses."
        stem={`kat-solar-arc-${result.id || 'preview'}`} provenance={{
          method_version: result.method_version, chart_id: result.chart_id,
          source_birth_id: result.source_birth_id, effective_utc: result.effective_utc,
          mapped_ephemeris_utc: result.mapped_ephemeris_utc,
          anniversary_bracket_utc: result.anniversary_bracket_utc,
          age_completed_years: result.age_completed_years, anniversary_fraction: result.anniversary_fraction,
          arc_degrees: result.arc_degrees, arc_policy: result.arc_policy,
          natal_sun_degrees: result.natal_sun_degrees,
          progressed_sun_degrees: result.progressed_sun_degrees,
          positions: result.positions, natal_positions: result.natal_positions,
          axis_status: result.axis_status, source_status: result.source_status,
          engine_version: result.engine_version, ephemeris_sha256: result.ephemeris_sha256,
          profile_id: result.profile_id, profile_revision: result.profile_revision,
        }} />
      <details className="chart-supporting-data"><summary>Directed positions and natal aspects · {result.directed_natal_aspects_total} aspects</summary>
      <div className="transit-tables"><table><caption>Solar-arc directions · original natal and directed longitude</caption>
        <thead><tr><th scope="col">Natal point</th><th scope="col">Original degree</th><th scope="col">Directed degree</th></tr></thead>
        <tbody>{result.positions.map(point => <tr key={point.id}><th scope="row">{bodyLabel(point.id)}</th>
          <td>{zodiac(point.source_longitude_degrees)}</td><td>{zodiac(point.longitude_degrees)}</td></tr>)}</tbody></table></div>
      <div className="transit-tables"><table><caption>Directed-to-natal aspects · {result.directed_natal_aspects_total} total, {result.directed_natal_aspects.length} shown</caption>
        <thead><tr><th scope="col">Directed</th><th scope="col">Aspect</th><th scope="col">Natal</th><th scope="col">Orb</th></tr></thead>
        <tbody>{result.directed_natal_aspects.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.a_body_id)}</th>
          <td>{item.aspect}</td><td>{bodyLabel(item.b_body_id)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
        {result.directed_natal_aspects_truncated && <p>Only the 24 closest aspects are shown; more were calculated.</p>}</div>
      <p className="transit-scroll-hint">Swipe tables and wheel sideways on narrow screens. Directions are not MCp, mean solar arc or transits.</p>
      </details>
    </div>}
  </section>;
}
