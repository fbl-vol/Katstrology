import type { MouseEvent } from 'react';
import { point } from './chart-geometry';
import type { NatalResult } from './natal';
import { aspectPath, type WheelGeometry } from './exploration-geometry';
import { edgeId, type Category, type Entry } from './exploration-data';

type Location = { x: number; y: number };
export type WheelChoice = { entries: Entry[]; location: Location; origin: SVGElement };

function inside(p: Location, vertices: Location[]) {
  let found = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const a = vertices[i], b = vertices[j];
    if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) found = !found;
  }
  return found;
}
function lineDistance(p: Location, a: Location, b: Location) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = dx || dy ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy))) : 0;
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}

export function ExplorationTargets({ natal, geometry, entries, choose, overlap }: {
  natal: NatalResult; geometry: WheelGeometry; entries: Record<Category, Entry[]>;
  choose: (entry: Entry) => void; overlap: (choice: WheelChoice) => void;
}) {
  const { ascendant, locations, tracks } = geometry;
  const bodies = entries.positions.map(entry => ({ entry,
    center: point(locations.get(entry.id)!, ascendant, tracks.get(entry.id)!) }));
  const houses = natal.houses.cusps.map((cusp, i) => {
    const next = natal.houses.cusps[(i + 1) % natal.houses.cusps.length];
    return { entry: entries.houses.find(e => e.house === cusp.number)!, center: point(cusp.longitude_degrees +
      ((next.longitude_degrees - cusp.longitude_degrees + 360) % 360) / 2, ascendant, 102) };
  });
  const aspects = natal.aspects.flatMap(a => {
    const first = locations.get(a.first), second = locations.get(a.second);
    if (first === undefined || second === undefined) return [];
    return [{ entry: entries.aspects.find(e => e.id === edgeId(a))!, kind: a.kind,
      a: point(first, ascendant, 77), b: point(second, ascendant, 77),
      path: aspectPath(first, second, a.kind, ascendant) }];
  });
  const patterns = entries.patterns.map(entry => ({ entry, vertices: entry.members
    .map(id => locations.get(id)!).sort((a, b) => a - b).map(degree => point(degree, ascendant, 77)) }));

  function press(event: MouseEvent<SVGGElement>, entry: Entry) {
    if (!event.detail) { choose(entry); return; }
    const svg = event.currentTarget.ownerSVGElement!;
    const matrix = svg.getScreenCTM();
    if (!matrix) return;
    const cursor = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    const scale = Math.hypot(matrix.a, matrix.b);
    const near = (p: Location, radius: number) => Math.hypot(cursor.x - p.x, cursor.y - p.y) <= radius;
    // The same precedence governs visible targets and ambiguous shared locations.
    let candidates = bodies.filter(b => near(b.center, 16 + 4 / scale)).map(b => b.entry);
    if (!candidates.length) candidates = houses.filter(h => near(h.center, 12 + 4 / scale)).map(h => h.entry);
    if (!candidates.length) candidates = aspects.filter(a => lineDistance(cursor, a.a, a.b) <= 4).map(a => a.entry);
    if (!candidates.length) candidates = patterns.filter(p => inside(cursor, p.vertices)).map(p => p.entry);
    if (candidates.length === 1) choose(candidates[0]);
    else if (candidates.length > 1) overlap({ entries: candidates, location: cursor, origin: event.currentTarget });
  }
  function control(entry: Entry) {
    return { role: 'button', tabIndex: 0, 'aria-label': `Explore ${entry.title}: ${entry.subtitle}`,
      'data-wheel-entry': entry.id, className: 'exploration-target',
      onClick: (event: MouseEvent<SVGGElement>) => press(event, entry),
      onKeyDown: (event: React.KeyboardEvent<SVGGElement>) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(entry); }
      } };
  }
  return <g className="exploration-targets">
    {patterns.map(p => <g key={p.entry.id} {...control(p.entry)}><polygon
      points={p.vertices.map(v => `${v.x},${v.y}`).join(' ')} fill="transparent" /></g>)}
    {aspects.map(a => <g key={a.entry.id} {...control(a.entry)}>
      {a.kind === 'conjunction' && <path d={a.path} fill="none" stroke="var(--wheel-aspect-gold, #a87931)" strokeWidth="1" />}
      <path d={a.path} fill="none" stroke="transparent" strokeWidth="8" strokeLinecap="round" />
      {a.kind === 'conjunction' && <circle cx={a.a.x} cy={a.a.y} r="5" fill="transparent" stroke="transparent" strokeWidth="8" vectorEffect="non-scaling-stroke" />}
    </g>)}
    {houses.map(h => <g key={h.entry.id} {...control(h.entry)}><circle cx={h.center.x} cy={h.center.y} r="12"
      fill="transparent" stroke="transparent" strokeWidth="8" vectorEffect="non-scaling-stroke" /></g>)}
    {bodies.map(b => <g key={b.entry.id} {...control(b.entry)}><circle cx={b.center.x} cy={b.center.y} r="16"
      fill="transparent" stroke="transparent" strokeWidth="8" vectorEffect="non-scaling-stroke" /></g>)}
  </g>;
}
