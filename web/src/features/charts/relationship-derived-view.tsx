import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { Workspace } from '../../shared/api';
import { useManualResultLifecycle } from './manual-result-lifecycle';
import { unavailableCalculation } from './advanced-result-status';
import { useManualChartIntent } from './manual-chart-intent';
import { bodyGlyph, bodyLabel, ChartNotation } from './chart-symbols';
import { WheelExportActions } from './chart-export';
import { point, ReturnWheel, signs, zodiac, type Chart, type NatalResult } from './natal';
import type { Person } from '../people/people';

type Technique = 'midpoint_composite' | 'uncorrected_davison';
type CompositePoint = { id: string; status: string; longitude_degrees: number | null;
  source_a_degrees: number; source_b_degrees: number };
export type Derived = { id?: string; status: string; technique: Technique; method_version: string;
  chart_a_id: string; chart_b_id: string; person_a_id: string; person_b_id: string;
  source_a_birth_id: string; source_b_birth_id: string;
  source_a_birth: Record<string, unknown>; source_b_birth: Record<string, unknown>;
  profile_a_id: string; profile_a_revision: number; profile_b_id: string; profile_b_revision: number;
  engine_a_version: string; engine_b_version: string; engine_version: string;
  ephemeris_a_sha256: Record<string, string>; ephemeris_b_sha256: Record<string, string>;
  source_settings: Chart['result']['profile']['settings'];
  derived_settings: Chart['result']['profile']['settings']; source_status?: string;
  positions: CompositePoint[]; position_status: string;
  aspects: { first: string; second: string; kind: string; orb_degrees: number }[];
  aspects_total: number; aspects_truncated: boolean;
  derived_instant_utc: string; derived_latitude: number; derived_longitude: number;
  derived_status: string; derived_natal: NatalResult; geography_policy: string; chiron_policy: string };

function CompositeWheel({ result }: { result: Derived }) {
  const svg = useRef<SVGSVGElement>(null);
  const shown = result.positions.filter(item => item.longitude_degrees !== null);
  const sorted = [...shown].sort((a, b) => a.longitude_degrees! - b.longitude_degrees!);
  let previous = sorted[sorted.length - 1]?.longitude_degrees! - 360 || -360;
  let cluster = 0;
  const labels = sorted.map(body => {
    cluster = body.longitude_degrees! - previous < 12 ? cluster + 1 : 0;
    previous = body.longitude_degrees!;
    return { body, radius: 150 + (cluster % 3) * 17 };
  });
  return <div className="natal-wheel-frame"><div className="natal-wheel-scroll"><svg ref={svg} className="natal-wheel"
    xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 480" role="img" aria-labelledby="composite-title composite-desc">
    <title id="composite-title">Shortest-circle symbolic composite of two saved natal charts</title>
    <desc id="composite-desc">Each planet is the shortest circular midpoint of two natal longitudes. An exactly opposite pair has no unique midpoint and is omitted from the wheel. There are no houses, axes or physical event instant; the table lists source degrees.</desc>
    <rect width="480" height="480" rx="20" fill="var(--wheel-paper, #fffef9)" />
    {[130, 188].map(radius => <circle key={radius} cx="240" cy="240" r={radius} fill="none" stroke="var(--wheel-ring, #b6c8b8)" />)}
    {signs.map((sign, index) => { const p = point(index * 30 + 15, 0, 206);
      return <text key={sign} x={p.x} y={p.y} textAnchor="middle" fontSize="11" fill="var(--wheel-ink, #3b5f51)">{sign.slice(0, 3)}</text>; })}
    {labels.map(({ body, radius }) => { const p = point(body.longitude_degrees!, 0, radius);
      const tick = point(body.longitude_degrees!, 0, 130);
      return <g key={body.id}><line x1={tick.x} y1={tick.y} x2={p.x} y2={p.y} stroke="var(--wheel-sky, #487b72)" />
        <circle cx={p.x} cy={p.y} r="11" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-sky, #487b72)" />
        <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="middle" fontSize="16" fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'} fill="var(--wheel-glyph, #224432)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>; })}
    <text x="240" y="228" textAnchor="middle" fontSize="13" fill="var(--wheel-ink, #3b5f51)">Symbolic midpoint</text>
  </svg></div>
    <ChartNotation ids={shown.map(item => item.id)} rings="A single symbolic midpoint ring, without physical sky, houses or axes." />
    <WheelExportActions svgRef={svg} stem={`kat-composite-${result.id || 'preview'}`} provenance={{
      technique: result.technique, method_version: result.method_version,
      chart_a_id: result.chart_a_id, chart_b_id: result.chart_b_id,
      source_a_birth_id: result.source_a_birth_id, source_b_birth_id: result.source_b_birth_id,
      source_a_birth: result.source_a_birth, source_b_birth: result.source_b_birth,
      profile_a_id: result.profile_a_id, profile_a_revision: result.profile_a_revision,
      profile_b_id: result.profile_b_id, profile_b_revision: result.profile_b_revision,
      ephemeris_a_sha256: result.ephemeris_a_sha256,
      ephemeris_b_sha256: result.ephemeris_b_sha256,
      positions: result.positions, position_status: result.position_status,
      source_status: result.source_status,
    }} />
  </div>;
}

export function RelationshipDerivedView({ workspace, people, onClose, savedResult, initialPersonId }: {
  workspace: Workspace; people: Pick<Person, 'id' | 'name' | 'active_chart_id'>[]; onClose: () => void; initialPersonId?: string;
  savedResult?: Derived;
}) {
  const [first, setFirst] = useState(initialPersonId || '');
  const [second, setSecond] = useState('');
  const [technique, setTechnique] = useState<Technique>('midpoint_composite');
  const { result: calculated, history, busy, error, setError, change,
    choosePerson: loadPerson, calculate: saveResult, openSaved: openResult } =
    useManualResultLifecycle<Derived, { id: string; created_at: string }>(workspace);
  const result = savedResult || calculated;
  const intent = useManualChartIntent(result);
  useEffect(() => {
    if (!savedResult) loadPerson(first, technique, 'Could not list saved relationship charts.');
  }, [first, technique, savedResult]);
  async function calculate(event: FormEvent) {
    event.preventDefault();
    if (first === second) { setError('Choose two different people with current natals.'); return; }
    intent.revealResult();
    await saveResult(first, technique, { person_b_id: second }, {
      prefix: 'relationship',
      firstRow: (_, id) => ({ id, created_at: new Date().toISOString() }),
      unavailable: status => unavailableCalculation('Derived chart', status),
      invalid: 'Check both current natal sources and the selected technique, then correct the selection. No chart was saved.',
      uncertain: 'Saving was not confirmed. Retry the same request or check saved derived charts before starting another.',
    });
  }
  function openSaved(id: string) {
    intent.revealResult(); void openResult(id, 'Could not open the archived derived chart.');
  }
  const name = (id: string) => people.find(person => person.id === id)?.name || 'saved person';
  return <section className="advanced-view" aria-label="Relationship-derived chart">
    <div className="transit-heading"><div><span className="eyebrow">RELATIONSHIP CHARTS</span>
      <h1 ref={intent.viewHeading} tabIndex={-1}>Relationship-derived charts</h1><p>{savedResult ? 'Original saved chart, with both source versions preserved. No values were recalculated.' : 'Choose a symbolic midpoint composite or the explicitly uncorrected time-and-coordinate Davison. Neither measures compatibility.'}</p></div>
      <button type="button" onClick={onClose}>{savedResult ? 'Back to chart library' : 'Back to chart choices'}</button></div>
    {!savedResult && <form className="advanced-form" onSubmit={event => void calculate(event)}>
      <label>First person<select required value={first} onChange={event => { change(); setFirst(event.target.value); }}>
        <option value="">Choose a person</option>{people.filter(person => person.active_chart_id).map(person =>
          <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>Second person<select required value={second} onChange={event => { change(); setSecond(event.target.value); }}>
        <option value="">Choose another person</option>{people.filter(person => person.active_chart_id && person.id !== first).map(person =>
          <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
      <label>Technique<select value={technique} onChange={event => { change(); setTechnique(event.target.value as Technique); }}>
        <option value="midpoint_composite">Shortest-circle midpoint composite</option>
        <option value="uncorrected_davison">Uncorrected Davison · arithmetic coordinates</option>
      </select></label>
      <button className="primary" type="submit" disabled={busy || !first || !second || first === second}>
        {busy ? 'Calculating…' : 'Calculate derived chart'}</button>
    </form>}
    {error && <p role="alert" className="error">{error}</p>}
    {result?.status === 'supported' && <div className="advanced-event" role="region" aria-label="Derived chart result">
      {result.source_status === 'historical' && <p role="status" className="error">Historical source version: this archived chart was not recalculated.</p>}
      <h2 ref={intent.resultHeading} tabIndex={-1}>{result.technique === 'midpoint_composite' ? 'Midpoint composite' : 'Uncorrected Davison'} · {name(result.person_a_id)} and {name(result.person_b_id)}</h2>
      {result.technique === 'midpoint_composite' ? <>
        <p>Each planet is the shortest circular midpoint of the two saved natal longitudes. This has no physical instant, houses, angles or motion.</p>
        {result.position_status !== 'supported' && <p role="status">An exactly opposite source pair has no unique circular midpoint. Those bodies were omitted from the wheel and aspects, not guessed.</p>}
        <CompositeWheel result={result} />
        <details className="chart-supporting-data"><summary>Composite planetary positions and aspects · {result.aspects_total} aspects</summary>
        <div className="transit-tables"><table><caption>Composite planets · both natal sources and midpoint</caption>
          <thead><tr><th scope="col">Planet</th><th scope="col">First natal</th><th scope="col">Second natal</th><th scope="col">Symbolic midpoint</th></tr></thead>
          <tbody>{result.positions.map(item => <tr key={item.id}><th scope="row">{bodyLabel(item.id)}</th>
            <td>{zodiac(item.source_a_degrees)}</td><td>{zodiac(item.source_b_degrees)}</td>
            <td>{item.longitude_degrees === null ? 'Ambiguous · exactly opposite' : zodiac(item.longitude_degrees)}</td></tr>)}</tbody></table></div>
        <div className="transit-tables"><table><caption>Composite planetary aspects · {result.aspects_total} total, {result.aspects.length} shown</caption>
          <thead><tr><th scope="col">First</th><th scope="col">Aspect</th><th scope="col">Second</th><th scope="col">Orb</th></tr></thead>
          <tbody>{result.aspects.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.first)}</th>
            <td>{item.kind}</td><td>{bodyLabel(item.second)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
          {result.aspects_truncated && <p>Closest 24 shown; more were calculated.</p>}</div>
        </details>
      </> : <>
        <p>Derived UTC instant {result.derived_instant_utc}. Algebraic coordinate means: {result.derived_latitude.toFixed(4)}° latitude, {result.derived_longitude.toFixed(4)}° longitude. Signed longitude is averaged literally; near the date line it can produce Greenwich, not a spherical midpoint. This is not a new person's natal.</p>
        <ReturnWheel natal={result.derived_natal} resultId={result.id || 'derived'}
          personId={result.person_a_id} birthId="derived-uncorrected-not-a-person-birth"
          label="Uncorrected Davison" methodVersion={result.method_version}
          sourceBirth={{ zone: 'UTC', latitude: result.derived_latitude, longitude: result.derived_longitude,
            provenance: 'derived-arithmetic-not-a-person-birth' }}
          sourceSettings={result.derived_settings} engineVersion={result.engine_version}
          profileId={result.profile_a_id} profileRevision={result.profile_a_revision}
          sourceStatus={result.source_status || 'current'} additionalProvenance={{
            technique: result.technique, method_version: result.method_version,
            chart_a_id: result.chart_a_id, chart_b_id: result.chart_b_id,
            source_a_birth_id: result.source_a_birth_id, source_b_birth_id: result.source_b_birth_id,
            source_a_birth: result.source_a_birth, source_b_birth: result.source_b_birth,
            profile_b_id: result.profile_b_id, profile_b_revision: result.profile_b_revision,
            ephemeris_a_sha256: result.ephemeris_a_sha256,
            ephemeris_b_sha256: result.ephemeris_b_sha256,
            geography_policy: result.geography_policy, derived_instant_utc: result.derived_instant_utc,
          }} />
      </>}
      <details className="chart-supporting-data"><summary>Chiron in this chart</summary><p>{result.chiron_policy}</p></details>
      <p className="transit-scroll-hint">Swipe wide tables and wheel sideways on small screens. Saved results keep both source versions; corrections do not rewrite past outputs.</p>
    </div>}
    {!savedResult && history.length > 0 && <nav className="advanced-history" aria-label="Saved relationship charts"><h2>Saved derived charts</h2>
      {history.map(row => <button key={row.id} type="button" onClick={() => void openSaved(row.id)}>
        Open saved derived chart · {row.created_at.slice(0, 10)}</button>)}</nav>}
  </section>;
}
