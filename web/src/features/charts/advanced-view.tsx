import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type Workspace } from '../../shared/api';
import { unavailableCalculation } from './advanced-result-status';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import { useApplicationUtcDate, useManualChartIntent, utcDays } from './manual-chart-intent';
import type { Person } from '../people/people';
import { ReturnWheel, type NatalResult, type Chart } from './natal';
import { birthReference, ReturnReferencePlace, type ReferenceChoice } from './return-reference-place';
import type { SelectedResult } from '../conversation/archive';

type Technique = 'solar_return' | 'lunar_return';
export type AdvancedDraft = { personId: string; year: string; yearEdited: boolean;
  start: string; end: string; reference: ReferenceChoice };
type ReturnResult = {
  id?: string; status: string; technique: Technique; method_version?: string; source_status?: string;
  person_id?: string; source_birth_id?: string; source_birth?: Chart['result']['birth'];
  source_settings?: Chart['result']['profile']['settings'];
  profile_id?: string; profile_revision?: number; engine_version?: string;
  reference_place?: { latitude: number; longitude: number };
  reference_place_source?: { kind: string; label?: string }; window_utc?: string[];
  events?: { instant_utc: string; chart: NatalResult }[];
};
type ReturnHistory = { id: string; first_utc: string | null;
  window_utc?: string[]; event_count?: number | null;
  reference_place?: ReturnResult['reference_place'];
  reference_place_source?: ReturnResult['reference_place_source'] };

export function AdvancedView({ workspace, people, technique, onClose, onCreateNatal, onDiscuss, initialDraft, initialPersonId }: {
  workspace: Workspace; people: Person[]; technique: Technique; onClose: () => void;
  onCreateNatal: (personId: string, draft: AdvancedDraft) => void; onDiscuss?: (personId: string, result: SelectedResult, label: string) => void;
  initialDraft?: AdvancedDraft; initialPersonId?: string;
}) {
  const label = technique === 'solar_return' ? 'Solar return' : 'Lunar returns';
  const [personId, setPersonId] = useState('');
  const [active, setActive] = useState<Chart | null>(null);
  const [loadingSource, setLoadingSource] = useState(false);
  const [sourceUnavailable, setSourceUnavailable] = useState(false);
  const [year, setYear] = useState(initialDraft?.year ?? '');
  const yearInput = useRef<HTMLInputElement>(null);
  const yearEdited = useRef(initialDraft?.yearEdited ?? false);
  const [start, setStart] = useState(initialDraft?.start || '');
  const [end, setEnd] = useState(initialDraft?.end || '');
  const clock = useApplicationUtcDate();
  useEffect(() => {
    if (!clock.today) return;
    // A late clock must not mutate an input while the user is selecting/replacing it.
    if (!yearEdited.current && document.activeElement !== yearInput.current)
      setYear(current => current || clock.today.slice(0, 4));
    setStart(current => current || clock.today);
    setEnd(current => current || utcDays(clock.today, 30));
  }, [clock.today]);
  const [reference, setReference] = useState<ReferenceChoice>(() => birthReference(null));
  const { result, history, error, busy, setError, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<ReturnResult, ReturnHistory>(workspace);
  const sourceStatus = result?.source_status || 'current';
  const eventHeadings = useRef<(HTMLHeadingElement | null)[]>([]);
  const sourceVersion = useRef(0);
  useEffect(() => {
    const origin = initialDraft?.personId || initialPersonId;
    if (origin) choosePerson(origin);
    return () => { sourceVersion.current++; };
  }, []);
  const person = people.find(item => item.id === personId);
  const intent = useManualChartIntent(result);
  const personInput = useRef<HTMLSelectElement>(null);
  const restoreDraft = useRef(!!initialDraft);
  const birthYear = Number(active?.result.natal?.instant_utc?.slice(0, 4) || 0);
  const exactSource = active?.result.natal?.status === 'complete' && !!birthYear;
  const yearError = technique === 'solar_return' && birthYear && Number(year) < birthYear
    ? `Choose ${birthYear} or a later UTC anniversary year for this natal.` : '';

  function choosePerson(id: string) {
    const preservingDraft = restoreDraft.current && id === initialDraft?.personId;
    restoreDraft.current = false;
    const version = ++sourceVersion.current;
    loadPerson(id, technique, 'Saved returns could not be listed. Try choosing the person again.');
    setPersonId(id); setActive(null);
    setLoadingSource(!!id); setSourceUnavailable(false);
    setReference(birthReference(null));
    if (!id) return;
    void api<Person>(`people/${encodeURIComponent(id)}`).then(loaded => {
      if (version !== sourceVersion.current) return;
      const chart = loaded.charts.find(item => item.id === loaded.active_chart_id) || null;
      setLoadingSource(false); setActive(chart);
      const birthplace = birthReference(chart);
      const draft = initialDraft?.reference;
      const useDraft = preservingDraft && draft && draft.kind !== 'missing' && (draft.kind !== 'birthplace' ||
        (draft.latitude === birthplace.latitude && draft.longitude === birthplace.longitude));
      setReference(useDraft ? draft : birthplace);
    }).catch(() => {
      if (version === sourceVersion.current) { setLoadingSource(false); setSourceUnavailable(true); }
    });
  }

  function changeSelection() { change(); }

  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Saved return could not be opened.');
  }

  async function calculate(event: FormEvent) {
    event.preventDefault();
    if (!person || !exactSource || yearError || busy) return;
    if (reference.latitude.trim() === '' || reference.longitude.trim() === '' || reference.kind === 'missing') {
      setError('Choose a reference place or enter both precise coordinates. No location was assumed.'); return;
    }
    const place = { latitude: Number(reference.latitude), longitude: Number(reference.longitude),
      ...(reference.placeId ? { reference_place_id: reference.placeId } : {}) };
    const parameters = technique === 'solar_return'
      ? { year: Number(year), ...place }
      : { start_utc: `${start}T00:00:00+00:00`, end_utc: `${end}T00:00:00+00:00`, ...place };
    if (technique === 'lunar_return') {
      const days = (Date.parse(end) - Date.parse(start)) / 86400_000;
      if (!Number.isFinite(days) || days <= 0 || days > 732) {
        setError('Choose an end date after the start, within 732 UTC days. Your dates are still here.'); return;
      }
    }
    intent.revealResult();
    await saveResult(personId, technique, parameters, {
      prefix: 'result', reloadHistory: { error: 'Saved returns could not be listed. Try choosing the person again.' },
      displayWithoutSaving: ['no_return_in_window'],
      unavailable: status => unavailableCalculation(label, status),
      invalid: 'Check the selected year or interval and reference coordinates, then correct the form. Nothing was saved.',
      uncertain: 'Saving was not confirmed. Retry this same request or check your saved returns before starting a new one.',
    });
  }

  const moment = (instant?: string | null) => instant
    ? new Date(instant).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })
    : 'date unavailable';
  const period = (window?: string[]) => window?.length === 2
    ? `${moment(window[0])} to ${moment(window[1])} UTC (end excluded)` : 'Period unavailable';
  const historyPlace = (item: ReturnHistory) => item.reference_place_source?.label ||
    (item.reference_place_source?.kind === 'saved_birthplace_coordinates' ? 'Birthplace' :
      item.reference_place ? `Coordinates ${item.reference_place.latitude}°, ${item.reference_place.longitude}°` :
        'Reference place not recorded');

  return <section className="advanced-view" aria-label={`${label} chart`}>
    <div className="chart-hub-heading"><div><span className="eyebrow">PERSONAL TIMING</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>{label}</h1><p>{technique === 'solar_return'
        ? 'Find the Sun’s return to the saved natal longitude in a UTC anniversary cycle.'
        : 'Find every Moon return in a selected UTC interval of up to two years, not a calendar month.'}</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>Person with a current natal <select ref={personInput} required value={personId} onChange={event => choosePerson(event.target.value)}>
        <option value="">Choose a person</option>{people.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {personId && loadingSource && <p role="status">Checking this person’s current natal…</p>}
      {personId && sourceUnavailable && <p role="alert" className="manual-source-recovery">Current natal could not be checked. No calculation was started.<br />
        <button type="button" onClick={() => choosePerson(personId)}>Try checking again</button>
        {' '}<button type="button" onClick={() => personInput.current?.focus()}>Choose another person</button>
      </p>}
      {person && !loadingSource && !sourceUnavailable && !exactSource && <p role="status" className="manual-source-recovery">
        {active ? 'A supplied exact birth time is needed for this return; no time was assumed.' :
          'No current generated natal is available for this person.'}<br />
        <button type="button" onClick={() => onCreateNatal(personId,
          { personId, year, yearEdited: yearEdited.current, start, end, reference })}>Create or review natal</button>
        {' '}<button type="button" onClick={() => personInput.current?.focus()}>Choose another person</button>
      </p>}
      {technique === 'solar_return' ? <label>UTC anniversary year <input ref={yearInput} required type="number" min={birthYear || 1900} max="2098"
        value={year} onBlur={() => {
          if (!yearEdited.current && clock.today) setYear(current => current || clock.today.slice(0, 4));
        }} onChange={event => { yearEdited.current = true; changeSelection(); setYear(event.target.value); }} />
        {yearError && <span className="error" role="alert">{yearError}</span>}</label> : <>
        <label>From (UTC, inclusive) <input required type="date" value={start} onChange={event => { changeSelection(); setStart(event.target.value); }} /></label>
        <label>Until (UTC, exclusive) <input required type="date" value={end} onChange={event => { changeSelection(); setEnd(event.target.value); }} /></label>
      </>}
      {personId && !loadingSource && !sourceUnavailable &&
        <ReturnReferencePlace key={personId} workspace={workspace} value={reference} onChange={next => {
          changeSelection(); setReference(next);
        }} />}
      {clock.unavailable && <p role="status">Application date is unavailable. Choose a year or dates yourself.</p>}
      <button type="submit" className="primary" disabled={busy || !exactSource || !!yearError || reference.kind === 'missing'}>{busy ? 'Calculating…' : `Calculate ${label.toLowerCase()}`}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {sourceStatus === 'historical' && result && <p className="error" role="status">Historical return: the saved source is no longer this person’s current natal. These archived values were not recalculated.</p>}
    {result?.status === 'no_return_in_window' && <div role="status" className="advanced-results">
      <h2 ref={intent.resultHeading} tabIndex={-1}>No return crossings in this interval · 0 found</h2>
      <p>{period(result.window_utc)}. Choose another period.</p>
    </div>}
    {result?.status === 'supported' && <div className="advanced-results" aria-live="polite">
      <h2 ref={intent.resultHeading} tabIndex={-1}>{label} for {person?.name || 'saved person'} · {result.events?.length || 0} crossing{result.events?.length === 1 ? '' : 's'}</h2>
      <p>{technique === 'solar_return' ? 'Saved birth-anniversary cycle' : 'Selected interval'}: {period(result.window_utc)}. All crossings are shown, including those in the next calendar year.</p>
      {(result.events?.length || 0) > 1 && <nav className="advanced-event-choices" aria-label="Choose a return crossing">
        {result.events?.map((entry, index) => <button key={entry.instant_utc} type="button" onClick={() => {
          eventHeadings.current[index]?.scrollIntoView({ block: 'start', behavior: 'instant' });
          eventHeadings.current[index]?.focus({ preventScroll: true });
        }}>Return {index + 1} · {moment(entry.instant_utc)} UTC</button>)}
      </nav>}
      {result.source_birth?.provenance.startsWith('provisional:') &&
        <p role="status">Supplied birth details are provisional; interpret this return with that limitation.</p>}
      {result.events?.map((entry, index) => <article key={entry.instant_utc} className="advanced-event">
        <h2 ref={element => { eventHeadings.current[index] = element; }} tabIndex={-1}>
          {label} {result.events?.length === 1 ? '' : `${index + 1} · `}{moment(entry.instant_utc)} UTC
        </h2>
        <p>{result.reference_place_source?.kind === 'offline_city_centre' ? result.reference_place_source.label :
          result.reference_place_source?.kind === 'saved_birthplace_coordinates' ? 'Saved birthplace coordinates' :
          'Reference coordinates'}: {result.reference_place?.latitude}°, {result.reference_place?.longitude}°.
          {entry.chart.houses.status !== 'supported' && ' Houses and angles are unavailable at this place.'}</p>
        {result.source_birth && result.source_settings && result.id && result.person_id && result.source_birth_id &&
          result.method_version && result.engine_version && result.profile_id && result.profile_revision &&
          <ReturnWheel natal={entry.chart} resultId={`${result.id}-${index}`} personId={result.person_id}
            birthId={result.source_birth_id} label={label} methodVersion={result.method_version}
            profileId={result.profile_id} profileRevision={result.profile_revision} sourceStatus={sourceStatus}
            sourceBirth={result.source_birth} sourceSettings={result.source_settings}
            engineVersion={result.engine_version} additionalProvenance={{
              reference_place: result.reference_place, reference_place_source: result.reference_place_source,
              window_utc: result.window_utc }} />}
        {result.id && result.person_id && onDiscuss && <button type="button" onClick={() => onDiscuss(result.person_id!,
          { result_id: result.id!, event_index: index },
          `${label} · ${moment(entry.instant_utc)} UTC`)}>Discuss this crossing</button>}
      </article>)}
    </div>}
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved returns">
      <h2>Saved {label.toLowerCase()}</h2>
      {history.map(item => <button key={item.id} type="button" onClick={() => void openSaved(item.id)}>
        Open saved {label.toLowerCase()} · {item.window_utc?.length === 2 ? period(item.window_utc) :
          moment(item.first_utc)}{item.event_count != null &&
          ` · ${item.event_count} crossing${item.event_count === 1 ? '' : 's'}`} · {historyPlace(item)}
      </button>)}
    </nav>}
  </section>;
}
