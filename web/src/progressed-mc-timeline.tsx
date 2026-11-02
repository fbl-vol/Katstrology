import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type Workspace } from './api';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import { bodyLabel, ChartNotation } from './chart-symbols';
import { zodiac } from './natal';

type Branch = 'mcp' | 'mcr';
type Timeline = { id?: string; status: string; source_status?: string;
  branch: Branch; branch_description: string; body: string; aspect: string;
  method_version: string; chart_id: string; source_birth_id: string;
  window_utc: string[]; events: { instant_utc: string; target_degrees: number }[];
  target_source_degrees: number; natal_mc_degrees: number; reason?: string };
type Listed = { id: string; created_at: string; branch?: Branch; body?: string };

const bodies = ['sun', 'moon', 'mercury', 'venus', 'mars', 'jupiter', 'saturn', 'uranus', 'neptune', 'pluto', 'chiron'];
const aspects = ['conjunction', 'opposition', 'trine', 'square', 'sextile'];

function downloadCsv(result: Timeline) {
  const lines = ['effective_utc,branch,body,aspect,target_degrees,source_chart_id,source_birth_id,method_version',
    ...result.events.map(event => [event.instant_utc, result.branch, result.body, result.aspect,
      event.target_degrees.toFixed(6), result.chart_id, result.source_birth_id, result.method_version].join(','))];
  const blob = new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = `kat-${result.branch}-contacts.csv`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ProgressedMcTimeline({ workspace, personId }: { workspace: Workspace; personId: string }) {
  const [branch, setBranch] = useState<Branch>('mcp');
  const [body, setBody] = useState('mercury');
  const [aspect, setAspect] = useState('square');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (clock.today) { setStart(current => current || clock.today); setEnd(current => current || utcDays(clock.today, 365)); }
  }, [clock.today]);
  const [result, setResult] = useState<Timeline | null>(null);
  const intent = useManualChartIntent(result, false);
  const [history, setHistory] = useState<Listed[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const version = useRef(0);
  const request = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => {
    const current = ++version.current;
    void api<{ results: Listed[] }>(
      `advanced-results?person_id=${encodeURIComponent(personId)}&technique=progressed_mc_contacts`)
      .then(data => { if (current === version.current) setHistory(data.results); })
      .catch(() => { if (current === version.current) setError('Saved MC branches could not be listed.'); });
    return () => { version.current++; };
  }, [personId]);
  function change() { version.current++; setResult(null); setError(''); setBusy(false); request.current = null; }
  async function calculate(event: FormEvent) {
    event.preventDefault();
    const current = ++version.current;
    setBusy(true); setResult(null); setError(''); intent.revealResult();
    const key = `${personId}:${branch}:${body}:${aspect}:${start}:${end}`;
    const id = request.current?.key === key ? request.current.id : `progressed-mc-${crypto.randomUUID()}`;
    request.current = { key, id };
    try {
      const data = await api<Timeline>('advanced-results', workspace.csrf, 'POST', {
        id, person_id: personId, technique: 'progressed_mc_contacts',
        parameters: { branch, body, aspect, start_utc: `${start}T00:00:00+00:00`,
          end_utc: `${end}T00:00:00+00:00` },
      });
      if (current !== version.current) return;
      if (data.status === 'supported') {
        setResult(data);
        setHistory(rows => rows.some(row => row.id === id) ? rows : [
          { id, created_at: new Date().toISOString(), branch, body }, ...rows]);
      } else setError(data.status === 'partial_near_station_contact' ?
        'Near-station tangency was not resolved. This date range is incomplete; no complete timeline was saved. Try a shorter interval.' :
        `A reliable MC branch was not available (${data.status}). No dates were inferred.`);
    } catch (cause) { if (current === version.current) {
      if (cause instanceof ApiError && cause.status === 400) {
        request.current = null;
        setError('Choose a positive effective UTC interval after birth, at most 732 days long. No MC timeline was saved.');
      } else setError('Saving was not confirmed. Retry the same request or check saved MC searches before starting another.');
    } }
    finally { if (current === version.current) setBusy(false); }
  }
  async function openSaved(id: string) {
    const current = ++version.current;
    setResult(null); setError(''); setBusy(false); intent.revealResult();
    try {
      const saved = await api<{ result: Timeline; source_status: string }>(`advanced-results/${encodeURIComponent(id)}`);
      if (current === version.current) setResult({ ...saved.result, id, source_status: saved.source_status });
    } catch { if (current === version.current) setError('Could not open the saved MC timeline.'); }
  }
  return <section className="advanced-view" aria-label="Progressed MC exact contact timeline">
    <h2>Search exact progressed MC dates</h2>
    <p>Choose one symbolic method. MCp moves the astronomical MC by the UTC anniversary bracket and compares it with a natal planet. MCr compares one directly progressed planet with the fixed natal astronomical MC. Neither is a real-sky transit.</p>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Branch<select value={branch} onChange={event => { change(); setBranch(event.target.value as Branch); }}>
        <option value="mcp">MCp · progressed MC → natal planet</option>
        <option value="mcr">MCr · progressed planet → natal MC</option>
      </select></label>
      <label>{branch === 'mcp' ? 'Natal planet' : 'Progressed planet'}<select value={body}
        onChange={event => { change(); setBody(event.target.value); }}>
        {bodies.map(item => <option value={item} key={item}>{bodyLabel(item)}</option>)}</select></label>
      <label>Aspect<select value={aspect} onChange={event => { change(); setAspect(event.target.value); }}>
        {aspects.map(item => <option value={item} key={item}>{item}</option>)}</select></label>
      <label>From (UTC)<input type="date" required min="1900-01-01" max="2099-12-31" value={start}
        onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Until (UTC, excluded)<input type="date" required min="1900-01-01" max="2099-12-31" value={end}
        onChange={event => { change(); setEnd(event.target.value); }} /></label>
      {clock.unavailable && <p role="status">Application date is unavailable. Choose UTC dates yourself.</p>}
      <button type="submit" className="primary" disabled={busy}>{busy ? 'Searching…' : 'Search exact dates'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved progressed MC searches"><h3>Saved MC searches</h3>
      {history.map(row => <button type="button" key={row.id} onClick={() => void openSaved(row.id)}>
        Open saved {row.branch?.toUpperCase() || 'MC'} {row.body ? bodyLabel(row.body) : ''} · {row.created_at.slice(0, 10)}</button>)}</nav>}
    {error && <p role="alert" className="error">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Progressed MC timeline">
      {result.source_status === 'historical' && <p role="status" className="error">Historical source natal. Archived dates were not recalculated.</p>}
      <h3 ref={intent.resultHeading} tabIndex={-1}>{result.branch.toUpperCase()} · {bodyLabel(result.body)} {result.aspect}</h3>
      <p>{result.branch_description}. Fixed natal MC {zodiac(result.natal_mc_degrees)}. Effective dates are symbolic in the requested half-open UTC interval.</p>
      <details className="chart-supporting-data"><summary>How these dates were found</summary><p>Contacts were found on a 12-hour scan with 60-second refinement.</p></details>
      <ChartNotation rings="No wheel is drawn for symbolic effective-date contacts. Dates are not concurrent positions." ids={[result.body]} />
      {result.events.length ? <div className="transit-tables"><table><caption>{result.branch.toUpperCase()} exact dates · {result.events.length} contacts</caption>
        <thead><tr><th scope="col">Effective instant (UTC)</th><th scope="col">Target longitude</th></tr></thead>
        <tbody>{result.events.map((item, index) => <tr key={`${index}-${item.instant_utc}`}><th scope="row">{item.instant_utc}</th>
          <td>{zodiac(item.target_degrees)}</td></tr>)}</tbody></table></div> :
        <p>No crossing in the chosen interval for this selected branch, body and aspect; this is not a promise about other intervals.</p>}
      <button type="button" onClick={() => downloadCsv(result)}>Download MC dates CSV</button>
    </div>}
  </section>;
}
