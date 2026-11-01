import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';
import { useApplicationUtcDate, utcDays } from './manual-chart-intent';
import type { Person } from './people';
import type { SelectedResult } from './archive';
import { SavedResultDetail, type SavedCalculation } from './saved-result-detail';

type Point = { index: number | null; kind: string; instant_utc: string; phase?: string;
  family?: string; eclipse_type?: string; pass_direction?: string; body?: string;
  branch?: string; aspect?: string; natal_target?: string; linked_syzygy_utc?: string };
export type TimingEntry = { id: string; technique: string; method_version: string; status: string;
  window_utc?: string[]; parameters: Record<string, string | number>;
  reference_place_source?: { kind: string; label?: string }; events: Point[] };
type Period = { chart_id: string; source_status: string; entries: TimingEntry[];
  next_offset: number | null; coverage: string; note: string };
type DatedPoint = { point: Point; sources: TimingEntry[] };
const labels: Record<string, string> = {
  mc_transit: 'Transit to natal MC', actual_lunations_eclipses: 'Sky lunation or eclipse',
  progressed_mc_contacts: 'Progressed MC contact', progressed_lunar_phases: 'Progressed lunar phase',
  secondary_progression: 'Secondary progression', true_solar_arc: 'Solar arc',
  solar_return: 'Solar return', lunar_return: 'Lunar return', planetary_return: 'Planetary return',
};
const format = (value: string) => `${new Date(value).toLocaleString('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
})} UTC`;

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

function chronological(entries: TimingEntry[], chartId: string): DatedPoint[] {
  const bySource = new Map<string, DatedPoint>();
  for (const entry of entries) for (const point of entry.events) {
    // Two saved runs of the same calculation may share a physical point. Preserve
    // both original IDs while never merging a different chart, method, reference
    // place, phase or eclipse maximum with its linked geocentric syzygy.
    const key = JSON.stringify([chartId, entry.technique, entry.method_version,
      entry.parameters, entry.reference_place_source, point.kind, point.instant_utc,
      point.phase, point.family, point.body, point.branch, point.aspect, point.natal_target,
      point.pass_direction]);
    const previous = bySource.get(key);
    if (previous) previous.sources.push(entry);
    else bySource.set(key, { point, sources: [entry] });
  }
  return [...bySource.values()].sort((a, b) =>
    a.point.instant_utc.localeCompare(b.point.instant_utc) ||
    a.sources[0].id.localeCompare(b.sources[0].id));
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
  const openRequest = useRef(0);
  const watchRequests = useRef(new Map<string, string>());
  const [watchOutcome, setWatchOutcome] = useState('');
  const [period, setPeriod] = useState<Period | null>(null);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [opened, setOpened] = useState<{ id: string; index: number | null; technique: string; status: string; result: SavedCalculation } | null>(null);
  useEffect(() => { if (clock.today) setStart(value => value || clock.today!); }, [clock.today]);
  useEffect(() => {
    setChartId(person.active_chart_id || ''); setPeriod(null); setOpened(null);
    return () => { request.current++; openRequest.current++; };
  }, [person.id]);
  const end = start ? periodEnd(start, duration) : '';
  const change = () => {
    request.current++; openRequest.current++; setPeriod(null); setOpened(null);
    setError(''); setLoading(false); setWatchOutcome('');
  };

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
    openRequest.current++; setOpened(null); setLoading(true); setError('');
    try {
      const query = new URLSearchParams({ person_id: person.id, chart_id: chartId, start, end,
        offset: String(offset) });
      const page = await api<Period>(`advanced-results/period?${query}`);
      if (version === request.current) setPeriod(previous => offset && previous?.chart_id === page.chart_id ?
        { ...page, entries: [...previous.entries, ...page.entries] } : page);
    } catch { if (version === request.current) setError('Saved timing could not be checked. Your chosen dates are still here.'); }
    finally { if (version === request.current) setLoading(false); }
  }

  async function open(entry: TimingEntry, index: number | null) {
    const intent = ++openRequest.current;
    setOpened(null); setError('');
    try {
      const saved = await api<{ id: string; source_status: string; result: SavedCalculation }>(
        `advanced-results/${encodeURIComponent(entry.id)}`);
      if (intent === openRequest.current && saved.id === entry.id)
        setOpened({ id: entry.id, index, technique: entry.technique, status: saved.source_status, result: saved.result });
    } catch { if (intent === openRequest.current) setError('This saved result could not be opened. Try again.'); }
  }

  const entries = period?.entries.filter(item => filter === 'all' || item.technique === filter) || [];
  const points = chronological(entries, period?.chart_id || chartId);
  const undated = entries.filter(item => !item.events.length);
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
        {period.next_offset !== null && ' More saved results remain; this loaded timeline is incomplete.'}</p>
        <label>Technique <select value={filter} onChange={event => { openRequest.current++; setOpened(null); setFilter(event.target.value); }}>
          <option value="all">All saved methods</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {period.coverage === 'no_saved_calculations' ? <p>No saved calculations cover these dates for this natal. This does not mean there are no sky events.</p> :
          <p>{points.length ? `${points.length} distinct dated point${points.length === 1 ? '' : 's'} in loaded saved results, sorted by date.` :
            'No dated points in the loaded saved results. Saved coverage is not a complete search of this period.'}</p>}
        <ol className="timing-results">{points.map(({ point, sources }) => {
          const source = sources[0];
          const name = labels[source.technique] || 'Saved timing';
          const detail = point.kind === 'eclipse' ? `${point.family} eclipse · global maximum` :
            point.kind === 'lunation' ? `${point.phase} · geocentric syzygy` :
              point.kind === 'effective' || source.technique.startsWith('progressed') ||
              ['secondary_progression', 'true_solar_arc'].includes(source.technique) ? 'symbolic effective date' :
                point.pass_direction || 'exact contact';
          return <li key={`${source.id}-${point.index ?? 'effective'}`} data-result-id={source.id}>
            <strong>{format(point.instant_utc)}</strong> · {name} · {detail}
            {point.body && <span> · {point.body}</span>}{point.aspect && <span> · {point.aspect}</span>}
            {point.natal_target && <span> to natal {point.natal_target}</span>}
            {point.linked_syzygy_utc && <small> · linked syzygy {format(point.linked_syzygy_utc)} (different instant)</small>}
            {source.reference_place_source?.label && <small> · {source.reference_place_source.label}</small>}
            <div className="timing-point-actions"><button type="button" onClick={() => void open(source, point.index)}>Open saved result</button>
              <button type="button" onClick={() => void saveForLater(source, point.index)}>Save for later</button>
              <button type="button" onClick={() => onDiscuss({ result_id: source.id, event_index: point.index },
                `${name} · ${format(point.instant_utc)}`)}>Discuss this point</button></div>
            {sources.length > 1 && <details><summary>Also saved in {sources.length - 1} other result{sources.length === 2 ? '' : 's'}</summary>
              {sources.slice(1).map(item => <button type="button" key={item.id} onClick={() => void open(item, point.index)}>
                Open another saved original</button>)}</details>}
            {opened && opened.index === point.index && sources.some(item => item.id === opened.id) && <SavedResultDetail
              result={opened.result} resultId={opened.id} sourceStatus={opened.status}
              technique={opened.technique} />}
          </li>;
        })}</ol>
        {undated.length > 0 && <details className="detail-section"><summary>Saved calculations without dated points · {undated.length}</summary>
          <p>These originals cover part of the interval but do not add a point to the loaded timeline.</p>
          <ul>{undated.map(entry => <li key={entry.id} data-result-id={entry.id}>
            {labels[entry.technique] || 'Saved timing'} · {entry.method_version}
            <button type="button" onClick={() => void open(entry, null)}>Open saved result</button>
            <button type="button" onClick={() => void saveForLater(entry, null)}>Save for later</button>
            <button type="button" onClick={() => onDiscuss({ result_id: entry.id, event_index: null },
              labels[entry.technique] || 'saved timing')}>Discuss this result</button>
            {opened?.id === entry.id && <SavedResultDetail result={opened.result} resultId={entry.id}
              sourceStatus={opened.status} technique={entry.technique} />}
          </li>)}</ul></details>}
        {period.next_offset !== null && <button type="button" disabled={loading} onClick={() => void load(period.next_offset!)}>Load more saved results</button>}
      </>}
    </>}
  </section>;
}
