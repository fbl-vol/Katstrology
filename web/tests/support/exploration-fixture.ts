import { execFileSync } from 'node:child_process';
import type { Chart } from '../../src/features/charts/natal';
import type { Exploration, Pattern } from '../../src/features/charts/exploration-data';

// A synthetic saved record goes through the real read projection for v2 UI checks.
// No database, ephemeris, private record or provider is consulted by this process.
export function expandedPatternFixture(chart: Chart): Exploration {
  const degrees: Record<string, number> = { sun: 0, mercury: 5, venus: 12, jupiter: 30,
    moon: 60, mars: 210, saturn: 216, uranus: 240, neptune: 260, pluto: 280 };
  const natal = chart.result.natal!;
  natal.positions = natal.positions.map(p => {
    const degree = degrees[p.id] ?? p.longitude_degrees;
    const house = natal.houses.cusps.find((c, i) => (degree - c.longitude_degrees + 360) % 360 <
      (natal.houses.cusps[(i + 1) % 12].longitude_degrees - c.longitude_degrees + 360) % 360)?.number ?? null;
    return { ...p, longitude_degrees: degree, sign: Math.floor(degree / 30), house };
  });
  const result = JSON.parse(execFileSync('../.venv-swiss/bin/python', ['-c',
    'import json,sys; from m2.calculation.natal import _aspects; from m2.calculation.exploration import explore_chart; c=json.load(sys.stdin); c["result"]["natal"]["aspects"]=_aspects(c["result"]["natal"]["positions"],c["result"]["profile"]["settings"]); print(json.dumps({"chart":c,"projection":explore_chart(c)}))'],
  { input: JSON.stringify(chart), env: { ...process.env, PYTHONPATH: '..', PYTHONDONTWRITEBYTECODE: '1' }, encoding: 'utf8' }));
  natal.aspects = result.chart.result.natal.aspects;
  return result.projection;
}

// Presentation-only fixture: explicit graphs, not a second pattern detector.
// The API/detector tests independently verify real saved-graph derivation.
export function patternFixture(chart: Chart, multiple = false): Exploration {
  const degrees: Record<string, number> = { sun: 142, moon: 262, mercury: 143, venus: 164,
    mars: 73, jupiter: 22, saturn: 345.5, uranus: 302, neptune: 254, pluto: multiple ? 255 : 246,
    north_node: 70, south_node: 250 };
  const natal = chart.result.natal!;
  natal.positions = natal.positions.map(p => {
    const degree = degrees[p.id];
    const house = natal.houses.cusps.find((c, i) => (degree - c.longitude_degrees + 360) % 360 <
      (natal.houses.cusps[(i + 1) % 12].longitude_degrees - c.longitude_degrees + 360) % 360)?.number ?? null;
    return { ...p, longitude_degrees: degree, sign: Math.floor(degree / 30), house };
  });
  // Preserve real saved cusp and angle geometry, deliberately not equal houses.
  const triples: [string, string, string, number][] = [
    ['sun', 'moon', 'trine', 0], ['sun', 'jupiter', 'trine', 0], ['moon', 'jupiter', 'trine', 0],
    ['venus', 'mars', 'square', 1], ['venus', 'saturn', 'opposition', 1.5],
    ['venus', 'neptune', 'square', 1], ['mars', 'saturn', 'square', 2.5],
    ['mars', 'neptune', 'opposition', 1], ['saturn', 'neptune', 'square', 1.5],
    ['sun', 'mercury', 'conjunction', 1],
  ];
  const exact: Record<string, number> = { trine: 120, square: 90, opposition: 180, conjunction: 0 };
  natal.aspects = triples.map(([first, second, kind, orb_degrees]) => ({ first, second, kind, orb_degrees, exact_degrees: exact[kind] }));
  const edge = (first: string, second: string, kind: string) => [kind, ...[first, second].sort()].join(':');
  const cross: Pattern = { id: `${chart.id}|cross`, kind: 'grand_cross', members: ['venus', 'mars', 'saturn', 'neptune'],
    edges: triples.slice(3, 9).map(([a, b, k]) => edge(a, b, k)), apex: null, contained_by: [] };
  const trine: Pattern = { id: `${chart.id}|trine`, kind: 'grand_trine', members: ['sun', 'moon', 'jupiter'],
    edges: triples.slice(0, 3).map(([a, b, k]) => edge(a, b, k)), apex: null, contained_by: [] };
  const children: Pattern[] = [
    { id: `${chart.id}|t-mars`, kind: 't_square', members: ['venus', 'mars', 'saturn'], apex: 'mars',
      edges: [edge('venus', 'mars', 'square'), edge('venus', 'saturn', 'opposition'), edge('mars', 'saturn', 'square')], contained_by: [cross.id] },
    { id: `${chart.id}|t-venus`, kind: 't_square', members: ['venus', 'mars', 'neptune'], apex: 'venus',
      edges: [edge('venus', 'mars', 'square'), edge('venus', 'neptune', 'square'), edge('mars', 'neptune', 'opposition')], contained_by: [cross.id] },
    { id: `${chart.id}|t-neptune`, kind: 't_square', members: ['venus', 'saturn', 'neptune'], apex: 'neptune',
      edges: [edge('venus', 'saturn', 'opposition'), edge('venus', 'neptune', 'square'), edge('saturn', 'neptune', 'square')], contained_by: [cross.id] },
    { id: `${chart.id}|t-saturn`, kind: 't_square', members: ['mars', 'saturn', 'neptune'], apex: 'saturn',
      edges: [edge('mars', 'saturn', 'square'), edge('mars', 'neptune', 'opposition'), edge('saturn', 'neptune', 'square')], contained_by: [cross.id] },
  ];
  const patterns = [trine, cross, ...children];
  if (multiple) {
    // A second fourth corner shares the Venus/Mars/Saturn T-square.
    const extra: [string, string, string, number][] = [
      ['venus', 'pluto', 'square', 1], ['mars', 'pluto', 'opposition', 2], ['saturn', 'pluto', 'square', .5],
    ];
    natal.aspects.push(...extra.map(([first, second, kind, orb_degrees]) => ({ first, second, kind, orb_degrees, exact_degrees: exact[kind] })));
    const otherId = `${chart.id}|cross-pluto`;
    const replace = (id: string) => id.replace('neptune', 'pluto');
    patterns.push({ ...cross, id: otherId, members: cross.members.map(replace), edges: cross.edges.map(replace) });
    children[0].contained_by.push(otherId);
    patterns.push(...children.slice(1).map(p => ({ ...p, id: `${p.id}-pluto`, members: p.members.map(replace),
      edges: p.edges.map(replace), apex: replace(p.apex!), contained_by: [otherId] })));
  }
  return { chart_id: chart.id, rule_version: 'natal-patterns-v1', source_status: 'current', status: 'supported', reason: null, patterns };
}
