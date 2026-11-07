import { useEffect, useState, type FormEvent } from 'react';
import type { Workspace } from '../../shared/api';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import type { Person } from '../people/people';
import { bodyLabel } from './chart-symbols';
import { zodiac } from './natal';

type McResult = { id?: string; status: string; source_status?: string;
  method_version?: string; chart_id?: string; natal_mc_longitude_degrees?: number;
  transit_body_id?: string; aspect?: string; events?: { instant_utc: string; target_degrees: number; tolerance_seconds: number }[];
  window_utc?: string[]; ephemeris_sha256?: Record<string, string> };
const bodies = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto'];
const aspects = ['conjunction', 'opposition', 'square', 'trine', 'sextile'];

export function McTransitsView({ workspace, people, onClose, initialPersonId }: {
  workspace: Workspace; people: Person[]; onClose: () => void; initialPersonId?: string;
}) {
  const [personId, setPersonId] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (clock.today) { setStart(current => current || clock.today); setEnd(current => current || utcDays(clock.today, 30)); }
  }, [clock.today]);
  const [body, setBody] = useState('sun');
  const [aspect, setAspect] = useState('conjunction');
  const { result, history, error, busy, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<McResult, { id: string; first_utc: string; created_at: string }>(workspace);
  const intent = useManualChartIntent(result);
  const person = people.find(item => item.id === personId);
  useEffect(() => { if (initialPersonId) choosePerson(initialPersonId); }, [initialPersonId]);
  function choosePerson(id: string) {
    setPersonId(id);
    loadPerson(id, 'mc_transit', 'Saved timelines could not be listed. Calculation remains available.');
  }
  async function calculate(event: FormEvent) {
    event.preventDefault(); intent.revealResult();
    await saveResult(personId, 'mc_transit', {
      start_utc: `${start}T00:00:00+00:00`, end_utc: `${end}T00:00:00+00:00`,
      transit_body: body, aspect,
    }, {
      prefix: 'mc-transit',
      firstRow: (saved, id) => ({ id, first_utc: saved.events?.[0]?.instant_utc || '',
        created_at: new Date().toISOString() }),
      unavailable: status => status === 'unsupported_natal_mc_houses'
        ? 'The saved natal has no qualified astronomical Midheaven. No tenth-house cusp was substituted.'
        : status === 'no_active_natal' ? 'Choose a person with a current generated natal.'
        : 'The selected natal source cannot provide an exact-time Midheaven. No contact was calculated.',
      invalid: 'Check the UTC interval (up to 732 days), body and aspect, then correct the form. No timeline was saved.',
      uncertain: 'Saving was not confirmed. Retry the same request or check saved timelines before starting another.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open the archived MC timeline.');
  }
  function downloadCsv() {
    if (!result?.events) return;
    const lines = ['UTC instant,Transiting body,Aspect,Natal MC longitude,Contact target longitude,Tolerance seconds',
      ...result.events.map(item => [item.instant_utc, bodyLabel(result.transit_body_id || body),
        result.aspect || aspect, result.natal_mc_longitude_degrees, item.target_degrees,
        item.tolerance_seconds].join(','))];
    const url = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv' }));
    const link = document.createElement('a'); link.href = url;
    link.download = `kat-natal-mc-${result.id || 'timeline'}.csv`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="advanced-view" aria-label="Natal MC transit timeline">
    <div className="transit-heading"><div><span className="eyebrow">MIDHEAVEN TIMING</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Transits to natal MC</h1><p>Find exact transiting-planet longitude contacts to one person’s saved astronomical Midheaven.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select value={personId} required onChange={event => void choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.filter(item => item.active_chart_id).map(item =>
          <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>From (UTC, inclusive)<input type="date" required min="1900-01-01" max="2099-12-31" value={start} onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Until (UTC, exclusive)<input type="date" required min="1900-01-01" max="2099-12-31" value={end} onChange={event => { change(); setEnd(event.target.value); }} /></label>
      <label>Transiting planet<select value={body} onChange={event => { change(); setBody(event.target.value); }}>
        {bodies.map(item => <option key={item} value={item}>{bodyLabel(item)}</option>)}</select></label>
      <label>Exact aspect<select value={aspect} onChange={event => { change(); setAspect(event.target.value); }}>
        {aspects.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose UTC dates yourself.</p>}
      <button type="submit" className="primary" disabled={busy || !personId}>{busy ? 'Calculating…' : 'Calculate MC contacts'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved MC timelines"><h2>Saved MC timelines</h2>
      {history.map(item => <button type="button" key={item.id} onClick={() => void openSaved(item.id)}>
        Open saved timeline · {(item.first_utc || item.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p role="alert" className="error">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="MC contact results">
      {result.source_status === 'historical' && <p role="status" className="error">Historical timeline: the source natal is no longer current. These archived contacts were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>{person?.name || 'Selected person'} · astronomical natal MC {zodiac(result.natal_mc_longitude_degrees || 0)}</h2>
      <p>{result.events?.length || 0} exact {result.aspect} contacts from transiting {bodyLabel(result.transit_body_id || body)}. UTC coverage {result.window_utc?.[0]} through {result.window_utc?.[1]} (end excluded). A whole-sign tenth cusp is not substituted for the astronomical MC; event-time tolerance is 60 seconds.</p>
      <div className="transit-tables"><table><caption>Transiting {bodyLabel(result.transit_body_id || body)} to saved natal MC</caption>
        <thead><tr><th scope="col">UTC instant</th><th scope="col">Aspect</th><th scope="col">Exact contact longitude</th></tr></thead>
        <tbody>{result.events?.map(item => <tr key={item.instant_utc}><th scope="row">{item.instant_utc.slice(0, 16).replace('T', ' ')} UTC</th>
          <td>{result.aspect}</td><td>{zodiac(item.target_degrees)}</td></tr>)}</tbody></table></div>
      <p className="transit-scroll-hint">Swipe the table sideways to see all columns on narrow screens.</p>
      {!result.events?.length && <p>No contacts in this fully scanned interval. Try another interval; no event was inferred.</p>}
      <button type="button" onClick={downloadCsv}>Download CSV timeline</button>

    </div>}
  </section>;
}
