import { useRef, type Ref } from 'react';
import { bodyGlyph, bodyLabel, ChartNotation, chartNotation } from './chart-symbols';
import { WheelExportActions } from './chart-export';
import { point, signs, zodiac, type Point } from './natal';

type Position = Point & { speed_degrees_per_day: number; retrograde: boolean };
type SkyAspect = { first: string; second: string; kind: string; orb_degrees: number };
type PairAspect = { a_body_id: string; b_body_id: string; aspect: string; orb_degrees: number };
export type TransitResultData = {
  status: string; mode: 'sky' | 'natal_transits'; chart_id: string | null;
  instant_utc: string; reporting: { date: string; time: string; zone: string; offset: string; occurrence: string };
  positions?: Position[]; natal_positions?: Point[]; natal_house_status?: string;
  same_sky_aspects?: SkyAspect[]; same_sky_total?: number;
  transit_to_natal_aspects?: PairAspect[]; transit_to_natal_total?: number;
  aspect_limit?: number; orb_policy?: Record<string, number>;
  profile_id?: string; profile_revision?: number; source_status?: string;
  engine_version?: string; ephemeris_sha256?: Record<string, string>; method?: string;
};

function SkyWheel({ result }: { result: TransitResultData }) {
  const svg = useRef<SVGSVGElement>(null);
  const combined = result.mode === 'natal_transits';
  const positions = result.positions || [];
  const natal = result.natal_positions || [];
  const label = (body: Point, radius: number, color: string, ring: string, track: number) => {
    const location = point(body.longitude_degrees, 0, radius + track);
    return <g key={`${ring}-${body.id}`}><circle cx={location.x} cy={location.y} r="11" fill="var(--wheel-paper, #fffef9)" stroke={color} strokeWidth="1.5" />
      <text x={location.x} y={location.y} dominantBaseline="middle" textAnchor="middle" fill={color} fontSize="16" fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'}>{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>;
  };
  function tracks(bodies: Point[]) {
    const sorted = [...bodies].sort((a, b) => a.longitude_degrees - b.longitude_degrees);
    const result = new Map<string, number>();
    let previous = sorted.length ? sorted[sorted.length - 1].longitude_degrees - 360 : 0;
    let cluster = 0;
    for (const body of sorted) {
      cluster = body.longitude_degrees - previous < 12 ? cluster + 1 : 0;
      result.set(body.id, (cluster % 3) * 19);
      previous = body.longitude_degrees;
    }
    return result;
  }
  const skyTracks = tracks(positions), natalTracks = tracks(natal);
  return <div className="natal-wheel-frame"><div className="natal-wheel-scroll"><svg ref={svg} className="natal-wheel"
    viewBox="0 0 480 480" role="img" aria-labelledby="transit-wheel-title transit-wheel-desc">
    <title id="transit-wheel-title">{combined ? 'Natal and transiting' : 'Sky-only'} tropical positions on {result.reporting.date} at {result.reporting.time} {result.reporting.zone}</title>
    <desc id="transit-wheel-desc">Outer marks are transiting planets; inner marks are natal positions when available. Wheel labels: {chartNotation}. Sign labels use their first three letters. No sky houses or aspect formations are drawn; the tables give exact degrees and bounded aspect names/orbs.</desc>
    <rect x="1" y="1" width="478" height="478" rx="18" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-frame, #d8dfce)" />
    {[190, 156, 106, 71].map(radius => <circle key={radius} cx="240" cy="240" r={radius} fill="none" stroke="var(--wheel-ring, #b9c9b8)" strokeWidth="1" />)}
    {signs.map((name, index) => {
      const position = point(index * 30 + 15, 0, 206);
      return <text key={name} x={position.x} y={position.y} textAnchor="middle" dominantBaseline="middle" fontSize="11" fill="var(--wheel-ink, #425e49)">{name.slice(0, 3)}</text>;
    })}
    {positions.map(body => label(body, 137, 'var(--wheel-sky, #245b4e)', 'sky', skyTracks.get(body.id) || 0))}
    {combined && natal.map(body => label(body, 79, 'var(--wheel-natal, #a16134)', 'natal', natalTracks.get(body.id) || 0))}
    <text x="240" y="226" textAnchor="middle" fill="var(--wheel-ink, #21483b)" fontSize="14" fontFamily="Georgia, serif">{combined ? 'Natal + transits' : 'Sky at this instant'}</text>
  </svg></div><p className="wheel-scroll-hint">Scroll sideways for the wheel. Open Symbols for the glyph key; tables give full names and degrees.</p>
    <ChartNotation ids={[...positions, ...natal].map(body => body.id)} rings={combined ? 'Outer green labels mark transiting positions; inner amber labels mark the saved natal.' :
      'The outer green labels mark transiting positions only; no birth time or house is assumed.'} />
    <WheelExportActions svgRef={svg} stem={`kat-${combined ? `transits-${result.chart_id}` : 'sky'}-${result.reporting.date}`}
      provenance={{ chart_id: result.chart_id, mode: result.mode, instant_utc: result.instant_utc,
        reporting: result.reporting, profile_id: result.profile_id,
        profile_revision: result.profile_revision, source_status: result.source_status,
        engine_version: result.engine_version, method: result.method,
        ephemeris_sha256: result.ephemeris_sha256, orb_policy: result.orb_policy }} />
  </div>;
}

export function TransitResult({ result, subject, headingRef }: {
  result: TransitResultData; subject?: string; headingRef?: Ref<HTMLHeadingElement>;
}) {
  if (result.status !== 'supported') {
    const reason = result.status === 'unsupported_stale_birth_source'
      ? 'The selected chart has a superseded birth source. Update the chart before comparing transits.'
      : result.status === 'unsupported_uncertain_birth_time_or_non_natal_chart'
        ? 'This chart has no supported exact-time natal positions. Correct the birth details or use Sky only.'
        : 'This calculated view is unavailable for the selected date and chart.';
    return <p className="natal-qualification">{reason} No unsupported positions are shown.</p>;
  }
  return <div className="transit-result"><h2 ref={headingRef} tabIndex={headingRef ? -1 : undefined}>{subject ? `${subject} · ${result.mode === 'sky' ? 'sky' : 'natal + transits'}` : result.mode === 'sky' ? 'Sky only' : 'Natal + transits'}</h2>
    <p><strong>{result.reporting.date} {result.reporting.time} · {result.reporting.zone}</strong>
      {result.reporting.occurrence !== 'unspecified' && ` · ${result.reporting.occurrence} repeated hour (UTC${result.reporting.offset.slice(0, 3)}:${result.reporting.offset.slice(3)})`}</p>
    {result.mode === 'natal_transits' && result.source_status !== 'current' &&
      <p className="natal-qualification">This view used an earlier natal chart. Later corrections do not change its saved positions.</p>}
    {result.mode === 'natal_transits' && result.natal_house_status !== 'supported' &&
      <p className="natal-qualification">Natal houses are unavailable for this chart; no house positions are inferred.</p>}
    <SkyWheel result={result} />
    <details className="transit-section"><summary>Transiting planets</summary><div className="transit-tables"><table><caption>Transiting planets · tropical longitude and actual motion</caption><thead><tr><th scope="col">Planet</th><th scope="col">Position</th><th scope="col">Longitude</th><th scope="col">Motion</th></tr></thead>
      <tbody>{result.positions?.map(body => <tr key={body.id}><th scope="row">{bodyLabel(body.id)}</th><td>{zodiac(body.longitude_degrees)}</td><td>{body.longitude_degrees.toFixed(4)}°</td><td>{body.retrograde ? 'Retrograde' : 'Direct'} ({body.speed_degrees_per_day.toFixed(4)}°/day)</td></tr>)}</tbody></table></div></details>
    {result.mode === 'natal_transits' && <details className="transit-section"><summary>Selected natal positions</summary><div className="transit-tables"><table><caption>Selected natal positions</caption><thead><tr><th scope="col">Natal point</th><th scope="col">Longitude</th></tr></thead>
      <tbody>{result.natal_positions?.map(body => <tr key={body.id}><th scope="row">{bodyLabel(body.id)}</th><td>{zodiac(body.longitude_degrees)} · {body.longitude_degrees.toFixed(4)}°</td></tr>)}</tbody></table></div></details>}
    <details className="transit-section"><summary>Same-sky aspects · {result.same_sky_total} found; showing {result.same_sky_aspects?.length} tightest (up to {result.aspect_limit})</summary><p className="transit-scroll-hint">Scroll the table sideways to see the orb.</p><div className="transit-tables"><h3 className="sr-only">Same-sky aspects · {result.same_sky_total} found; showing {result.same_sky_aspects?.length} tightest (up to {result.aspect_limit})</h3><table><caption className="sr-only">Same-sky aspects · transiting planets</caption><thead><tr><th scope="col">Transiting planet</th><th scope="col">Aspect</th><th scope="col">Transiting planet</th><th scope="col">Orb</th></tr></thead>
      <tbody>{result.same_sky_aspects?.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.first)}</th><td>{item.kind}</td><td>{bodyLabel(item.second)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>{!result.same_sky_total && <p>No same-sky aspects within the declared orbs.</p>}</div></details>
    {result.mode === 'natal_transits' && <details className="transit-section"><summary>Transit-to-natal aspects · {result.transit_to_natal_total} found; showing {result.transit_to_natal_aspects?.length} tightest (up to {result.aspect_limit})</summary><p className="transit-scroll-hint">Scroll the table sideways to see the orb.</p><div className="transit-tables"><h3 className="sr-only">Transit-to-natal aspects · {result.transit_to_natal_total} found; showing {result.transit_to_natal_aspects?.length} tightest (up to {result.aspect_limit})</h3><table><caption className="sr-only">Transit-to-natal aspects · transiting planet and natal point</caption><thead><tr><th scope="col">Transiting planet</th><th scope="col">Aspect</th><th scope="col">Natal point</th><th scope="col">Orb</th></tr></thead>
      <tbody>{result.transit_to_natal_aspects?.map((item, index) => <tr key={index}><th scope="row">{bodyLabel(item.a_body_id)}</th><td>{item.aspect}</td><td>{bodyLabel(item.b_body_id)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>{!result.transit_to_natal_total && <p>No transit-to-natal aspects within the declared orbs.</p>}</div></details>}
    {((result.same_sky_total || 0) > (result.same_sky_aspects?.length || 0) ||
      (result.mode === 'natal_transits' && (result.transit_to_natal_total || 0) > (result.transit_to_natal_aspects?.length || 0))) &&
      <p className="natal-qualification">Only the closest {result.aspect_limit} aspects in each category are shown; additional aspects were calculated but omitted.</p>}
  </div>;
}
