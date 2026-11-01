import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';
import { useApplicationUtcDate, utcDays } from './manual-chart-intent';
import type { Person } from './people';

export type TimingEntry = { id: string; technique: string; method_version: string; status: string;
  window_utc?: string[]; parameters: Record<string, string>; events: {
    index: number | null; instant_utc: string; phase?: string; pass_direction?: string }[] };
type Period = { chart_id: string; source_status: string; entries: TimingEntry[];
  next_offset: number | null; coverage: string; note: string };
const labels: Record<string, string> = {
  mc_transit: 'Transit to natal MC', actual_lunations_eclipses: 'Sky lunation or eclipse',
  progressed_mc_contacts: 'Progressed MC contact', progressed_lunar_phases: 'Progressed lunar phase',
  secondary_progression: 'Secondary progression', true_solar_arc: 'Solar arc',
  solar_return: 'Solar return', lunar_return: 'Lunar return', planetary_return: 'Planetary return',
};

function periodEnd(start: string, span: 'week' | 'month' | 'year') {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return '';
  if (span === 'week') return utcDays(start, 7);
  const [year, month, day] = start.split('-').map(Number);
  const target = new Date(Date.UTC(year + (span === 'year' ? 1 : 0),
    month - 1 + (span === 'month' ? 1 : 0), 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(day, lastDay));
  return target.toISOString().slice(0, 10);
}

export function PersonTiming({ workspace, person }: { workspace: Workspace; person: Person }) {
  const clock = useApplicationUtcDate();
  const [chartId, setChartId] = useState(person.active_chart_id || '');
  const [start, setStart] = useState('');
  const [duration, setDuration] = useState<'week' | 'month' | 'year'>('month');
  const request = useRef(0);
  const [period, setPeriod] = useState<Period | null>(null);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<{ id: string; status: string; result: Record<string, unknown> } | null>(null);
  useEffect(() => { if (clock.today) setStart(value => value || clock.today!); }, [clock.today]);
  useEffect(() => { setChartId(person.active_chart_id || ''); setPeriod(null); setOpened(null); return () => { request.current++; }; }, [person.id]);
  const end = start ? periodEnd(start, duration) : '';
  const change = () => { request.current++; setPeriod(null); setOpened(null); setError(''); setLoading(false); };

  async function load(offset = 0) {
    if (!chartId || !start || !end) return;
    const version = ++request.current;
    setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ person_id: person.id, chart_id: chartId, start, end,
        offset: String(offset) });
      const page = await api<Period>(`advanced-results/period?${query}`);
      if (version === request.current) setPeriod(previous => offset && previous?.chart_id === page.chart_id ?
        { ...page, entries: [...previous.entries, ...page.entries] } : page);
    } catch { if (version === request.current) setError('Saved timing could not be checked. Your chosen dates are still here.'); }
    finally { if (version === request.current) setLoading(false); }
  }

  const entries = period?.entries.filter(item => filter === 'all' || item.technique === filter) || [];
  const eventCount = entries.reduce((total, entry) => total + entry.events.length, 0);
  return <section className="person-timing" aria-label="Where am I now">
    <h2>Where am I now?</h2>
    <p>Explore saved timing for {person.name}. These are calculations, not a prediction or proof that events are related.</p>
    {!person.charts.length ? <p>No natal has been saved. You can still talk without a chart.</p> : <>
      <div className="timing-controls"><label>Source natal <select value={chartId} onChange={event => { change(); setChartId(event.target.value); }}>
        <option value="">Choose a natal</option>{person.charts.map((chart, index) => <option key={chart.id} value={chart.id}>
          {chart.id === person.active_chart_id ? 'Current natal' : `Earlier natal ${index + 1}`}</option>)}
      </select></label><label>From (UTC) <input type="date" value={start} onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Explore <select value={duration} onChange={event => { change(); setDuration(event.target.value as typeof duration); }}>
        <option value="week">Week</option><option value="month">Month</option><option value="year">Year</option></select></label>
      <button type="button" disabled={loading || !chartId || !start || !end} onClick={() => void load()}>
        {loading ? 'Opening…' : 'Show saved timing'}</button></div>
      {clock.unavailable && <p role="status">Application date unavailable. Choose a starting date yourself.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {period && <><p role="status">{period.source_status === 'current' ? 'Current natal' : 'Historical natal'} · {start} to {end} UTC (end excluded). {period.note}
        {period.next_offset !== null && ' More saved results remain; this page is incomplete.'}</p>
        <label>Technique <select value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="all">All saved methods</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {period.coverage === 'no_saved_calculations' ? <p>No saved calculations cover these dates for this natal. This does not mean there are no sky events.</p> :
          <p>{eventCount ? `${eventCount} dated point${eventCount === 1 ? '' : 's'} in loaded saved results.` :
            'No dated points in the loaded saved results. Saved coverage is not a complete search of this period.'}</p>}
        <ol className="timing-results">{entries.map(entry => <li key={entry.id}>
          <strong>{labels[entry.technique] || 'Saved timing'}</strong> · {entry.parameters.body || entry.parameters.branch || 'saved method'}
          {entry.window_utc && <small> · saved window {entry.window_utc[0]} to {entry.window_utc[1]}</small>}
          {entry.events.length ? <ul>{entry.events.map(event => <li key={`${event.index}-${event.instant_utc}`}>
            {new Date(event.instant_utc).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })} UTC
            {event.phase && ` · ${event.phase}`}{event.pass_direction && ` · ${event.pass_direction}`}
          </li>)}</ul> : <p>No dated points in the chosen period from this saved result.</p>}
          <button type="button" onClick={() => void api<{ id: string; source_status: string; result: Record<string, unknown> }>(`advanced-results/${encodeURIComponent(entry.id)}`).then(value => {
            if (value && value.id === entry.id) setOpened({ id: entry.id, status: value.source_status, result: value.result });
          }).catch(() => setError('This saved result could not be opened.'))}>Open saved result</button>
          {opened?.id === entry.id && <div className="timing-opened"><p>{opened.status === 'current' ? 'Current' : 'Historical'} saved result. Its original source and method remain unchanged.</p>
            <p>Method: {entry.method_version}. {entry.events.length} dated point(s) in this period. Open its original chart in the relevant saved chart view for all details.</p></div>}
        </li>)}</ol>
        {period.next_offset !== null && <button type="button" disabled={loading} onClick={() => void load(period.next_offset!)}>Load more saved results</button>}
      </>}
    </>}
  </section>;
}
