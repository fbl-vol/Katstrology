import { bodyLabel } from './chart-symbols';
import { zodiac } from './chart-geometry';
import type { Chart, NatalResult } from './natal';

export type Pattern = { id: string; kind: string; name?: string; definition?: string; aliases?: string[];
  members: string[]; edges: string[]; apex: string | null; contained_by: string[];
  geometry?: 'aspects' | 'members' | 'distribution'; house?: number | null;
  facts?: { sign?: number; house?: number; count?: number; occupied_arc_degrees?: number;
    handle?: string | null; groups?: string[][]; gaps?: { first: string; second: string; degrees: number }[] } };
export type PatternEvidence = { id: string; first: string; second: string; kind: string;
  exact_degrees: number; orb_degrees: number; limit_degrees: number; origin: 'saved' | 'derived' };
export type PatternRule = { kind: string; name: string; definition: string; aliases: string[];
  family: string; status: 'evaluated' | 'excluded' | 'unavailable'; reason: string | null; matches: number };
export type Exploration = { chart_id: string; rule_version: string; source_status: string;
  status: 'supported' | 'unavailable'; reason: string | null; patterns: Pattern[];
  evidence?: PatternEvidence[]; catalogue?: PatternRule[]; distribution?: { status: 'matched' | 'mixed' } | null };
export const categories = ['positions', 'houses', 'aspects', 'patterns'] as const;
export type Category = typeof categories[number];
export type Entry = { id: string; category: Category; title: string; subtitle: string;
  facts: [string, string][]; members: string[]; edges: string[]; house?: number; pattern?: Pattern };
export const patternNames: Record<string, string> = { grand_trine: 'Grand Trine', grand_cross: 'Grand Cross', t_square: 'T-square' };
export const edgeId = (a: NatalResult['aspects'][number]) => [a.kind, ...[a.first, a.second].sort()].join(':');
export const aspectTitle = (a: NatalResult['aspects'][number]) => `${bodyLabel(a.first)} ${a.kind} ${bodyLabel(a.second)}`;
const longitude = (degree: number) => `${zodiac(degree)} · ${degree.toFixed(4)}°`;

export function catalogue(chart: Chart, natal: NatalResult, patterns: Pattern[]): Record<Category, Entry[]> {
  const points = [...natal.positions, ...natal.houses.angles];
  const pointFacts = (ids: string[]): [string, string][] => ids.flatMap(id => {
    const p = points.find(p => p.id === id);
    return p ? [[bodyLabel(id), longitude(p.longitude_degrees)] as [string, string]] : [];
  });
  const positions: Entry[] = natal.positions.map(p => ({ id: p.id, category: 'positions',
    title: bodyLabel(p.id), subtitle: `${zodiac(p.longitude_degrees)} · ${p.retrograde ? 'Retrograde' : 'Direct'}`,
    facts: [...pointFacts([p.id]), ['House', p.house ? String(p.house) : 'Unavailable'],
      ['Motion', p.retrograde ? 'Retrograde' : 'Direct']], members: [p.id], edges: [] }));
  const houses: Entry[] = natal.houses.status !== 'supported' ? [] : [
    ...natal.houses.cusps.map(c => ({ id: `house-${c.number}`, category: 'houses' as const,
      title: `House ${c.number}`, subtitle: zodiac(c.longitude_degrees), house: c.number,
      facts: [['Cusp', longitude(c.longitude_degrees)], ['Included bodies', natal.positions
        .filter(p => p.house === c.number).map(p => bodyLabel(p.id)).join(', ') || 'None']] as [string, string][],
      members: natal.positions.filter(p => p.house === c.number).map(p => p.id), edges: [] })),
    ...natal.houses.angles.map(p => ({ id: p.id, category: 'houses' as const, title: bodyLabel(p.id),
      subtitle: zodiac(p.longitude_degrees), facts: pointFacts([p.id]), members: [p.id], edges: [] })),
  ];
  const aspects: Entry[] = natal.aspects.map(a => ({ id: edgeId(a), category: 'aspects',
    title: aspectTitle(a), subtitle: `${a.orb_degrees.toFixed(3)}° orb`, members: [a.first, a.second], edges: [edgeId(a)],
    facts: [...pointFacts([a.first, a.second]), ['Orb', `${a.orb_degrees.toFixed(3)}°`],
      ['Exact angle', `${a.exact_degrees}°`], ['Saved orb limit', `${chart.result.profile.settings.orbs?.[a.kind] ?? 'Unavailable'}°`]] }));
  return { positions, houses, aspects, patterns: patterns.map(p => ({ id: p.id, category: 'patterns',
    title: (p.name ?? patternNames[p.kind] ?? p.kind) + (p.apex ? ` · ${bodyLabel(p.apex)} apex` : ''),
    subtitle: p.members.map(bodyLabel).join(' · '), facts: [...pointFacts(p.members), ...patternFacts(p)],
    members: p.members, edges: p.edges, pattern: p, house: p.house ?? undefined })) };
}

function patternFacts(pattern: Pattern): [string, string][] {
  const facts = pattern.facts ?? {};
  const rows: [string, string][] = [];
  if (pattern.aliases?.length) rows.push(['Also called', pattern.aliases.join(', ')]);
  if (facts.sign !== undefined) rows.push(['Shared sign', zodiac(facts.sign * 30)]);
  if (facts.house !== undefined) rows.push(['Shared house', String(facts.house)]);
  if (facts.count !== undefined) rows.push(['Planet and luminary count', String(facts.count)]);
  if (facts.occupied_arc_degrees !== undefined) rows.push(['Smallest occupied arc', `${facts.occupied_arc_degrees.toFixed(3)}°`]);
  if (facts.handle) rows.push(['Handle', bodyLabel(facts.handle)]);
  facts.groups?.forEach((group, i) => rows.push([`Group ${i + 1}`, group.map(bodyLabel).join(', ')]));
  facts.gaps?.forEach(gap => rows.push([`${bodyLabel(gap.first)} → ${bodyLabel(gap.second)} gap`, `${gap.degrees.toFixed(3)}°`]));
  return rows;
}

export function patternExplanation(p: Pattern) {
  if (p.definition) return p.definition;
  if (p.kind === 'grand_trine') return 'Three trines connect these three planets into a triangle.';
  if (p.kind === 'grand_cross') return 'Four squares form the outline; two oppositions join opposite corners with dashed diagonals.';
  return `${bodyLabel(p.apex!)} is the apex where two squares meet. The dashed opposition forms the base.`;
}
