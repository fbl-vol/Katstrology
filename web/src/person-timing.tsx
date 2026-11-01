import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';
import { useApplicationUtcDate, utcDays } from './manual-chart-intent';
import type { Person } from './people';
import type { SelectedResult } from './archive';
import { ReturnWheel, type Chart, type NatalResult } from './natal';

type OpenedResult = { id: string; status: string; result: {
  window_utc?: string[]; events?: { instant_utc?: string; chart?: NatalResult; phase?: string;
    angular_residual_degrees?: number; pass_direction?: string }[];
  source_birth?: Chart['result']['birth']; source_settings?: Chart['result']['profile']['settings'];
  person_id?: string; source_birth_id?: string; profile_id?: string; profile_revision?: number;
  method_version?: string; engine_version?: string; reference_place?: unknown;
} };
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

export function PersonTiming({ workspace, person, onDiscuss, onWatch }: {
  workspace: Workspace; person: Person;
  onDiscuss: (result: SelectedResult, label: string) => void;
  onWatch: () => void;
}) {
  const clock = useApplicationUtcDate();
  const [chartId, setChartId] = useState(person.active_chart_id || '');
  const [start, setStart] = useState('');
  const [duration, setDuration] = useState<'week' | 'month' | 'year'>('month');
  const request = useRef(0);
  const watchRequests = useRef(new Map<string, string>());
  const [watchOutcome, setWatchOutcome] = useState('');
  const [period, setPeriod] = useState<Period | null>(null);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<OpenedResult | null>(null);
  useEffect(() => { if (clock.today) setStart(value => value || clock.today!); }, [clock.today]);
  useEffect(() => { setChartId(person.active_chart_id || ''); setPeriod(null); setOpened(null); return () => { request.current++; }; }, [person.id]);
  const end = start ? periodEnd(start, duration) : '';
  const change = () => { request.current++; setPeriod(null); setOpened(null); setError(''); setLoading(false); };
  const dateTime = (value: string) => new Date(value).toLocaleString('en-GB', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
  });

  async function saveForLater(entry: TimingEntry, index: number | null) {
    const key = `${entry.id}:${index ?? 'whole'}`;
    if (!watchRequests.current.has(key)) watchRequests.current.set(key, `watch-${crypto.randomUUID()}`);
    setWatchOutcome('Saving for later…');
    try {
      await api(`people/${person.id}/watchlist`, workspace.csrf, 'POST', {
        id: watchRequests.current.get(key), result_id: entry.id,
        event_index: index, note: '', reminder: null,
      });
      setWatchOutcome('Saved for later. A due reminder is off until you opt in.');
      onWatch();
    } catch { setWatchOutcome('Saving was not confirmed. Retry here with the same selection.'); }
  }

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
  const seen = new Set<string>();
  const visible = entries.map(entry => ({ ...entry, sourceCount: entry.events.length,
    events: entry.events.filter(event => {
    const key = JSON.stringify([entry.technique, entry.method_version, entry.parameters,
      event.instant_utc, event.phase, event.pass_direction]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }) }));
  const eventCount = visible.reduce((total, entry) => total + entry.events.length, 0);
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
      {watchOutcome && <p role="status">{watchOutcome}</p>}
      {period && <><p role="status">{period.source_status === 'current' ? 'Current natal' : 'Historical natal'} · {start} to {end} UTC (end excluded). {period.note}
        {period.next_offset !== null && ' More saved results remain; this page is incomplete.'}</p>
        <label>Technique <select value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="all">All saved methods</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {period.coverage === 'no_saved_calculations' ? <p>No saved calculations cover these dates for this natal. This does not mean there are no sky events.</p> :
          <p>{eventCount ? `${eventCount} dated point${eventCount === 1 ? '' : 's'} in loaded saved results.` :
            'No dated points in the loaded saved results. Saved coverage is not a complete search of this period.'}</p>}
        <ol className="timing-results">{visible.map(entry => <li key={entry.id} data-result-id={entry.id}>
          <strong>{labels[entry.technique] || 'Saved timing'}</strong> · {entry.parameters.body || entry.parameters.branch || 'saved method'}
          {entry.window_utc && <small> · saved window {dateTime(entry.window_utc[0])} to {dateTime(entry.window_utc[1])} UTC</small>}
          {entry.events.length ? <ul>{entry.events.map(event => <li key={`${event.index}-${event.instant_utc}`}>
            {new Date(event.instant_utc).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })} UTC
            {event.phase && ` · ${event.phase}`}{event.pass_direction && ` · ${event.pass_direction}`}
          </li>)}</ul> : <p>{entry.sourceCount ? 'This point is also shown in another loaded saved calculation.' :
            'No dated points in the chosen period from this saved result.'}</p>}
          <button type="button" onClick={() => void api<{ id: string; source_status: string; result: OpenedResult['result'] }>(`advanced-results/${encodeURIComponent(entry.id)}`).then(value => {
            if (value && value.id === entry.id) setOpened({ id: entry.id, status: value.source_status, result: value.result });
          }).catch(() => setError('This saved result could not be opened.'))}>Open saved result</button>
          <button type="button" onClick={() => void saveForLater(entry, null)}>Save for later</button>
          <button type="button" onClick={() => onDiscuss({ result_id: entry.id, event_index: null },
            labels[entry.technique] || 'saved timing')}>Discuss this result</button>
          {entry.events.filter(event => event.index !== null).map(event => <span key={`actions-${event.index}-${event.instant_utc}`}>
            <button type="button" onClick={() => void saveForLater(entry, event.index)}>Save this crossing</button>
            <button type="button"
            onClick={() => onDiscuss({ result_id: entry.id, event_index: event.index },
              `${labels[entry.technique] || 'saved timing'} · ${event.instant_utc.slice(0, 10)} UTC`)}>
            Discuss this crossing · {event.instant_utc.slice(0, 10)}
          </button></span>)}
          {opened?.id === entry.id && <div className="timing-opened"><p>{opened.status === 'current' ? 'Current' : 'Historical'} saved result. Its original source and method remain unchanged.</p>
            <p>{labels[entry.technique]} · original saved calculation. {opened.result.window_utc ?
              `Saved interval ${dateTime(opened.result.window_utc[0])} to ${dateTime(opened.result.window_utc[1])} UTC.` :
              'One saved effective date.'} No values were recalculated.</p>
            {opened.result.events?.map((event, index) => <article key={`${index}-${event.instant_utc || ''}`}>
              <h3>{event.instant_utc ? dateTime(event.instant_utc) + ' UTC' : `Saved event ${index + 1}`}</h3>
              {event.phase && <p>Phase: {event.phase}</p>}
              {event.pass_direction && <p>Pass: {event.pass_direction}</p>}
              {event.angular_residual_degrees != null && <p>Angular residual: {event.angular_residual_degrees.toFixed(5)}°</p>}
              {event.chart && opened.result.source_birth && opened.result.source_settings &&
                opened.result.person_id && opened.result.source_birth_id && opened.result.profile_id &&
                opened.result.profile_revision && opened.result.method_version && opened.result.engine_version &&
                <ReturnWheel natal={event.chart} resultId={`${entry.id}-${index}`} personId={opened.result.person_id}
                  birthId={opened.result.source_birth_id} label={labels[entry.technique] || 'Return'}
                  methodVersion={opened.result.method_version} profileId={opened.result.profile_id}
                  profileRevision={opened.result.profile_revision} sourceStatus={opened.status}
                  sourceBirth={opened.result.source_birth} sourceSettings={opened.result.source_settings}
                  engineVersion={opened.result.engine_version} />}
            </article>)}</div>}
        </li>)}</ol>
        {period.next_offset !== null && <button type="button" disabled={loading} onClick={() => void load(period.next_offset!)}>Load more saved results</button>}
      </>}
    </>}
  </section>;
}
