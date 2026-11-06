import type { ReactNode } from 'react';
import { point } from './chart-geometry';
import type { NatalResult } from './natal';
import { edgeId, type Entry } from './exploration-data';

export type WheelGeometry = { ascendant: number; tracks: Map<string, number>; locations: Map<string, number> };
export type WheelOverlay = (geometry: WheelGeometry) => ReactNode;
export const aspectColors: Record<string, string> = {
  conjunction: 'var(--wheel-aspect-gold, #a87931)',
  opposition: 'var(--wheel-aspect-warm, #ad684c)', square: 'var(--wheel-aspect-warm, #ad684c)',
  trine: 'var(--wheel-aspect-cool, #487b72)', sextile: 'var(--wheel-aspect-cool, #487b72)',
};

export function aspectPath(first: number, second: number, kind: string, ascendant: number) {
  const a = point(first, ascendant, 77), b = point(second, ascendant, 77);
  if (kind !== 'conjunction') return `M${a.x} ${a.y} L${b.x} ${b.y}`;
  // A small arc and endpoint rings keep even an exact conjunction visible.
  const delta = ((second - first + 540) % 360) - 180;
  return `M${a.x} ${a.y} A77 77 0 0 ${delta < 0 ? 1 : 0} ${b.x} ${b.y}`;
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
    {natal.aspects.filter(a => entry.edges.includes(edgeId(a))).map(a => {
      const first = locations.get(a.first), second = locations.get(a.second);
      if (first === undefined || second === undefined) return null;
      return <g key={edgeId(a)} data-highlight-edge={edgeId(a)}>
        <path d={aspectPath(first, second, a.kind, ascendant)} fill="none" stroke={aspectColors[a.kind]}
          strokeWidth="3" strokeDasharray={a.kind === 'opposition' ? '5 4' : undefined} />
        {a.kind === 'conjunction' && [first, second].map((degree, i) => {
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
