import type { ReactNode } from 'react';
import { point } from './chart-geometry';
import type { NatalResult } from './natal';
import type { Entry } from './exploration-data';

export type WheelGeometry = { ascendant: number; tracks: Map<string, number>; locations: Map<string, number> };
export type WheelOverlay = (geometry: WheelGeometry) => ReactNode;
export const aspectColors: Record<string, string> = {
  conjunction: 'var(--wheel-aspect-gold, #a87931)',
  opposition: 'var(--wheel-aspect-warm, #ad684c)', square: 'var(--wheel-aspect-warm, #ad684c)',
  trine: 'var(--wheel-aspect-cool, #487b72)', sextile: 'var(--wheel-aspect-cool, #487b72)',
  quincunx: 'var(--wheel-aspect-gold, #a87931)', sesquiquadrate: 'var(--wheel-aspect-warm, #ad684c)',
  quintile: 'var(--wheel-aspect-cool, #487b72)', biquintile: 'var(--wheel-aspect-cool, #487b72)',
};

export function aspectPath(first: number, second: number, kind: string, ascendant: number) {
  const a = point(first, ascendant, 77), b = point(second, ascendant, 77);
  if (kind !== 'conjunction') return `M${a.x} ${a.y} L${b.x} ${b.y}`;
  // A small arc and endpoint rings keep even an exact conjunction visible.
  const delta = ((second - first + 540) % 360) - 180;
  return `M${a.x} ${a.y} A77 77 0 0 ${delta < 0 ? 1 : 0} ${b.x} ${b.y}`;
}

// Non-polygon targets follow the circular distribution, never invented aspects.
export function patternRing(entry: Entry, geometry: WheelGeometry) {
  if (entry.pattern?.geometry === 'distribution')
    return 'M328 240 A88 88 0 1 0 152 240 A88 88 0 1 0 328 240';
  const degrees = entry.members.flatMap(id => {
    const degree = geometry.locations.get(id);
    return degree === undefined ? [] : [degree];
  }).sort((a, b) => a - b);
  if (!degrees.length) return '';
  const gaps = degrees.map((degree, i) => (i + 1 < degrees.length ? degrees[i + 1] : degrees[0] + 360) - degree);
  const endIndex = gaps.indexOf(Math.max(...gaps));
  const start = degrees[(endIndex + 1) % degrees.length];
  // A tiny arc is still reachable for an exactly coincident concentration.
  const span = Math.max(2, 360 - gaps[endIndex]);
  const a = point(start, geometry.ascendant, 88), b = point(start + span, geometry.ascendant, 88);
  return `M${a.x} ${a.y} A88 88 0 ${span > 180 ? 1 : 0} 0 ${b.x} ${b.y}`;
}

export function Highlight({ natal, geometry, entry }: { natal: NatalResult; geometry: WheelGeometry; entry: Entry | null }) {
  if (!entry) return null;
  const { ascendant, tracks, locations } = geometry;
  const cuspIndex = natal.houses.cusps.findIndex(c => c.number === entry.house);
  const cusp = natal.houses.cusps[cuspIndex];
  const next = natal.houses.cusps[(cuspIndex + 1) % natal.houses.cusps.length];
  const a = cusp && point(cusp.longitude_degrees, ascendant, 186);
  const b = next && point(next.longitude_degrees, ascendant, 186);
  const span = cusp && next && (next.longitude_degrees - cusp.longitude_degrees + 360) % 360;
  return <g className="exploration-highlight" pointerEvents="none" aria-hidden="true" data-selected-entry={entry.id}>
    {a && b && <path d={`M240 240 L${a.x} ${a.y} A186 186 0 ${span > 180 ? 1 : 0} 0 ${b.x} ${b.y} Z`}
      fill="var(--wheel-aspect-cool, #487b72)" fillOpacity=".12" stroke="var(--wheel-angle, #304f3b)" />}
    {entry.pattern?.geometry && entry.pattern.geometry !== 'aspects' && <g data-highlight-distribution={entry.pattern.geometry}>
      <path d={patternRing(entry, geometry)} fill="none" stroke="var(--wheel-angle, #304f3b)"
        strokeWidth="2" strokeDasharray={entry.pattern.geometry === 'distribution' ? '2 4' : undefined} />
      {entry.pattern.geometry === 'distribution' && (entry.pattern.facts?.groups ?? []).map((members, i) =>
        <path key={i} d={patternRing({ ...entry, members, pattern: { ...entry.pattern!, geometry: 'members' } }, geometry)}
          fill="none" stroke="var(--wheel-angle, #304f3b)" strokeWidth="4" strokeLinecap="round" />)}
    </g>}
    {entry.edges.map(id => {
      const [kind, firstId, secondId] = id.split(':');
      const first = locations.get(firstId), second = locations.get(secondId);
      if (first === undefined || second === undefined) return null;
      const minor = ['quincunx', 'sesquiquadrate', 'quintile', 'biquintile'].includes(kind);
      return <g key={id} data-highlight-edge={id}>
        <path d={aspectPath(first, second, kind, ascendant)} fill="none" stroke={aspectColors[kind]}
          strokeWidth="3" strokeDasharray={minor ? '2 4' : kind === 'opposition' ? '5 4' : undefined} />
        {kind === 'conjunction' && [first, second].map((degree, i) => {
          const p = point(degree, ascendant, 77);
          return <circle key={i} cx={p.x} cy={p.y} r="4" fill="none" stroke={aspectColors.conjunction} strokeWidth="2" />;
        })}
      </g>;
    })}
    {entry.members.map(id => {
      const degree = locations.get(id);
      if (degree === undefined) return null;
      const p = point(degree, ascendant, tracks.get(id) ?? 77);
      return <circle key={id} data-highlight-body={id} cx={p.x} cy={p.y} r={tracks.has(id) ? 15 : 6}
        fill="none" stroke="var(--wheel-angle, #304f3b)" strokeWidth="2.5" />;
    })}
  </g>;
}
