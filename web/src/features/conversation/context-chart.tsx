import { useEffect, useState } from 'react';
import { api } from '../../shared/api';
import { Glyph, bodyLabel, ChartNotation } from '../charts/chart-symbols';
import type { Selection } from './conversation';
import { CompactNatalWheel, zodiac } from '../charts/natal';
import type { Person } from '../people/people';
import type { Turn } from './turns';

function useCompactLayout() {
  const [compact, setCompact] = useState(() => matchMedia('(max-width: 1000px)').matches);
  useEffect(() => {
    const query = matchMedia('(max-width: 1000px)');
    const update = () => setCompact(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return compact;
}

export function ContextChart({ selection, people, turns, activeHead, onOpenChart }: {
  selection: Selection[]; people: Person[]; turns: Turn[]; activeHead: string | null;
  onOpenChart: (person: Person) => void;
}) {
  const compact = useCompactLayout();
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState<{ signature: string; records: Person[] } | null>(null);
  const [failed, setFailed] = useState(false);
  const selected = selection.map(item => people.find(person => person.id === item.person_id)).filter((person): person is Person => !!person);
  const signature = JSON.stringify(selected.map(person => [person.id, person.name, person.active_chart_id]));
  const ids = selected.map(person => person.id);
  useEffect(() => {
    let current = true;
    setLoaded(null); setFailed(false); setExpanded(false);
    if (!ids.length || ids.length > 2) {
      setLoaded({ signature, records: [] });
      return () => { current = false; };
    }
    void Promise.all(ids.map(id => api<Person>(`people/${encodeURIComponent(id)}`)))
      .then(records => { if (current) setLoaded({ signature, records }); })
      .catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [signature]);

  if (!selection.length) return null;
  const title = selected.length === 1 ? `${selected[0].name}’s natal chart` : 'Selected natal charts';
  const records = loaded?.signature === signature ? loaded.records : [];
  const head = turns.find(turn => turn.id === activeHead);
  const earlier = loaded?.signature === signature ? head?.selected_people.filter(item => item.chart_id &&
    records.find(person => person.id === item.person_id)?.active_chart_id !== item.chart_id) || [] : [];
  const chartIssue = records.map(person => {
    const chart = person.charts.find(item => item.id === person.active_chart_id);
    if (!person.active_chart_id) return '';
    if (!chart) return 'Current chart details unavailable';
    if (chart.source_status !== 'current') return 'Chart source no longer current';
    if (chart.result.natal?.status !== 'complete' || chart.result.natal.houses.status !== 'supported') return 'Complete natal wheel unavailable';
    return '';
  }).find(Boolean);
  const hint = [chartIssue, earlier.length ? 'Earlier message used a different chart' : '',
    selected.length > 1 ? 'Separate charts · no comparison' :
      selected[0]?.active_chart_id ? 'For your next message' : 'No current generated natal'].filter(Boolean).join(' · ');
  return <aside className="context-chart" aria-label="Current natal context">
    <details open={!compact || expanded} onToggle={event => { if (compact) setExpanded(event.currentTarget.open); }}>
      <summary><strong>{title}</strong><span>{hint}</span></summary>
      <div className="context-chart-body">
        <h2>{title}</h2>
        <p className="context-chart-kicker">{selected.length > 1 ? 'Separate charts for your next message; no comparison is inferred.' : hint}</p>
        {earlier.length > 0 && <p className="context-chart-caution">Earlier message used a different chart. Its original version remains in the archive.</p>}
        {failed && <p role="status">Current chart could not be loaded. Open the person profile to inspect it; no preview is shown.</p>}
        {!failed && !loaded && <p role="status">Loading current chart…</p>}
        {selected.length > 2 && <p>Open each person’s profile for their own natal chart. No multi-person chart is inferred here.</p>}
        {selected.length < selection.length && <p role="status">A selected person is no longer in this workspace. The archived selection remains unchanged.</p>}
        {records.map(person => {
          const chart = person.charts.find(item => item.id === person.active_chart_id);
          const natal = chart?.result.natal;
          const supported = chart?.source_status === 'current' && natal?.status === 'complete' && natal.houses.status === 'supported' && natal.houses.angles.length > 0;
          return <section key={person.id} className="context-person" aria-label={`${person.name} current chart`}>
            {records.length > 1 && <h3>{person.name}</h3>}
            {chart ? <>
              {supported && records.length === 1 && <><CompactNatalWheel chart={chart} />
                <table className="context-placements"><caption>Selected placements · full positions in chart</caption><tbody>
                  {(['sun', 'moon', 'venus'] as const).map(id => natal.positions.find(body => body.id === id)).filter(body => !!body).map(body =>
                    <tr key={body.id}><th scope="row"><Glyph id={body.id} /> {bodyLabel(body.id)}</th><td>{zodiac(body.longitude_degrees)}</td></tr>)}
                </tbody></table></>}
              {!supported && <p className="context-chart-caution">{chart.source_status !== 'current' ? 'This chart source is no longer current.' : 'A complete supported wheel is unavailable for this chart.'} No positions or houses are inferred here.</p>}
            </> : <p>No current generated natal. A draft, uploaded file or historical chart is not substituted.</p>}
            <button type="button" aria-label={`Open ${person.name}’s full chart`} onClick={() => onOpenChart(person)}>Open full chart</button>
            {supported && records.length === 1 && <ChartNotation ids={natal.positions.map(body => body.id)} rings="This wheel shows natal placements." />}
          </section>;
        })}
      </div>
    </details>
    {compact && records.length === 1 && <button type="button" className="context-chart-shortcut" onClick={() => onOpenChart(records[0])}>
      Open {records[0].name}’s full chart
    </button>}
  </aside>;
}
