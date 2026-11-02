import { useRef } from 'react';
import { bodyGlyph, bodyLabel, ChartNotation, chartNotation } from './chart-symbols';
import './chart-wheel.css';
import { WheelExportActions } from './chart-export';

export type Point = { id: string; longitude_degrees: number; sign: number };
export type Placement = Point & { latitude_degrees: number; speed_degrees_per_day: number;
  retrograde: boolean; house: number | null };
export type NatalResult = { status: string; instant_utc?: string; positions: Placement[];
  houses: { status: string; system: string; cusps: { number: number; longitude_degrees: number }[];
            angles: Point[] }; aspects: { first: string; second: string; kind: string;
            orb_degrees: number; exact_degrees: number }[];
  method_version: string; ephemeris_sha256?: Record<string, string>; reason?: string;
  lilith_convention?: 'mean' | 'osculating'; lilith_method?: string };
export type Chart = { id: string; person_id: string; birth_id: string; profile_id: string; profile_revision: number;
  source_status: string; result: { natal_sun: { status: string; sun_longitude_degrees?: number };
    birth: { zone: string; latitude: number | null; longitude: number | null; provenance: string };
    natal?: NatalResult; houses: string; engine: { method: string; version: string };
    profile: { settings: { house_system: string; node_type: string; orbs?: Record<string, number>; include_chiron?: boolean; include_lilith?: 'mean' | 'osculating' } }; } };

export const signs = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces'];
const aspectColors: Record<string, string> = { conjunction: 'var(--wheel-aspect-gold, #a87931)',
  opposition: 'var(--wheel-aspect-warm, #ad684c)', square: 'var(--wheel-aspect-warm, #ad684c)',
  trine: 'var(--wheel-aspect-cool, #487b72)', sextile: 'var(--wheel-aspect-cool, #487b72)' };

export function zodiac(degrees: number) {
  const within = degrees % 30;
  return `${Math.floor(within)}°${String(Math.floor((within % 1) * 60)).padStart(2, '0')}′ ${signs[Math.floor(degrees / 30)]}`;
}

export function point(degrees: number, ascendant: number, radius: number) {
  const radians = Math.PI + (ascendant - degrees) * Math.PI / 180;
  return { x: 240 + radius * Math.cos(radians), y: 240 + radius * Math.sin(radians) };
}

function Wheel({ chart, natal, compact = false, label = 'Natal', additionalProvenance = {} }: {
  chart: Chart; natal: NatalResult; compact?: boolean; label?: string;
  additionalProvenance?: Record<string, unknown>;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const ascendant = natal.houses.angles[0].longitude_degrees;
  const bodies = [...natal.positions].sort((a, b) => a.longitude_degrees - b.longitude_degrees);
  const tracks = new Map<string, number>();
  let previous = bodies[bodies.length - 1].longitude_degrees - 360;
  let cluster = 0;
  for (const body of bodies) {
    cluster = body.longitude_degrees - previous < 11 ? cluster + 1 : 0;
    tracks.set(body.id, 137 + (cluster % 3) * 17);
    previous = body.longitude_degrees;
  }
  const locations = new Map([...natal.positions, ...natal.houses.angles]
    .map(item => [item.id, item.longitude_degrees] as const));

  return <div className={`natal-wheel-frame${compact ? ' compact-natal-wheel' : ''}`}>
    <div className="natal-wheel-scroll"><svg ref={svg} className="natal-wheel" xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 480 480" role="img" aria-labelledby={`wheel-title-${chart.id} wheel-desc-${chart.id}`}>
      <title id={`wheel-title-${chart.id}`}>Tropical {label.toLowerCase()} wheel{compact ? ' for the next message' : ''}</title>
      <desc id={`wheel-desc-${chart.id}`}>Calculated {natal.houses.system} cusps, planets, nodes, ascendant, midheaven and displayed aspects. {natal.positions.some(body => body.id === 'chiron') ? 'Opted-in Chiron included. ' : ''}{natal.lilith_method ? `${natal.lilith_method}. ` : ''}Wheel labels: {chartNotation}. Sign labels use their first three letters. Numbered rays are house cusps. The following tables list degrees, cusps and aspect names/orbs.</desc>
      <rect x="1" y="1" width="478" height="478" rx="18" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-frame, #d8dfce)" />
      {[188, 120, 82].map(radius => <circle key={radius} cx="240" cy="240" r={radius} fill="none" stroke="var(--wheel-ring, #aabda9)" strokeWidth="1" />)}
      {Array.from({ length: 12 }, (_, i) => {
        const start = point(i * 30, ascendant, 188);
        const end = point(i * 30, ascendant, 166);
        const label = point(i * 30 + 15, ascendant, 205);
        return <g key={i}><line x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke="var(--wheel-ring, #b4c3b2)" />
          <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fill="var(--wheel-ink, #3a5946)" fontSize="11">{signs[i].slice(0, 3)}</text></g>;
      })}
      {natal.houses.cusps.map((cusp, index) => {
        const start = point(cusp.longitude_degrees, ascendant, 85);
        const end = point(cusp.longitude_degrees, ascendant, 186);
        const next = natal.houses.cusps[(index + 1) % 12];
        const middle = point(cusp.longitude_degrees + ((next.longitude_degrees - cusp.longitude_degrees + 360) % 360) / 2, ascendant, 102);
        return <g key={cusp.number}><line className={index === 0 || index === 9 ? 'wheel-angle' : 'wheel-cusp'} x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke={index === 0 || index === 9 ? 'var(--wheel-angle, #304f3b)' : 'var(--wheel-cusp, #c7d1c1)'} strokeWidth={index === 0 || index === 9 ? 2 : 0.75} opacity={index === 0 || index === 9 ? 1 : 0.8} />
          <text x={middle.x} y={middle.y} textAnchor="middle" dominantBaseline="middle" fontSize="11" fill="var(--wheel-ink, #425e49)">{cusp.number}</text></g>;
      })}
      {natal.aspects.filter(item => item.kind !== 'conjunction').map((item, index) => {
        const first = locations.get(item.first);
        const second = locations.get(item.second);
        if (first === undefined || second === undefined) return null;
        const a = point(first, ascendant, 77), b = point(second, ascendant, 77);
        return <line key={`${item.first}-${item.second}-${index}`} className="wheel-aspect" x1={a.x} y1={a.y} x2={b.x} y2={b.y}
          stroke={aspectColors[item.kind]} opacity=".45" strokeWidth=".75" />;
      })}
      {natal.positions.map(body => {
        const start = point(body.longitude_degrees, ascendant, 121);
        const label = point(body.longitude_degrees, ascendant, tracks.get(body.id) || 137);
        return <g key={body.id}><line x1={start.x} y1={start.y} x2={label.x} y2={label.y} stroke="var(--wheel-leader, #506a51)" strokeWidth=".85" />
          <circle cx={label.x} cy={label.y} r="12" fill="var(--wheel-paper, #fffef9)" stroke="var(--wheel-angle, #728b70)" />
          <text x={label.x} y={label.y} textAnchor="middle" dominantBaseline="middle" fontSize="17" fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'} fill="var(--wheel-glyph, #224432)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>;
      })}
      <text x="240" y="228" textAnchor="middle" fill="var(--wheel-ink, #2b503b)" fontSize="14" fontFamily="Georgia, serif">{label} · tropical</text>

    </svg></div>
    {!compact && <><p className="wheel-scroll-hint">Scroll sideways for the full wheel. Open Symbols for the glyph key; tables give full names and degrees.</p>
    <ChartNotation ids={natal.positions.map(body => body.id)} rings="The outer labels mark this chart’s positions; rays show house cusps when available." />
    <WheelExportActions svgRef={svg} stem={`kat-${chart.id}`}
      provenance={{ chart_id: chart.id, person_id: chart.person_id, birth_id: chart.birth_id,
        birth: chart.result.birth, profile_id: chart.profile_id, profile_revision: chart.profile_revision,
        source_status: chart.source_status, instant_utc: natal.instant_utc,
        method_version: natal.method_version, engine: chart.result.engine,
        included_bodies: natal.positions.map(body => body.id), source_settings: chart.result.profile.settings,
        ephemeris_sha256: natal.ephemeris_sha256, ...additionalProvenance }} /></>}
  </div>;
}

export function ReturnWheel({ natal, resultId, personId, birthId, label, methodVersion,
  sourceBirth, sourceSettings, engineVersion, profileId, profileRevision, sourceStatus,
  additionalProvenance }: {
  natal: NatalResult; resultId: string; personId: string; birthId: string; label: string;
  methodVersion: string; sourceBirth: Chart['result']['birth'];
  sourceSettings: Chart['result']['profile']['settings']; engineVersion: string;
  profileId: string; profileRevision: number; sourceStatus: string;
  additionalProvenance?: Record<string, unknown>;
}) {
  const chart: Chart = { id: resultId, person_id: personId, birth_id: birthId,
    profile_id: profileId, profile_revision: profileRevision, source_status: sourceStatus,
    result: { natal_sun: { status: 'exact_supplied_time' }, birth: sourceBirth,
      houses: natal.houses.status, profile: { settings: sourceSettings }, engine: { method: methodVersion, version: engineVersion } } };
  const positions = <div className="natal-tables"><table><caption>{label} positions · tropical longitude</caption>
    <thead><tr><th scope="col">Body</th><th scope="col">Sign and degree</th><th scope="col">Longitude</th></tr></thead>
    <tbody>{natal.positions.map(item => <tr key={item.id}><th scope="row">{bodyLabel(item.id)}</th>
      <td>{zodiac(item.longitude_degrees)}</td><td>{item.longitude_degrees.toFixed(4)}°</td></tr>)}</tbody></table></div>;
  return <div className="natal-detail">
    {natal.houses.status === 'supported' ? <><Wheel chart={chart} natal={natal} label={label}
      additionalProvenance={additionalProvenance} />
      <details className="chart-supporting-data"><summary>Planetary positions · {natal.positions.length} rows</summary>
        {positions}</details></> : <>
      <p role="status">Houses and angles are unavailable here. Planetary positions remain below; no substitute house system was used.</p>
      {positions}</>}
  </div>;
}

export function CompactNatalWheel({ chart }: { chart: Chart }) {
  const natal = chart.result.natal;
  return chart.source_status === 'current' && natal?.status === 'complete' && natal.houses.status === 'supported' &&
    natal.houses.angles.length > 0 ? <Wheel chart={chart} natal={natal} compact /> : null;
}

export function NatalChart({ chart }: { chart: Chart }) {
  const natal = chart.result.natal;
  if (!natal) return null;
  const settings = chart.result.profile.settings;
  const birth = chart.result.birth;
  return <div className="natal-detail">
    <p>{natal.status === 'complete' ? 'Calculated natal chart' : 'Limited natal chart'} · {settings.house_system} houses · {settings.node_type} north node{natal.lilith_method ? ` · ${natal.lilith_method}` : ''}.</p>
    {(birth.provenance.startsWith('provisional:') || birth.provenance.includes('geonames_city_centre')) &&
      <p className="natal-qualification">{birth.provenance.startsWith('provisional:') &&
        'Birth details are provisional; treat these positions as tentative.'}
        {birth.provenance.includes('geonames_city_centre') && ' Birthplace coordinates use a city-centre reference, not an exact birth location.'}</p>}
    {chart.source_status !== 'current' ? <p className="error">Historical source: do not use these calculated degrees as current chart evidence.</p> :
      natal.status === 'unsupported_uncertain_birth_time' ?
        <p role="status">Unknown or uncertain birth time: no full natal positions, houses, angles or aspects were calculated. Use a validated exact birth record for a full chart. The earlier Sun-only interval remains separate.</p> : <>
        {natal.houses.status === 'supported' ? <Wheel chart={chart} natal={natal} /> :
          <p role="status">Houses and angles unavailable ({natal.houses.status.replaceAll('_', ' ')}). No substitute system or ascendant was invented; planetary placements and aspects below remain available.</p>}
        <div className="natal-tables"><table><caption>Planet and lunar node positions{natal.lilith_method ? ' + selected Black Moon Lilith' : ''} · tropical longitude</caption>
          <thead><tr><th scope="col">Body</th><th scope="col">Sign and degree</th><th scope="col">Longitude</th><th scope="col">House</th><th scope="col">Motion</th></tr></thead>
          <tbody>{natal.positions.map(item => <tr key={item.id}><th scope="row">{bodyLabel(item.id)}</th>
            <td>{zodiac(item.longitude_degrees)}</td><td>{item.longitude_degrees.toFixed(4)}°</td><td>{item.house ?? '—'}</td>
            <td>{item.retrograde ? 'Retrograde' : 'Direct'}</td></tr>)}</tbody></table></div>
        {natal.houses.status === 'supported' && <div className="natal-tables"><table><caption>Angles and {settings.house_system} house cusps</caption>
          <thead><tr><th scope="col">Point</th><th scope="col">Sign and degree</th><th scope="col">Longitude</th></tr></thead>
          <tbody>{natal.houses.angles.map(item => <tr key={item.id}><th scope="row">{bodyLabel(item.id)}</th><td>{zodiac(item.longitude_degrees)}</td><td>{item.longitude_degrees.toFixed(4)}°</td></tr>)}
            {natal.houses.cusps.map(item => <tr key={item.number}><th scope="row">House {item.number}</th><td>{zodiac(item.longitude_degrees)}</td><td>{item.longitude_degrees.toFixed(4)}°</td></tr>)}</tbody></table></div>}
        <div className="natal-tables"><table><caption>Major aspects · orb policy: {Object.entries(settings.orbs || {}).map(([name, orb]) => `${name} ${orb}°`).join(', ')}</caption>
          <thead><tr><th scope="col">First</th><th scope="col">Aspect</th><th scope="col">Second</th><th scope="col">Orb</th></tr></thead>
          <tbody>{natal.aspects.map((item, index) => <tr key={`${item.first}-${item.second}-${index}`}><th scope="row">{bodyLabel(item.first)}</th>
            <td>{item.kind}</td><td>{bodyLabel(item.second)}</td><td>{item.orb_degrees.toFixed(3)}°</td></tr>)}</tbody></table>
          {!natal.aspects.length && <p>No aspects fall within this profile’s selected orbs.</p>}</div>
        <details className="chart-supporting-data"><summary>How this chart was calculated</summary>
          <p>House membership uses ecliptic-projected longitude. The south node is the north node’s antipode; it is not a second node calculation or an aspect participant. Aspects use ecliptic longitude, not applying/separating motion. {natal.lilith_method ? `${natal.lilith_method}. “True” does not mean more accurate; not asteroid 1181 or Waldemath. ` : ''}No interpretation, synastry, rectification or future prediction is calculated.</p>
        </details>
      </>}
  </div>;
}
