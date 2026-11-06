import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type Workspace } from '../../shared/api';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import { unavailableCalculation } from './advanced-result-status';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import { ReturnWheel, zodiac, type NatalResult, type Chart } from './natal';
import type { Person } from '../people/people';
import { birthReference, ReturnReferencePlace, type ReferenceChoice } from './return-reference-place';

type Body = 'venus' | 'mars' | 'jupiter' | 'saturn';
export type PlanetaryReturnDraft = { personId: string; body: Body; start: string; end: string;
  reference: ReferenceChoice };
type ReturnEvent = { instant_utc: string; longitude_degrees: number; speed_degrees_per_day: number;
  angular_residual_degrees: number; pass_direction: string; chart: NatalResult & {
    aspects_total: number; aspects_truncated: boolean } };
type ReturnResult = { id?: string; status: string; method_version: string; person_id: string;
  source_birth_id: string; source_birth: Chart['result']['birth']; source_settings: Chart['result']['profile']['settings'];
  source_status: string; engine_version: string; ephemeris_sha256: Record<string, string>;
  profile_id: string; profile_revision: number; chart_id: string; body: Body;
  natal_longitude_degrees: number; reference_place: { latitude: number; longitude: number };
  reference_place_source?: { kind: string; label?: string };
  window_utc: string[]; events: ReturnEvent[] };
const names: Record<Body, string> = { venus: 'Venus', mars: 'Mars', jupiter: 'Jupiter', saturn: 'Saturn' };
const days: Record<Body, number> = { venus: 1830, mars: 1830, jupiter: 5490, saturn: 11712 };
const utcLabel = (instant: string) => `${new Date(instant).toLocaleString('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
})} UTC`;

function downloadCsv(result: ReturnResult) {
  const lines = ['body,utc,pass_direction,longitude_degrees,natal_longitude_degrees,speed_degrees_per_day,angular_residual_degrees,reference_latitude,reference_longitude,source_chart_id,method_version',
    ...result.events.map(item => [result.body, item.instant_utc, item.pass_direction,
      item.longitude_degrees.toFixed(6), result.natal_longitude_degrees.toFixed(6),
      item.speed_degrees_per_day.toFixed(6), item.angular_residual_degrees.toFixed(8),
      result.reference_place.latitude, result.reference_place.longitude,
      result.chart_id, result.method_version].join(','))];
  const url = URL.createObjectURL(new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url;
  a.download = `kat-planetary-returns-${result.id || 'preview'}.csv`;
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function PlanetaryReturnsView({ workspace, people, onClose, onCreateNatal, initialDraft }: {
  workspace: Workspace; people: Person[]; onClose: () => void;
  onCreateNatal: (personId: string, draft: PlanetaryReturnDraft) => void;
  initialDraft?: PlanetaryReturnDraft;
}) {
  const [personId, setPersonId] = useState('');
  const [active, setActive] = useState<Chart | null>(null);
  const [loadingSource, setLoadingSource] = useState(false);
  const [sourceUnavailable, setSourceUnavailable] = useState(false);
  const [body, setBody] = useState<Body>(initialDraft?.body || 'venus');
  const [start, setStart] = useState(initialDraft?.start || '');
  const [end, setEnd] = useState(initialDraft?.end || '');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (clock.today) { setStart(current => current || clock.today); setEnd(current => current || utcDays(clock.today, 365)); }
  }, [clock.today]);
  const [reference, setReference] = useState<ReferenceChoice>(() => birthReference(null));
  const { result, history, error, busy, setError, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<ReturnResult, { id: string; first_utc?: string; created_at: string }>(workspace);
  const intent = useManualChartIntent(result);
  const personVersion = useRef(0);
  const personInput = useRef<HTMLSelectElement>(null);
  const restoreDraft = useRef(!!initialDraft);
  const exactSource = active?.result.natal?.status === 'complete';
  useEffect(() => {
    if (initialDraft?.personId) choosePerson(initialDraft.personId);
    return () => { personVersion.current++; };
  }, []);
  function choosePerson(id: string) {
    const preservingDraft = restoreDraft.current && id === initialDraft?.personId;
    restoreDraft.current = false;
    loadPerson(id, 'planetary_return', 'Saved planetary returns could not be listed.');
    setPersonId(id); setActive(null); setReference(birthReference(null));
    setLoadingSource(!!id); setSourceUnavailable(false);
    const current = ++personVersion.current;
    if (!id) return;
    void api<Person>(`people/${encodeURIComponent(id)}`).then(person => {
      if (current !== personVersion.current) return;
      const chart = person.charts.find(item => item.id === person.active_chart_id) || null;
      setLoadingSource(false); setActive(chart);
      const birthplace = birthReference(chart);
      const draft = initialDraft?.reference;
      const useDraft = preservingDraft && draft && draft.kind !== 'missing' && (draft.kind !== 'birthplace' ||
        (draft.latitude === birthplace.latitude && draft.longitude === birthplace.longitude));
      setReference(useDraft ? draft : birthplace);
    }).catch(() => { if (current === personVersion.current) { setLoadingSource(false); setSourceUnavailable(true); } });
  }
  async function calculate(event: FormEvent) {
    event.preventDefault();
    if (!exactSource || busy) return;
    if (reference.kind === 'missing' || reference.latitude.trim() === '' || reference.longitude.trim() === '') {
      setError('Choose a reference place or enter both precise coordinates. Your dates are still here.'); return;
    }
    if (Date.parse(`${start}T00:00:00Z`) < Date.parse(active?.result.natal?.instant_utc || '')) {
      setError('Choose a UTC start after the saved birth instant. Your dates are still here.'); return;
    }
    const duration = (Date.parse(end) - Date.parse(start)) / 86400_000;
    if (!Number.isFinite(duration) || duration <= 0 || duration > days[body]) {
      setError(`Choose an end date after the start, within ${days[body]} days for ${names[body]}. Your dates are still here.`); return;
    }
    const parameters = { body, start_utc: `${start}T00:00:00+00:00`,
      end_utc: `${end}T00:00:00+00:00`, latitude: Number(reference.latitude),
      longitude: Number(reference.longitude),
      ...(reference.placeId ? { reference_place_id: reference.placeId } : {}) };
    intent.revealResult();
    await saveResult(personId, 'planetary_return', parameters, {
      prefix: 'planet-return',
      firstRow: (saved, id) => ({ id, first_utc: saved.events[0]?.instant_utc,
        created_at: new Date().toISOString() }),
      unavailable: status => status === 'partial_near_station_contact'
        ? 'A near-station crossing cannot be resolved as a complete pass history. No partial return was saved.'
        : unavailableCalculation('Planetary returns', status),
      invalid: 'Check the UTC interval and reference coordinates, then correct the form. No return was saved.',
      uncertain: 'Saving was not confirmed. Retry this same request or check saved returns before starting a new one.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open saved planetary returns.');
  }
  return <section className="advanced-view" aria-label="Planetary returns chart">
    <div className="transit-heading"><div><span className="eyebrow">SAVED NATAL · ALL PASSES</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Planetary returns</h1><p>Find each direct and retrograde crossing of the planet’s own saved natal longitude. Jupiter, Saturn, Venus and Mars; no single pass selected for you.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal<select ref={personInput} required value={personId} onChange={event => choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      {personId && loadingSource && <p role="status">Checking this person’s current natal…</p>}
      {personId && sourceUnavailable && <p role="alert" className="manual-source-recovery">Current natal could not be checked. No calculation was started.<br />
        <button type="button" onClick={() => choosePerson(personId)}>Try checking again</button>
        {' '}<button type="button" onClick={() => personInput.current?.focus()}>Choose another person</button>
      </p>}
      {personId && !loadingSource && !sourceUnavailable && !exactSource && <p role="status" className="manual-source-recovery">
        {active ? 'A supplied exact birth time is needed for planetary returns; no time was assumed.' :
          'No current generated natal is available for this person.'}<br />
        <button type="button" onClick={() => onCreateNatal(personId,
          { personId, body, start, end, reference })}>Create or review natal</button>
        {' '}<button type="button" onClick={() => personInput.current?.focus()}>Choose another person</button>
      </p>}
      <label>Returning planet<select value={body} onChange={event => { change(); setBody(event.target.value as Body); }}>
        {(Object.keys(names) as Body[]).map(item => <option key={item} value={item}>{names[item]}</option>)}</select></label>
      <label>From<input required type="date" value={start} onChange={event => { change(); setStart(event.target.value); }} /></label>
      <label>Until (not included)<input required type="date" value={end} onChange={event => { change(); setEnd(event.target.value); }} /></label>
      <p>Maximum window for {names[body]}: {days[body]} days. A zero-pass result is valid; an unresolved station is not a complete result.</p>
      {personId && !loadingSource && !sourceUnavailable &&
        <ReturnReferencePlace key={personId} workspace={workspace} value={reference} onChange={next => {
          change(); setReference(next);
        }} />}
      {clock.unavailable && <p role="status">Application date is unavailable. Choose UTC dates yourself.</p>}
      <button type="submit" className="primary" disabled={!exactSource || busy || reference.kind === 'missing'}>{busy ? 'Searching…' : 'Find planetary return passes'}</button>
    </form>
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved planetary returns"><h2>Saved planetary returns</h2>
      {history.map(item => <button key={item.id} type="button" onClick={() => void openSaved(item.id)}>
        Open saved planetary returns · {(item.first_utc || item.created_at).slice(0, 10)}</button>)}</nav>}
    {error && <p role="alert" className="error">{error}</p>}
    {result && <div role="region" aria-label="Planetary return results" className="advanced-results">
      {result.source_status === 'historical' && <p role="status" className="error">Historical natal source: these archived passes were not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>{names[result.body]} returns · {result.events.length} pass{result.events.length === 1 ? '' : 'es'}</h2>
      <p>Geocentric tropical {names[result.body]} to saved natal {names[result.body]} at {zodiac(result.natal_longitude_degrees)}. Selected period {result.window_utc.map(utcLabel).join(' to ')} (last moment not included). Reference: {result.reference_place_source?.kind === 'offline_city_centre' ? result.reference_place_source.label :
        result.reference_place_source?.kind === 'saved_birthplace_coordinates' ? 'saved birthplace coordinates' : 'selected coordinates'}
        {' '}({result.reference_place.latitude}°, {result.reference_place.longitude}°).</p>
      {result.events.length === 0 && <p role="status">No crossing in the specified interval. Try a different period.</p>}
      {result.events.map((item, index) => <article key={item.instant_utc} className="advanced-event">
        <h3>Pass {index + 1}: {item.pass_direction} · {utcLabel(item.instant_utc)}</h3>
        <p>Longitude {zodiac(item.longitude_degrees)}; speed {item.speed_degrees_per_day.toFixed(5)}°/day;
          residual {item.angular_residual_degrees.toFixed(7)}°. Reference place {result.reference_place.latitude}°, {result.reference_place.longitude}°.</p>
        {item.chart.aspects_truncated && <p>Only {item.chart.aspects.length} of {item.chart.aspects_total} calculated return-chart aspects retained for bounded display; all planets and available houses shown.</p>}
        <ReturnWheel natal={item.chart} resultId={`${result.id || 'preview'}-${index}`} personId={result.person_id}
          birthId={result.source_birth_id} label={`${names[result.body]} return · ${item.pass_direction}`}
          methodVersion={result.method_version} profileId={result.profile_id} profileRevision={result.profile_revision}
          sourceStatus={result.source_status} sourceBirth={result.source_birth} sourceSettings={result.source_settings}
          engineVersion={result.engine_version} additionalProvenance={{ source_chart_id: result.chart_id,
            return_body: result.body, natal_longitude_degrees: result.natal_longitude_degrees,
            pass_direction: item.pass_direction, speed_degrees_per_day: item.speed_degrees_per_day,
            angular_residual_degrees: item.angular_residual_degrees,
            reference_place: result.reference_place, reference_place_source: result.reference_place_source,
            ephemeris_sha256: result.ephemeris_sha256,
            aspects_total: item.chart.aspects_total, aspects_shown: item.chart.aspects.length }} />
      </article>)}
      <button type="button" onClick={() => downloadCsv(result)}>Download planetary returns CSV</button>
    </div>}
  </section>;
}
