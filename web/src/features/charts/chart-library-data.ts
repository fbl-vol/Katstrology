import { bodyLabel } from './chart-symbols';

export type LibraryTechnique = 'natal' | 'solar_return' | 'lunar_return' | 'planetary_return' |
  'mc_transit' | 'secondary_progression' | 'progressed_mc_contacts' | 'true_solar_arc' |
  'progressed_lunar_phases' | 'actual_lunations_eclipses' | 'synastry_overlay' |
  'midpoint_composite' | 'uncorrected_davison';

export const libraryTitles: Record<LibraryTechnique, string> = {
  natal: 'Natal chart', solar_return: 'Solar return', lunar_return: 'Lunar returns',
  planetary_return: 'Planetary returns', mc_transit: 'Midheaven transit contacts',
  secondary_progression: 'Secondary progressions', progressed_mc_contacts: 'Progressed Midheaven contacts',
  true_solar_arc: 'Solar-arc directions', progressed_lunar_phases: 'Progressed lunar phases',
  actual_lunations_eclipses: 'Lunations and eclipses', synastry_overlay: 'Synastry',
  midpoint_composite: 'Midpoint composite', uncorrected_davison: 'Uncorrected Davison',
};
export type PreviewPosition = { id: string; longitude_degrees: number };
export type LibraryPreview = {
  kind: 'wheel' | 'comparison' | 'timeline' | 'unavailable';
  positions?: PreviewPosition[]; other_positions?: PreviewPosition[];
  aspects?: { first: string; second: string; kind: string }[];
  events?: { date: string | null; label: string }[]; total?: number;
};
export type LibraryResult = {
  id: string; technique: LibraryTechnique; created_at: string; source_status: string;
  date: string | null; window_utc: string[] | null; zone: string | null;
  place: { label: string | null; latitude: number | null; longitude: number | null };
  variant: Record<string, string>; people: { id: string; name: string }[];
  event_count: number | null; preview: LibraryPreview;
};
export type LibraryEntry = { technique: LibraryTechnique; count: number; variants: number;
  representative: LibraryResult | null };
export type LibrarySummary = { person_id: string; entries: LibraryEntry[] };
export type LibraryHistory = { person_id: string; technique: LibraryTechnique;
  entries: LibraryResult[]; next_before: string | null };

export function libraryDate(result: LibraryResult) {
  if (result.technique === 'midpoint_composite') return 'Symbolic midpoint · no physical date';
  if (result.window_utc) return `${result.window_utc[0].slice(0, 10)} – ${result.window_utc[1].slice(0, 10)} · UTC interval`;
  if (!result.date) return result.technique === 'synastry_overlay' ? 'Two saved natal charts' : 'Date not recorded';
  // Birth wall times already belong to the saved zone; never reinterpret them in the browser's zone.
  return `${result.date.slice(0, 10)} · ${result.date.slice(11, 16)} ${result.zone || ''}`.trim();
}

export function libraryPlace(result: LibraryResult) {
  const { label, latitude, longitude } = result.place;
  if (label && result.technique === 'uncorrected_davison' && latitude != null && longitude != null) {
    return `${label} · ${latitude.toFixed(2)}°, ${longitude.toFixed(2)}°`;
  }
  if (label) return label;
  if (latitude != null && longitude != null) return `${latitude.toFixed(2)}°, ${longitude.toFixed(2)}°`;
  if (['synastry_overlay', 'midpoint_composite'].includes(result.technique)) return 'Two source birthplaces';
  return 'No reference place recorded';
}

export function libraryVariant(result: LibraryResult, personId: string) {
  const partner = result.people.filter(person => person.id !== personId).map(person => person.name);
  const variants = Object.entries(result.variant).map(([key, value]) =>
    key === 'branch' ? value === 'mcp' ? 'MCp' : value === 'mcr' ? 'MCr' : value :
      ['body', 'transit_body', 'natal_target'].includes(key) ? bodyLabel(value) : value.replaceAll('_', ' '));
  return [...partner, ...variants].join(' · ');
}
