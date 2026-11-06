import { useEffect, useState, type FormEvent } from 'react';
import type { Workspace } from '../../shared/api';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import { unavailableCalculation } from './advanced-result-status';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import { bodyLabel } from './chart-symbols';
import { zodiac } from './natal';
import { SymbolicComparisonWheel } from './symbolic-comparison-wheel';
import type { Person } from '../people/people';

type Contact = { sky_body: string; longitude_degrees: number; natal_target: string;
  natal_longitude_degrees: number; aspect: string; orb_degrees: number; in_orb: boolean };
type Lunation = { phase: string; instant_utc: string; sun_degrees: number;
  moon_degrees: number; angular_residual_degrees: number; contacts: Contact[] };
type Eclipse = { family: string; eclipse_type: string; maximum_utc: string;
  linked_syzygy_utc: string; sun_degrees_at_maximum: number;
  moon_degrees_at_maximum: number; visibility: string; contacts_at_maximum: Contact[] };
type SkyResult = { id?: string; status: string; source_status?: string; chart_id: string;
  person_id: string; source_birth_id: string; method_version: string;
  profile_id: string; profile_revision: number; engine_version: string;
  ephemeris_sha256: Record<string, string>; natal_target: string;
  natal_target_degrees: number; aspect: string; orb_degrees: number;
  window_utc: string[]; lunations: Lunation[]; eclipses: Eclipse[] };
const bodies = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn',
  'uranus', 'neptune', 'pluto', 'ascendant', 'midheaven', 'chiron'];
const aspects = ['conjunction', 'opposition', 'trine', 'square', 'sextile'];
const utcLabel = (instant: string) => `${new Date(instant).toLocaleString('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
})} UTC`;

function downloadCsv(result: SkyResult) {
  const lines = ['kind,phase_or_eclipse_type,utc,linked_syzygy_utc,sun_degrees,moon_degrees,source_chart_id,natal_target,aspect,method_version',
    ...result.lunations.map(item => ['syzygy', item.phase, item.instant_utc, '',
      item.sun_degrees.toFixed(6), item.moon_degrees.toFixed(6), result.chart_id,
      result.natal_target, result.aspect, result.method_version].join(',')),
    ...result.eclipses.map(item => [`${item.family}_global_eclipse`, item.eclipse_type, item.maximum_utc,
      item.linked_syzygy_utc, item.sun_degrees_at_maximum.toFixed(6),
      item.moon_degrees_at_maximum.toFixed(6), result.chart_id,
      result.natal_target, result.aspect, result.method_version].join(','))];
  const url = URL.createObjectURL(new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `kat-actual-lunations-${result.id || 'preview'}.csv`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function LunationsView({ workspace, people, onClose }: {
  workspace: Workspace; people: Person[]; onClose: () => void;
}) {
  const [personId, setPersonId] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (clock.today) { setStart(current => current || clock.today); setEnd(current => current || utcDays(clock.today, 60)); }
  }, [clock.today]);
  const [target, setTarget] = useState('sun');
  const [aspect, setAspect] = useState('conjunction');
  const { result, history, error, busy, setError, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<SkyResult, { id: string; first_utc?: string; created_at: string }>(workspace);
  const intent = useManualChartIntent(result);
  const [selected, setSelected] = useState<{ kind: 'syzygy' | 'eclipse'; index: number }>({ kind: 'syzygy', index: 0 });
  function choosePerson(id: string) {
    setPersonId(id);
    loadPerson(id, 'actual_lunations_eclipses', 'Saved real-sky searches could not be listed.');
  }
  async function calculate(event: FormEvent) {
    event.preventDefault();
    const duration = (Date.parse(end) - Date.parse(start)) / 86400_000;
    if (!Number.isFinite(duration) || duration <= 0 || duration > 732) {
      setError('Choose an end date after the start, within 732 days. Your dates are still here.'); return;
    }
    intent.revealResult();
    await saveResult(personId, 'actual_lunations_eclipses', {
      start_utc: `${start}T00:00:00+00:00`, end_utc: `${end}T00:00:00+00:00`,
      natal_target: target, aspect,
    }, {
      prefix: 'actual-lunation', onResult: () => setSelected({ kind: 'syzygy', index: 0 }),
      firstRow: (data, id) => ({ id, first_utc: data.lunations[0]?.instant_utc,
        created_at: new Date().toISOString() }),
      unavailable: status => unavailableCalculation('Selected natal contact', status),
      invalid: 'Choose a positive UTC interval of at most 732 days and a supported natal target. No sky search was saved.',
      uncertain: 'Saving was not confirmed. Retry the same request or check saved sky searches before starting another.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open saved real-sky search.',
      () => setSelected({ kind: 'syzygy', index: 0 }));
  }
  const chosen = selected.kind === 'syzygy' ? result?.lunations[selected.index] : result?.eclipses[selected.index];
  const chosenInstant = chosen && ('instant_utc' in chosen ? chosen.instant_utc : chosen.maximum_utc);
  const sun = chosen && ('sun_degrees' in chosen ? chosen.sun_degrees : chosen.sun_degrees_at_maximum);
  const moon = chosen && ('moon_degrees' in chosen ? chosen.moon_degrees : chosen.moon_degrees_at_maximum);
  const contacts = chosen && ('contacts' in chosen ? chosen.contacts : chosen.contacts_at_maximum);
  return <section className="advanced-view" aria-label="Actual lunations and global eclipses">
    <div className="transit-heading"><div><span className="eyebrow">ACTUAL SKY · GLOBAL DOES NOT MEAN LOCALLY VISIBLE</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Lunations and eclipses</h1><p>See New and Full Moons, plus any global eclipses in the selected period. A global eclipse may not be visible where you are.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select value={personId} required onChange={event => void choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.filter(person => person.active_chart_id).map(person =>
          <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>From<input type="date" required min="1900-01-01" max="2099-12-31" value={start}
        onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Until (not included)<input type="date" required min="1900-01-01" max="2099-12-31" value={end}
        onChange={event => { change(); setEnd(event.target.value); }} /></label>
      <label>Natal target<select value={target} onChange={event => { change(); setTarget(event.target.value); }}>
        {bodies.map(item => <option key={item} value={item}>{bodyLabel(item)}</option>)}</select></label>
      <label>Contact aspect<select value={aspect} onChange={event => { change(); setAspect(event.target.value); }}>
        {aspects.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose UTC dates yourself.</p>}
      <button className="primary" type="submit" disabled={busy || !personId}>{busy ? 'Searching…' : 'Find lunations and eclipses'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved real-sky searches"><h2>Saved sky searches</h2>
      {history.map(row => <button key={row.id} type="button" onClick={() => void openSaved(row.id)}>
        Open saved sky search · {(row.first_utc || row.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p className="error" role="alert">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Actual lunations result">
      {result.source_status === 'historical' && <p role="status" className="error">Historical natal source. Archived contacts were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>Actual sky · {people.find(person => person.id === result.person_id)?.name || 'saved person'}</h2>
      <p>Geocentric syzygy times and global eclipse maxima are distinct; a global eclipse is not necessarily visible from your location. Contact orbs compare the actual Sun and Moon at each labelled instant with the selected natal {bodyLabel(result.natal_target)} ({zodiac(result.natal_target_degrees)}), using the saved {result.aspect} orb of {result.orb_degrees}°.</p>
      {result.lunations.length ? <div className="transit-tables"><table><caption>Actual geocentric New and Full Moon syzygies · {result.lunations.length}</caption>
        <thead><tr><th scope="col">Phase</th><th scope="col">Syzygy UTC</th><th scope="col">Sun</th><th scope="col">Moon</th><th scope="col">View</th></tr></thead>
        <tbody>{result.lunations.map((item, index) => <tr key={item.instant_utc}>
          <th scope="row">{item.phase === 'new' ? 'New Moon' : 'Full Moon'}</th><td>{utcLabel(item.instant_utc)}</td>
          <td>{zodiac(item.sun_degrees)}</td><td>{zodiac(item.moon_degrees)}</td>
          <td><button type="button" aria-pressed={selected.kind === 'syzygy' && selected.index === index}
            onClick={() => setSelected({ kind: 'syzygy', index })}>View syzygy</button></td></tr>)}</tbody></table></div> :
        <p>No New/Full Moon syzygy in the selected half-open window.</p>}
      {result.eclipses.length ? <div className="transit-tables"><table><caption>Swiss global solar and lunar eclipse maxima · {result.eclipses.length}</caption>
        <thead><tr><th scope="col">Family</th><th scope="col">Class</th><th scope="col">Global maximum UTC</th><th scope="col">Linked syzygy UTC</th><th scope="col">View</th></tr></thead>
        <tbody>{result.eclipses.map((item, index) => <tr key={item.maximum_utc}>
          <th scope="row">{item.family === 'solar' ? 'Solar eclipse' : 'Lunar eclipse'}</th>
          <td>{item.eclipse_type}</td><td>{utcLabel(item.maximum_utc)}</td><td>{utcLabel(item.linked_syzygy_utc)}</td>
          <td><button type="button" aria-pressed={selected.kind === 'eclipse' && selected.index === index}
            onClick={() => setSelected({ kind: 'eclipse', index })}>View global eclipse</button></td></tr>)}</tbody></table></div> :
        <p>No Swiss-validated global eclipse in the selected half-open window. No eclipse was guessed from lunar-node distance.</p>}
      {chosen && chosenInstant && sun !== undefined && moon !== undefined && contacts && <div role="region" aria-label="Selected actual-sky chart">
        <h3>{selected.kind === 'eclipse' ? `Global ${'family' in chosen ? chosen.family : ''} eclipse maximum` :
          `${'phase' in chosen && chosen.phase === 'new' ? 'New' : 'Full'} Moon syzygy`} · {utcLabel(chosenInstant)}</h3>
        <p>Actual Sun {zodiac(sun)}; actual Moon {zodiac(moon)}. An eclipse maximum can differ from its geocentric syzygy. Global type is not a location-specific observation.</p>
        <SymbolicComparisonWheel frame="actual" positions={[{ id: 'sun', longitude_degrees: sun },
          { id: 'moon', longitude_degrees: moon }]}
          natalPositions={[{ id: result.natal_target, longitude_degrees: result.natal_target_degrees }]}
          label="Actual sky" description="Sun and Moon at the selected actual UTC instant, with only the selected natal target on the inner ring."
          stem={`kat-real-sky-${result.id || 'preview'}-${selected.kind}-${selected.index}`} provenance={{
            chart_id: result.chart_id, source_birth_id: result.source_birth_id,
            method_version: result.method_version, event_kind: selected.kind,
            instant_utc: chosenInstant, eclipse_type: 'eclipse_type' in chosen ? chosen.eclipse_type : null,
            linked_syzygy_utc: 'linked_syzygy_utc' in chosen ? chosen.linked_syzygy_utc : null,
            global_visibility: 'not_calculated_for_location',
            sun_degrees: sun, moon_degrees: moon,
            natal_target: result.natal_target, natal_target_degrees: result.natal_target_degrees,
            aspect: result.aspect, contacts, source_status: result.source_status,
            engine_version: result.engine_version, ephemeris_sha256: result.ephemeris_sha256,
            profile_id: result.profile_id, profile_revision: result.profile_revision,
          }} />
        <div className="transit-tables"><table><caption>Contacts at selected {selected.kind === 'eclipse' ? 'maximum' : 'syzygy'} · {bodyLabel(result.natal_target)}</caption>
          <thead><tr><th scope="col">Sky body</th><th scope="col">Aspect</th><th scope="col">Orb</th><th scope="col">Within saved orb?</th></tr></thead>
          <tbody>{contacts.map(item => <tr key={item.sky_body}><th scope="row">{bodyLabel(item.sky_body)}</th>
            <td>{item.aspect}</td><td>{item.orb_degrees.toFixed(3)}°</td><td>{item.in_orb ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div>
      </div>}
      <button type="button" onClick={() => downloadCsv(result)}>Download lunations and eclipses CSV</button>
      <p className="transit-scroll-hint">Swipe tables and wheel sideways on narrow screens. Global results do not establish local eclipse visibility.</p>
    </div>}
  </section>;
}
