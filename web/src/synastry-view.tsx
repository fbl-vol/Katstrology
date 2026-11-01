import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from './api';
import { bodyGlyph, bodyLabel, ChartNotation, chartNotation } from './chart-symbols';
import { WheelExportActions } from './chart-export';
import { point, signs, zodiac } from './natal';
import type { Person } from './people';

type Position = { id: string; longitude_degrees: number };
type Aspect = { a_body_id: string; b_body_id: string; aspect: string; orb_degrees: number; exact_degrees: number };
type Overlay = { status: string; recipient_house_system: string;
  placements: { body_id: string; longitude_degrees: number; recipient_house: number }[] };
export type SynastryData = {
  status: string; source_status?: string; missing_person_ids?: string[]; reason?: string;
  chart_a_id?: string; chart_b_id?: string; person_a_id?: string; person_b_id?: string;
  profile_a_id?: string; profile_b_id?: string; profile_a_revision?: number; profile_b_revision?: number;
  engine_a_version?: string; engine_b_version?: string; ephemeris_sha256?: Record<string, string>;
  a_house_system?: string; b_house_system?: string; a_angles?: boolean; b_angles?: boolean;
  a_birth_time?: string; b_birth_time?: string; unit?: string; zodiac?: string; method?: string;
  orb_policy?: Record<string, number>; total_aspects?: number; truncated?: boolean;
  aspects?: Aspect[]; positions_a?: Position[]; positions_b?: Position[];
  house_overlays?: { status: string; method_version: string; placement_rule: string;
    a_in_b: Overlay; b_in_a: Overlay };
};

function PositionRing({ positions, radius, stroke }: { positions: Position[]; radius: number; stroke: string }) {
  const sorted = [...positions].sort((a, b) => a.longitude_degrees - b.longitude_degrees);
  return <>{sorted.map((body, index) => {
    const tick = point(body.longitude_degrees, 0, radius + 12);
    const label = point(body.longitude_degrees, 0, radius - (index % 3) * 9);
    return <g key={body.id}><line x1={tick.x} y1={tick.y} x2={label.x} y2={label.y} stroke={stroke} strokeWidth=".9" />
      <circle cx={label.x} cy={label.y} r="10" fill="var(--wheel-paper, #fffef9)" stroke={stroke} />
      <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize="16" fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'} fill="var(--wheel-glyph, #243f3c)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>;
  })}</>;
}

function PairWheel({ result, aName, bName }: { result: SynastryData; aName: string; bName: string }) {
  const svg = useRef<SVGSVGElement>(null);
  return <div className="natal-wheel-frame"><p className="wheel-scroll-hint">Swipe the wheel sideways for the full chart.</p><div className="natal-wheel-scroll"><svg ref={svg} className="natal-wheel" viewBox="0 0 480 480" role="img" aria-labelledby="pair-title pair-desc" xmlns="http://www.w3.org/2000/svg">
    <title id="pair-title">Two-person tropical chart: outer ring {aName}; inner ring {bName}</title>
    <desc id="pair-desc">Two separately calculated natal position rings. Outer teal is {aName}; inner amber is {bName}. Wheel labels: {chartNotation}. Sign labels use the first three letters. No house sectors, compatibility score or aspect formations are drawn; tables show exact longitudes, directional house overlays and calculated aspects.</desc>
    <rect width="480" height="480" rx="20" fill="var(--wheel-paper, #fffef9)" />
    {[105, 135, 175, 190].map(radius => <circle key={radius} cx="240" cy="240" r={radius} fill="none" stroke="var(--wheel-ring, #c4d2c7)" />)}
    {signs.map((sign, index) => {
      const label = point(index * 30 + 15, 0, 206);
      const edge = point(index * 30, 0, 175);
      const end = point(index * 30, 0, 190);
      return <g key={sign}><line x1={edge.x} y1={edge.y} x2={end.x} y2={end.y} stroke="var(--wheel-ring, #c4d2c7)" />
        <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize="10" fill="var(--wheel-ink, #3b5f51)">{sign.slice(0, 3)}</text></g>;
    })}
    <PositionRing positions={result.positions_a || []} radius={168} stroke="var(--wheel-sky, #2c716b)" />
    <PositionRing positions={result.positions_b || []} radius={111} stroke="var(--wheel-natal, #a46c3e)" />
    <text x="240" y="239" textAnchor="middle" fill="var(--wheel-ink, #2b503b)" fontSize="15" fontFamily="Georgia, serif">Two natal charts</text>
    <text x="240" y="257" textAnchor="middle" fill="var(--wheel-muted, #52684e)" fontSize="10">No scores · overlays in tables</text>
  </svg></div><p className="wheel-scroll-hint">Scroll sideways for the full wheel. The tables give the exact longitudes and full names.</p>
    <ChartNotation ids={[...(result.positions_a || []), ...(result.positions_b || [])].map(body => body.id)} rings={`Outer teal marks ${aName}; inner amber marks ${bName}. No house sectors or aspect lines are drawn.`} />
    <WheelExportActions svgRef={svg} stem={`kat-pair-${result.chart_a_id}-${result.chart_b_id}`}
      provenance={{ person_a_id: result.person_a_id, person_b_id: result.person_b_id,
        chart_a_id: result.chart_a_id, chart_b_id: result.chart_b_id,
        profile_a_id: result.profile_a_id, profile_b_id: result.profile_b_id,
        profile_a_revision: result.profile_a_revision, profile_b_revision: result.profile_b_revision,
        engine_a_version: result.engine_a_version, engine_b_version: result.engine_b_version,
        ephemeris_sha256: result.ephemeris_sha256, method: result.method,
        orb_policy: result.orb_policy, house_overlays: result.house_overlays }} />
  </div>;
}

export function SynastryView({ workspace, people, onClose, onCreate, onDiscuss, discussionDisabled = false }: {
  workspace: Workspace; people: Person[]; onClose: () => void;
  onCreate: (personId: string) => void; onDiscuss: (people: string[]) => void;
  discussionDisabled?: boolean;
}) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [result, setResult] = useState<SynastryData | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState('');
  const [historical, setHistorical] = useState(false);
  const [history, setHistory] = useState<{ id: string; created_at: string; person_b_id: string }[]>([]);
  const saveRequest = useRef('');
  const version = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => cancelAnimationFrame(frame); }, []);
  function change() { version.current++; setResult(null); setError(''); setBusy(false); setSaving(false);
    setSavedId(''); setHistory([]); saveRequest.current = ''; setHistorical(false); }

  useEffect(() => {
    if (!a || !b || a === b) return;
    const current = version.current;
    void api<{ results: { id: string; created_at: string; person_b_id: string }[] }>(
      `advanced-results?person_id=${encodeURIComponent(a)}&technique=synastry_overlay`)
      .then(response => { if (current === version.current)
        setHistory(response.results.filter(item => item.person_b_id === b)); })
      .catch(() => { if (current === version.current) setError('Saved comparisons could not be listed. The current comparison is still available.'); });
  }, [a, b]);

  async function save() {
    if (!result || result.status !== 'supported' || !a || !b) return;
    const current = version.current;
    const id = saveRequest.current || `overlay-${crypto.randomUUID()}`;
    saveRequest.current = id;
    setSaving(true); setError('');
    try {
      const saved = await api<SynastryData & { id: string }>('advanced-results', workspace.csrf, 'POST', {
        id, person_id: a, technique: 'synastry_overlay', parameters: { person_b_id: b },
      });
      if (current !== version.current) return;
      setSavedId(saved.id); setResult(saved); setHistorical(saved.source_status === 'historical');
      setHistory(rows => rows.some(row => row.id === saved.id) ? rows : [
        { id: saved.id, created_at: new Date().toISOString(), person_b_id: b }, ...rows]);
    } catch {
      if (current === version.current) setError('Save was not confirmed. Retry the same save request; do not create another comparison.');
    } finally { if (current === version.current) setSaving(false); }
  }

  async function openSaved(id: string) {
    const current = ++version.current;
    setResult(null); setError(''); setSavedId('');
    try {
      const saved = await api<{ result: SynastryData; source_status: string }>(
        `advanced-results/${encodeURIComponent(id)}`);
      if (current === version.current) {
        setResult(saved.result); setSavedId(id);
        setHistorical(saved.source_status === 'historical');
      }
    } catch { if (current === version.current) setError('Could not open the archived comparison.'); }
  }

  async function compare(event: React.FormEvent) {
    event.preventDefault();
    const current = ++version.current;
    setResult(null); setError(''); setBusy(true);
    try {
      const params = new URLSearchParams({ person_a_id: a, person_b_id: b });
      const output = await api<SynastryData>(`synastry?${params.toString()}`);
      if (current === version.current) { setResult(output); setSavedId(''); setHistorical(false); saveRequest.current = ''; }
    } catch (cause) {
      if (current === version.current) setError(cause instanceof ApiError && cause.status === 404 ?
        'A selected person is no longer in this workspace. Choose two available people.' :
        'This comparison was not calculated. Choose two distinct people and try again.');
    } finally { if (current === version.current) setBusy(false); }
  }

  const aName = people.find(person => person.id === a)?.name || 'Person A';
  const bName = people.find(person => person.id === b)?.name || 'Person B';
  return <section className="synastry-page" aria-label="Synastry chart">
    <div className="transit-heading"><div><span className="eyebrow">RELATIONSHIPS</span><h1 ref={heading} tabIndex={-1}>Synastry</h1>
      <p>Compare two people's current natal positions and aspects, side by side. This is not a compatibility score.</p></div>
      <button type="button" onClick={onClose}>Back to chart choices</button></div>
    <form className="synastry-controls" onSubmit={event => void compare(event)}>
      <label>Person A<select value={a} required onChange={event => { change(); setA(event.target.value); }}><option value="">Choose person</option>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>Person B<select value={b} required onChange={event => { change(); setB(event.target.value); }}><option value="">Choose person</option>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <button className="primary" type="submit" disabled={busy || !a || !b || a === b}>{busy ? 'Calculating…' : 'Compare charts'}</button>
    </form>
    {a && b && a === b && <p className="error" role="alert">Choose two different people; no chart was calculated.</p>}
    {history.length > 0 && <nav className="advanced-history" aria-label="Saved comparisons"><h2>Saved comparisons</h2>
      {history.map(item => <button key={item.id} type="button" onClick={() => void openSaved(item.id)}>
        Open saved comparison · {item.created_at.slice(0, 10)}
      </button>)}
    </nav>}
    {error && <p className="error" role="alert">{error}</p>}
    {result?.status === 'no_active_natal' && <div role="status" className="synastry-unavailable"><p>Both people need a current generated natal. An older or uploaded chart is never substituted.</p>
      {result.missing_person_ids?.map(id => <button type="button" key={id} onClick={() => onCreate(id)}>Create chart for {people.find(person => person.id === id)?.name || 'person'}</button>)}</div>}
    {result && result.status !== 'supported' && result.status !== 'no_active_natal' && <p className="synastry-unavailable" role="status">Comparison unavailable. {result.status === 'unsupported_stale_birth_source'
      ? 'One chart uses superseded birth details. Update it before comparing.'
      : result.status === 'unsupported_uncertain_birth_time_or_non_natal_chart'
        ? 'Both charts need exact supplied birth instants; no approximate time was substituted.'
        : result.status === 'unsupported_incompatible_aspect_profiles'
          ? 'Both charts must use matching zodiac, aspects and orb settings.'
          : result.status === 'unsupported_different_engine_data_versions'
            ? 'The charts use different calculation versions. Recalculate them before comparing.'
            : 'Both charts need current sources and compatible calculation settings.'}</p>}
    {result?.status === 'supported' && <div className="synastry-result" aria-live="polite">
      <h2>{aName} · {bName}</h2>
      <p className="pair-ring-key">A · {aName} (outer teal) · B · {bName} (inner amber). Exact degrees and aspects are in the tables.</p>
      {historical && <p role="status" className="error">Historical comparison: one or both source charts are no longer current. These archived placements were not recalculated.</p>}
      {savedId ? <p role="status">Saved comparison; reopen it from Saved comparisons after a refresh.</p> :
        <button type="button" disabled={saving} onClick={() => void save()}>{saving ? 'Saving comparison…' : 'Save this comparison'}</button>}
      <PairWheel result={result} aName={aName} bName={bName} />
      {(!result.a_angles || !result.b_angles) && <p className="natal-qualification">Houses or angles are unavailable for one of these charts; only the supported direction of house overlay is shown.</p>}
      {([['a', aName, result.positions_a], ['b', bName, result.positions_b]] as const).map(([key, name, positions]) => <div className="transit-tables" key={key}><table><caption>{key.toUpperCase()} · {name}</caption><thead><tr><th scope="col">Natal position</th><th scope="col">Sign and degree</th><th scope="col">Longitude</th></tr></thead><tbody>{positions?.map(body => <tr key={body.id}><th scope="row">{bodyLabel(body.id)}</th><td>{zodiac(body.longitude_degrees)}</td><td>{body.longitude_degrees.toFixed(4)}°</td></tr>)}</tbody></table></div>)}
      <p className="transit-scroll-hint">Swipe the tables sideways to see every column.</p>
      <div className="transit-tables"><h3>Inter-chart aspects · {result.total_aspects} found; showing {result.aspects?.length} closest</h3><table><caption className="sr-only">A to B inter-chart ecliptic aspects</caption><thead><tr><th scope="col">A · {aName}</th><th scope="col">Aspect</th><th scope="col">B · {bName}</th><th scope="col">Orb</th></tr></thead><tbody>{result.aspects?.map((aspect, index) => <tr key={`${aspect.a_body_id}-${aspect.b_body_id}-${index}`}><th scope="row">{bodyLabel(aspect.a_body_id)}</th><td>{aspect.aspect}</td><td>{bodyLabel(aspect.b_body_id)}</td><td>{aspect.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
        {result.truncated && <p>Only the 12 closest aspects are shown; additional aspects were calculated but omitted.</p>}
        {!result.total_aspects && <p>No aspects fall within the shared orb policy.</p>}</div>
      {result.house_overlays && <section className="synastry-overlays" aria-label="Directional house overlays">
        <h3>Planets in each other’s houses</h3>
        <p>Each planet’s saved ecliptic longitude is projected into the other person’s own natal house convention. A cusp belongs to the house it begins.</p>
        {([['a_in_b', aName, bName], ['b_in_a', bName, aName]] as const).map(([key, donor, recipient]) => {
          const overlay = result.house_overlays![key];
          return <div key={key} className="transit-tables" role="region" aria-label={`${donor} in ${recipient} houses`}>
            <h4>{donor}’s planets in {recipient}’s houses</h4>
            {overlay.status !== 'supported' ? <p role="status">Unavailable: {recipient}’s {overlay.recipient_house_system} houses are not supported ({overlay.status}). No substitute houses were inferred.</p> :
              <table><caption>{donor} → {recipient} · {overlay.recipient_house_system} houses</caption>
                <thead><tr><th scope="col">{donor}’s planet</th><th scope="col">Longitude</th><th scope="col">{recipient}’s house</th></tr></thead>
                <tbody>{overlay.placements.map(point => <tr key={point.body_id}><th scope="row">{bodyLabel(point.body_id)}</th><td>{zodiac(point.longitude_degrees)}</td><td>{point.recipient_house}</td></tr>)}</tbody></table>}
          </div>;
        })}
      </section>}
      <details className="chart-supporting-data"><summary>How this comparison works</summary>
        <p>The rings show separate tropical positions, not a composite. House overlays are labelled in their own tables, not drawn as sectors. A new discussion uses the current charts when a message is sent; it does not attach this manual result.</p>
      </details>
      {discussionDisabled && <p role="status">Finish or check the pending conversation before starting a different discussion. This chart did not change your draft.</p>}
      <button type="button" disabled={discussionDisabled} onClick={() => onDiscuss([a, b])}>Start conversation about these people</button>
    </div>}
  </section>;
}
