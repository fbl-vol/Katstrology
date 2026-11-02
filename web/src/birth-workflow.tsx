import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from './api';
import type { Person } from './people';
import { NatalChart, type Chart } from './natal';

type Place = { id: string; name: string; region: string; country: string; latitude: number; longitude: number; zone: string };
export type Generation = { birth_id: string; draft_revision: number; chart: Chart; active_chart_id: string | null;
  provisional: boolean; reused: boolean };
const defaultOrbs: Record<string, number> = { conjunction: 8, opposition: 8, square: 6, trine: 6, sextile: 4 };
const browserZones = ['UTC', ...(Intl.supportedValuesOf?.('timeZone') || [])];
const placeLabel = (place: Place) => [place.name, place.region, place.country].filter(Boolean).join(', ');

function explanation(code: string): string {
  switch (code) {
    case 'select_place_or_advanced_location': return 'Choose a city from the local results, or open Advanced and supply both coordinates and an IANA timezone. No location was inferred.';
    case 'select_place_again': return 'The place changed or is no longer in the offline list. Choose a listed city again.';
    case 'choose_dst_occurrence': return 'This local hour occurred twice. In Advanced, choose the first or second occurrence before generating.';
    case 'nonexistent_local_time': return 'This local hour did not occur on that date in the selected timezone. Correct the supplied time; no birth time was guessed.';
    case 'invalid_timezone': return 'The timezone is not a valid IANA identifier. Check its canonical spelling in Advanced.';
    case 'coordinates_required_together': return 'Advanced location needs both latitude and longitude.';
    case 'unsupported_birth_or_chart': return 'The supplied date, day interval, coordinates or chart is outside the supported calculation range. Nothing was saved.';
    case 'unsupported_local_day': return 'This historical local date cannot form a supported day interval. Check the date and timezone.';
    case 'request_conflict': return 'The saved request identity belongs to different inputs. Change the inputs to begin a new request.';
    case 'chiron_data_missing_or_unverified': return 'Chiron cannot be calculated with the chart data available here. No chart was saved. Turn off Include Chiron to continue with the other planets.';
    default: return 'The birth details could not be accepted. Check the date, time, selected place and Advanced settings. Nothing was saved.';
  }
}

export function BirthWorkflow({ person, workspace, refresh, discussChart, onGenerated, compact = false }: {
  person: Person; workspace: Workspace; refresh: () => Promise<void>;
  discussChart: () => void; onGenerated?: (result: Generation, draft: Person['drafts'][number]['details']) => void; compact?: boolean;
}) {
  const savedDraft = person.drafts[0]?.details;
  const activeSettings = person.charts.find(chart => chart.id === person.active_chart_id)?.result.profile.settings;
  const [day, setDay] = useState(savedDraft?.birth_date || '');
  const [hour, setHour] = useState(savedDraft?.birth_time || '');
  const [unknown, setUnknown] = useState(savedDraft?.time_unknown || false);
  const [provisional, setProvisional] = useState(true);
  const [query, setQuery] = useState(savedDraft?.birthplace || '');
  const [place, setPlace] = useState<Place | null>(null);
  const [matches, setMatches] = useState<Place[]>([]);
  const [placeError, setPlaceError] = useState('');
  const [zone, setZone] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [fold, setFold] = useState('');
  const [needFold, setNeedFold] = useState(false);
  const [house, setHouse] = useState(activeSettings?.house_system || 'placidus');
  const [node, setNode] = useState(activeSettings?.node_type || 'true');
  const [includeChiron, setIncludeChiron] = useState(activeSettings?.include_chiron === true);
  const [lilith, setLilith] = useState(activeSettings?.include_lilith || 'off');
  const [orbs, setOrbs] = useState(activeSettings?.orbs || defaultOrbs);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [generated, setGenerated] = useState<Generation | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const requestId = useRef<string | null>(null);
  const submitting = useRef(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const timeRef = useRef<HTMLInputElement>(null);
  const placeRef = useRef<HTMLInputElement>(null);
  const zoneRef = useRef<HTMLInputElement>(null);
  const foldRef = useRef<HTMLSelectElement>(null);
  const chironRef = useRef<HTMLInputElement>(null);
  const advancedRef = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (!busy && error === explanation('chiron_data_missing_or_unverified')) {
      if (advancedRef.current) advancedRef.current.open = true;
      chironRef.current?.focus();
    }
  }, [busy, error]);

  useEffect(() => {
    if (place || query.trim().length < 2) { setMatches([]); return; }
    let current = true;
    const timer = window.setTimeout(() => {
      void api<{ places: Place[] }>('places/search', workspace.csrf, 'POST', { query: query.trim() })
        .then(result => { if (current) { setMatches(result.places); setPlaceError(''); } })
        .catch(() => { if (current) setPlaceError('Local place suggestions are unavailable. Advanced manual location remains possible.'); });
    }, 180);
    return () => { current = false; window.clearTimeout(timer); };
  }, [query, place?.id, workspace.owner]);

  function changed() {
    requestId.current = null; setGenerated(null); setUnconfirmed(false); setError(''); setStatus('');
    setNeedFold(false); setFold('');
  }

  const typedZone = zone.trim();
  const canonical = browserZones.find(item => item.toLowerCase() === typedZone.toLowerCase());
  const suggestions = typedZone.length >= 3 && canonical !== typedZone ? browserZones
    .filter(item => item.toLowerCase().includes(typedZone.toLowerCase())).slice(0, 5) : [];
  const selectedZone = typedZone || place?.zone || '';

  async function generate(event?: React.FormEvent) {
    event?.preventDefault();
    if (submitting.current || generated) return;
    if (!place && (!typedZone || latitude === '' || longitude === '')) {
      setError(explanation('select_place_or_advanced_location')); placeRef.current?.focus(); return;
    }
    if (typedZone && canonical && canonical !== typedZone) {
      setError(`Use the exact timezone spelling ${canonical} in Advanced, then generate again.`);
      zoneRef.current?.focus(); return;
    }
    submitting.current = true; setBusy(true); setError(''); setStatus('Generating and saving the chart…');
    const id = requestId.current || `generate-${crypto.randomUUID()}`;
    requestId.current = id;
    const settings = house !== 'placidus' || node !== 'true' || includeChiron || lilith !== 'off' ||
      Object.keys(defaultOrbs).some(key => orbs[key] !== defaultOrbs[key]) ?
      { chart_kind: 'natal', zodiac: 'tropical', house_system: house, node_type: node,
        aspects: Object.keys(defaultOrbs), orbs, ...(includeChiron ? { include_chiron: true } : {}),
        ...(lilith !== 'off' ? { include_lilith: lilith } : {}) } : null;
    try {
      const result = await api<Generation>(`people/${person.id}/generate`, workspace.csrf, 'POST', {
        request_id: id, birth_date: day, birth_time: unknown ? '' : hour, time_unknown: unknown,
        birthplace: place ? placeLabel(place) : query.trim(), place_id: place?.id || null,
        provisional, zone_override: typedZone || null,
        latitude_override: latitude === '' ? null : Number(latitude),
        longitude_override: longitude === '' ? null : Number(longitude),
        fold: fold === '' ? null : Number(fold), settings,
      });
      setGenerated(result);
      onGenerated?.(result, { birth_date: day, birth_time: unknown ? '' : hour,
        birthplace: place ? placeLabel(place) : query.trim(), time_unknown: unknown });
      setUnconfirmed(false);
      setStatus(result.active_chart_id !== result.chart.id ?
        'This was a retry of an older request. Its original chart is intact but is not the current natal; no active chart changed.' :
        `Current natal saved.${result.provisional ? ' Details remain provisional.' : ''}`);
      try { await refresh(); }
      catch { setStatus('The chart was saved, but the person list could not refresh. Do not generate again; revisit this person to load its history.'); }
      window.requestAnimationFrame(() => resultRef.current?.scrollIntoView({ block: 'nearest' }));
    } catch (cause) {
      setStatus('');
      if (cause instanceof ApiError && [400, 409].includes(cause.status)) {
        setError(explanation(cause.code)); setUnconfirmed(false); requestId.current = null;
        if (cause.code === 'choose_dst_occurrence') {
          setNeedFold(true); if (advancedRef.current) advancedRef.current.open = true;
          window.requestAnimationFrame(() => foldRef.current?.focus());
        } else if (cause.code === 'nonexistent_local_time') timeRef.current?.focus();
        else if (cause.code === 'invalid_timezone') zoneRef.current?.focus();
        else if (cause.code.startsWith('select_place')) placeRef.current?.focus();
      } else {
        setError('Save was not confirmed. Do not start another version; retry this exact request ID to check the archive without duplicate calculation.');
        setUnconfirmed(true);
      }
    } finally { submitting.current = false; setBusy(false); }
  }

  return <section className="birth-workflow" aria-label="Generate a chart">
    <h2>Birth details</h2>
    <p>One chart from the details you supply. A city is a reference, not exact birth coordinates. {savedDraft ?
      'Review the saved details and choose the birthplace again (or enter an Advanced manual location); an old label is not a selected place.' :
      'Nothing is inferred from an unselected place label.'}</p>
    <form onSubmit={event => void generate(event)}>
      <fieldset disabled={busy || !!generated}>
        <label>Birth date <input type="date" required value={day} onChange={event => { changed(); setDay(event.target.value); }} /></label>
        <label className="check"><input type="checkbox" checked={unknown} onChange={event => { changed(); setUnknown(event.target.checked); setHour(''); setFold(''); }} />Time unknown</label>
        {!unknown && <label>Birth time <input ref={timeRef} type="time" required value={hour} onChange={event => { changed(); setHour(event.target.value); }} /></label>}
        <label>Birthplace search <input ref={placeRef} autoComplete="off" value={query} placeholder="Search city, then choose country and region" onChange={event => { changed(); setPlace(null); setQuery(event.target.value); }} /></label>
        {matches.length > 0 && <div className="place-results" role="group" aria-label="Offline birthplace results">{matches.map(item =>
          <button type="button" key={item.id} onClick={() => { changed(); setPlace(item); setQuery(placeLabel(item)); setMatches([]); }}>
            {placeLabel(item)} <small>GeoNames city centre · {item.zone}</small>
          </button>)}</div>}
        {placeError && <p className="error" role="alert">{placeError}</p>}
        {place && <p className="place-selected" role="status">Selected {placeLabel(place)} · GeoNames city-centre reference ({place.latitude}, {place.longitude}) · {place.zone}. If birth was near a timezone border, inspect/override in Advanced.</p>}
        <label className="check"><input type="checkbox" checked={provisional} onChange={event => { changed(); setProvisional(event.target.checked); }} />Details are provisional</label>
        <p>Leave checked if the details may change. This choice does not verify a birth record; unknown time cannot produce an Ascendant or houses.</p>
        <details ref={advancedRef} className="birth-advanced"><summary>Advanced · chart settings and location</summary>
          <p>Tropical zodiac · ten planets, true north node, Placidus houses, five major aspects. Defaults: conjunction/opposition 8°, square/trine 6°, sextile 4°. Other values apply to the chart you generate.</p>
          <label>House system <select value={house} onChange={event => { changed(); setHouse(event.target.value); }}><option value="placidus">Placidus</option><option value="whole_sign">Whole sign</option></select></label>
          <label>North node <select value={node} onChange={event => { changed(); setNode(event.target.value); }}><option value="true">True node</option><option value="mean">Mean node</option></select></label>
          <label className="check"><input ref={chironRef} type="checkbox" checked={includeChiron} onChange={event => { changed(); setIncludeChiron(event.target.checked); }} />Include Chiron in this chart and its aspects</label>
          <label>Black Moon Lilith (lunar apogee) <select value={lilith} onChange={event => { changed(); setLilith(event.target.value); }}>
            <option value="off">Off (default)</option><option value="mean">Mean lunar apogee</option>
            <option value="osculating">True / osculating lunar apogee</option>
          </select></label>
          <p>Optional for this chart and its aspects. “True” names an osculating orbital model, not a more accurate answer. Neither is asteroid 1181 Lilith or Waldemath’s hypothetical moon; leave off to keep the standard chart.</p>
          <div className="birth-orbs"><strong>Major aspect orbs (degrees)</strong>{Object.keys(defaultOrbs).map(key => <label key={key}>{key}<input type="number" step="0.1" min="0.1" max="10" value={orbs[key]} onChange={event => { changed(); setOrbs(current => ({ ...current, [key]: Number(event.target.value) })); }} /></label>)}</div>
          <p>Coordinates below replace the listed city centre only when both are entered. Without a selected place, supply both coordinates and a canonical IANA timezone; the birthplace label stays user-supplied.</p>
          <div className="two-col"><label>Latitude override <input type="number" step="any" min="-90" max="90" value={latitude} onChange={event => { changed(); setLatitude(event.target.value); }} /></label>
            <label>Longitude override <input type="number" step="any" min="-180" max="180" value={longitude} onChange={event => { changed(); setLongitude(event.target.value); }} /></label></div>
          <label>IANA timezone override <input ref={zoneRef} value={zone} placeholder={place?.zone || 'e.g. Europe/Copenhagen'} onChange={event => { changed(); setZone(event.target.value); }} /></label>
          {suggestions.length > 0 && <div className="birth-zone-options" aria-label="Timezone suggestions">{suggestions.map(item =>
            <button type="button" key={item} onClick={() => { changed(); setZone(item); zoneRef.current?.focus(); }}>Use {item}</button>)}</div>}
          {needFold && <label>Repeated birth hour <select ref={foldRef} value={fold}
            onChange={event => { requestId.current = null; setGenerated(null); setError(''); setFold(event.target.value); }}>
            <option value="">Choose occurrence</option><option value="0">First occurrence</option><option value="1">Second occurrence</option>
          </select></label>}
          {selectedZone && <small>Calculation timezone: {selectedZone}. Historical offsets come from IANA rules, not today's UTC offset.</small>}
        </details>
        <button className="primary" type="submit" disabled={busy || !!generated}>{busy ? 'Generating chart…' : generated ? 'Chart saved' : 'Generate chart'}</button>
      </fieldset>
      {error && <p className="error" role="alert">{error}</p>}
      {status && <p className="birth-status" role="status">{status}</p>}
    </form>
    {unconfirmed && <button type="button" className="quiet-action" onClick={() => void generate()}>Retry same chart request</button>}
    {generated && <button type="button" className="quiet-action" onClick={changed}>Update the current natal</button>}
    {generated && !compact && <div ref={resultRef} className="generated-chart" role="region" aria-label="Generated chart">
      <h2>{generated.chart.id === generated.active_chart_id ? 'Current natal' : 'Historical chart'}</h2>
      {generated.chart.id === generated.active_chart_id && <button type="button" className="quiet-action" onClick={discussChart}>Discuss current natal</button>}
      <NatalChart chart={generated.chart} />
    </div>}
  </section>;
}
