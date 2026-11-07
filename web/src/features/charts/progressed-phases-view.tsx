import { useEffect, useState, type FormEvent } from 'react';
import type { Workspace } from '../../shared/api';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import { zodiac } from './natal';
import { SymbolicComparisonWheel } from './symbolic-comparison-wheel';
import { unavailableCalculation } from './advanced-result-status';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import type { Person } from '../people/people';

type Event = { phase: string; cycle_index: number; effective_utc: string;
  mapped_ephemeris_utc: string; progressed_sun_degrees: number;
  progressed_moon_degrees: number; separation_degrees: number;
  angular_residual_degrees: number };
type PhaseResult = { id?: string; status: string; source_status?: string;
  chart_id: string; person_id: string; source_birth_id: string; method_version: string;
  progression_method_version: string; profile_id: string; profile_revision: number;
  engine_version: string; ephemeris_sha256: Record<string, string>;
  natal_phase_degrees: number; natal_positions: { id: string; longitude_degrees: number }[];
  phase_policy: string; phase_targets_degrees: Record<string, number>;
  window_utc: string[]; window_end_inclusive: boolean; events: Event[] };
const names: Record<string, string> = { new: 'Progressed New Moon', first_quarter: 'Progressed first quarter',
  full: 'Progressed Full Moon', last_quarter: 'Progressed last quarter' };

function downloadCsv(result: PhaseResult) {
  const lines = ['effective_utc,mapped_ephemeris_utc,phase,cycle_index,progressed_sun_degrees,progressed_moon_degrees,source_chart_id,method_version',
    ...result.events.map(item => [item.effective_utc, item.mapped_ephemeris_utc,
      item.phase, item.cycle_index, item.progressed_sun_degrees.toFixed(6),
      item.progressed_moon_degrees.toFixed(6), result.chart_id, result.method_version].join(','))];
  const url = URL.createObjectURL(new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `kat-progressed-phases-${result.id || 'preview'}.csv`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ProgressedPhasesView({ workspace, people, onClose, initialPersonId }: {
  workspace: Workspace; people: Person[]; onClose: () => void; initialPersonId?: string;
}) {
  const [personId, setPersonId] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (clock.today) { setStart(current => current || clock.today); setEnd(current => current || utcDays(clock.today, 30 * 365)); }
  }, [clock.today]);
  const { result, history, busy, error, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<PhaseResult, { id: string; first_utc?: string; created_at: string }>(workspace);
  const intent = useManualChartIntent(result);
  const [selectedIndex, setSelectedIndex] = useState(0);
  useEffect(() => { if (initialPersonId) choosePerson(initialPersonId); }, [initialPersonId]);
  function choosePerson(id: string) {
    setPersonId(id);
    loadPerson(id, 'progressed_lunar_phases', 'Saved phase searches could not be listed.');
  }
  async function calculate(event: FormEvent) {
    event.preventDefault(); intent.revealResult();
    await saveResult(personId, 'progressed_lunar_phases', {
      start_utc: `${start}T00:00:00+00:00`, end_utc: `${end}T00:00:00+00:00`,
    }, {
      prefix: 'phase', onResult: () => setSelectedIndex(0),
      firstRow: (data, id) => ({ id, first_utc: data.events[0]?.effective_utc,
        created_at: new Date().toISOString() }),
      unavailable: status => unavailableCalculation('Progressed phase search', status),
      invalid: 'Choose a positive effective UTC interval after birth, at most 40 years long. No phase search was saved.',
      uncertain: 'Saving was not confirmed. Retry the same request or check saved phase searches before starting another.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open saved progressed phase search.',
      () => setSelectedIndex(0));
  }
  const chosen = result?.events[selectedIndex];
  return <section className="advanced-view" aria-label="Progressed lunar phase cycles">
    <div className="transit-heading"><div><span className="eyebrow">SYMBOLIC MOON–SUN CYCLE</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Progressed lunar phases</h1><p>Find symbolic New, first-quarter, Full and last-quarter dates using the secondary Moon–Sun separation, not the real sky.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select required value={personId} onChange={event => void choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.filter(person => person.active_chart_id).map(person =>
          <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>From (effective UTC)<input type="date" required min="1900-01-01" max="2099-12-31" value={start}
        onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Until (UTC, excluded)<input type="date" required min="1900-01-01" max="2099-12-31" value={end}
        onChange={event => { change(); setEnd(event.target.value); }} /></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose effective UTC dates yourself.</p>}
      <button type="submit" className="primary" disabled={busy || !personId}>{busy ? 'Searching…' : 'Find progressed phases'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved progressed phase searches"><h2>Saved phase searches</h2>
      {history.map(row => <button key={row.id} type="button" onClick={() => void openSaved(row.id)}>
        Open saved phases · {(row.first_utc || row.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p role="alert" className="error">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Progressed phase result">
      {result.source_status === 'historical' && <p role="status" className="error">Historical source natal. These archived symbolic dates were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>Symbolic phases · {people.find(person => person.id === result.person_id)?.name || 'saved person'}</h2>
      <p>Cycle indices count progressed New Moons from the exact supplied birth instant. The effective date is a lived-time label; each mapped ephemeris date is a different symbolic instant, not an actual New or Full Moon.</p>
      {result.events.length ? <div className="transit-tables"><table><caption>Progressed lunar phase dates · {result.events.length} exact crossings</caption>
        <thead><tr><th scope="col">Cycle</th><th scope="col">Phase</th><th scope="col">Effective date (UTC)</th><th scope="col">Mapped ephemeris UTC</th><th scope="col">Sun</th><th scope="col">Moon</th><th scope="col">View</th></tr></thead>
        <tbody>{result.events.map((item, index) => <tr key={`${item.phase}-${item.effective_utc}`}>
          <th scope="row">{item.cycle_index}</th><td>{names[item.phase] || item.phase}</td><td>{item.effective_utc}</td>
          <td>{item.mapped_ephemeris_utc}</td><td>{zodiac(item.progressed_sun_degrees)}</td>
          <td>{zodiac(item.progressed_moon_degrees)}</td><td><button type="button" onClick={() => setSelectedIndex(index)}
            aria-pressed={selectedIndex === index}>View phase chart</button></td></tr>)}</tbody></table></div> :
        <p>No selected phase boundary crossed in this half-open interval; other periods may have them.</p>}
      {chosen && <div role="region" aria-label="Selected symbolic phase chart">
        <h3>{names[chosen.phase]} · cycle {chosen.cycle_index}</h3>
        <p>Effective {chosen.effective_utc}; mapped {chosen.mapped_ephemeris_utc}. Moon–Sun separation {(chosen.phase === 'new' ?
          Math.min(chosen.separation_degrees, 360 - chosen.separation_degrees) :
          chosen.separation_degrees).toFixed(5)}°; root residual {chosen.angular_residual_degrees.toFixed(6)}° is numerical precision only.</p>
        <SymbolicComparisonWheel positions={[{ id: 'sun', longitude_degrees: chosen.progressed_sun_degrees },
          { id: 'moon', longitude_degrees: chosen.progressed_moon_degrees }]}
          natalPositions={result.natal_positions} label="Phase" description="Only progressed Sun and Moon at the mapped symbolic ephemeris instant, compared with their saved natal degrees."
          stem={`kat-progressed-phase-${result.id || 'preview'}-${selectedIndex}`} provenance={{
            chart_id: result.chart_id, source_birth_id: result.source_birth_id,
            method_version: result.method_version, progression_method_version: result.progression_method_version,
            phase: chosen.phase, cycle_index: chosen.cycle_index,
            effective_utc: chosen.effective_utc, mapped_ephemeris_utc: chosen.mapped_ephemeris_utc,
            phase_targets_degrees: result.phase_targets_degrees,
            progressed_sun_degrees: chosen.progressed_sun_degrees,
            progressed_moon_degrees: chosen.progressed_moon_degrees,
            angular_residual_degrees: chosen.angular_residual_degrees,
            natal_positions: result.natal_positions, source_status: result.source_status,
            engine_version: result.engine_version, ephemeris_sha256: result.ephemeris_sha256,
            profile_id: result.profile_id, profile_revision: result.profile_revision,
          }} />
      </div>}
      <button type="button" onClick={() => downloadCsv(result)}>Download progressed phase dates CSV</button>
      <p className="transit-scroll-hint">Swipe the event table and wheel sideways on narrow screens.</p>
    </div>}
  </section>;
}
