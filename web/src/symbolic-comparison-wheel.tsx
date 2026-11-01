import { useRef } from 'react';
import { bodyGlyph, ChartNotation } from './chart-symbols';
import { WheelExportActions } from './chart-export';
import { point, signs } from './natal';

export type SymbolicPosition = { id: string; longitude_degrees: number };

function ringPositions(positions: SymbolicPosition[], radius: number) {
  const sorted = [...positions].sort((a, b) => a.longitude_degrees - b.longitude_degrees);
  let previous = sorted[sorted.length - 1]?.longitude_degrees - 360 || -360;
  let cluster = 0;
  return sorted.map(body => {
    cluster = body.longitude_degrees - previous < 13 ? cluster + 1 : 0;
    previous = body.longitude_degrees;
    return { body, labelRadius: radius + ((cluster % 3) - 1) * 14 };
  });
}

export function SymbolicComparisonWheel({ positions, natalPositions, label, description, stem,
  provenance, frame = 'symbolic' }: {
  positions: SymbolicPosition[]; natalPositions: SymbolicPosition[];
  label: string; description: string; stem: string; provenance: Record<string, unknown>;
  frame?: 'symbolic' | 'actual';
}) {
  const ref = useRef<SVGSVGElement>(null);
  return <div className="natal-wheel-frame"><div className="natal-wheel-scroll"><svg ref={ref} className="natal-wheel"
    viewBox="0 0 480 480" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="symbolic-wheel-title symbolic-wheel-desc">
    <title id="symbolic-wheel-title">{label} compared with saved natal</title>
    <desc id="symbolic-wheel-desc">{description} Outer teal marks {frame === 'actual' ? 'actual Sun and Moon positions at the selected UTC instant' : 'symbolic directed positions'}. Inner amber marks saved natal positions. {frame === 'actual' ? 'This is a real-sky snapshot without a local visibility calculation.' : 'These are not a simultaneous sky.'} Tables give longitudes and aspects.</desc>
    <rect width="480" height="480" rx="20" fill="var(--wheel-paper, #fffef9)" />
    {[100, 135, 175, 188].map(radius => <circle key={radius} cx="240" cy="240" r={radius} fill="none" stroke="var(--wheel-ring, #c4d2c7)" />)}
    {signs.map((sign, index) => { const p = point(index * 30 + 15, 0, 205);
      return <text key={sign} x={p.x} y={p.y} textAnchor="middle" fontSize="10" fill="var(--wheel-ink, #3b5f51)">{sign.slice(0, 3)}</text>; })}
    {([['directed', positions, 170, 'var(--wheel-sky, #2c716b)'],
       ['natal', natalPositions, 108, 'var(--wheel-natal, #a46c3e)']] as const).map(([ring, bodies, radius, stroke]) =>
      ringPositions(bodies, radius).map(({ body, labelRadius }) => {
        const p = point(body.longitude_degrees, 0, labelRadius);
        const tick = point(body.longitude_degrees, 0, radius);
        return <g key={`${ring}-${body.id}`}><line x1={tick.x} y1={tick.y} x2={p.x} y2={p.y} stroke={stroke} />
          <circle cx={p.x} cy={p.y} r="10" fill="var(--wheel-paper, #fffef9)" stroke={stroke} />
          <text x={p.x} y={p.y} dominantBaseline="middle" textAnchor="middle" fontSize="15" fontFamily={body.id === 'sun' ? 'KatAstroSun' : 'KatAstro'} fill="var(--wheel-glyph, #243f3c)">{bodyGlyph(body.id) || body.id.slice(0, 2)}</text></g>; }))}
    <text x="240" y="237" textAnchor="middle" fontSize="12" fill="var(--wheel-ink, #2b503b)">{label} · natal</text>
  </svg></div>
    <ChartNotation ids={positions.map(body => body.id)} rings={`Outer teal shows ${label}; inner amber shows saved natal. No ${frame === 'actual' ? 'local visibility or house placements' : 'directed houses'} are claimed.`} />
    <WheelExportActions svgRef={ref} stem={stem} provenance={provenance} />
  </div>;
}
