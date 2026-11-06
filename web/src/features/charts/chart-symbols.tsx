import formsFont from '../../shared/assets/kat-astro-forms.woff?inline';
import sunFont from '../../shared/assets/kat-astro-sun.woff?inline';

const bodies = [
  ['sun', '☉', 'Sun'], ['moon', '☽', 'Moon'], ['mercury', '☿', 'Mercury'],
  ['venus', '♀', 'Venus'], ['mars', '♂', 'Mars'], ['jupiter', '♃', 'Jupiter'],
  ['saturn', '♄', 'Saturn'], ['uranus', '♅', 'Uranus'], ['neptune', '♆', 'Neptune'],
  ['pluto', '♇', 'Pluto'], ['chiron', 'Ch', 'Chiron (opt-in)'],
  ['lilith_mean', 'BM', 'Black Moon Lilith (mean lunar apogee)'],
  ['lilith_osculating', 'BT', 'Black Moon Lilith (true / osculating lunar apogee)'],
  ['north_node', '☊', 'North Node'],
  ['south_node', '☋', 'South Node'],
] as const;

const byId = new Map<string, { glyph: string; label: string }>(
  bodies.map(([id, glyph, label]) => [id, { glyph, label }]));

export function bodyLabel(id: string) {
  if (id === 'ascendant') return 'Ascendant';
  if (id === 'midheaven') return 'Midheaven';
  if (id === 'progressed_mc') return 'Progressed MC (MCp)';
  if (id === 'natal_mc') return 'Natal MC';
  return byId.get(id)?.label || id.replaceAll('_', ' ');
}

export function bodyGlyph(id: string) {
  return byId.get(id)?.glyph || null;
}

export const chartNotation = bodies.filter(([id]) => id !== 'chiron' && !id.startsWith('lilith_'))
  .map(([, glyph, label]) => `${glyph} ${label}`).join(' · ') +
  ' · Asc Ascendant · MC Midheaven';

// Insert only in a detached standalone export, never in the page DOM under CSP.
// Its URLs are literal bundled subset WOFF bytes; export has no remote dependency.
export const embeddedGlyphFontsStyle = `@font-face{font-family:KatAstro;src:url("${formsFont}") format("woff");}
@font-face{font-family:KatAstroSun;src:url("${sunFont}") format("woff");}`;

export function Glyph({ id }: { id: string }) {
  const mark = byId.get(id);
  if (!mark) return <>{bodyLabel(id)}</>;
  return <span className={id === 'sun' ? 'astro-glyph astro-sun' : 'astro-glyph'} aria-hidden="true">{mark.glyph}</span>;
}

export function ChartNotation({ rings, ids }: { rings: string; ids?: string[] }) {
  const visible = new Set(ids || bodies.filter(([id]) => id !== 'chiron' && !id.startsWith('lilith_')).map(([id]) => id));
  return <details className="chart-notation"><summary>Symbols</summary>
    <p>{rings} Zodiac labels use the first three letters of each sign. Numbered rays mark house cusps when supported; aspect lines are listed by name and orb in the tables. Color is never the only source of a chart fact.</p>
    <table><caption>Planet and lunar node symbols on this wheel</caption><tbody>
      {bodies.filter(([id]) => visible.has(id)).map(([id, , label]) => <tr key={id}>
        <td><Glyph id={id} /></td><th scope="row">{label}</th></tr>)}
    </tbody></table>
    <p>Asc = Ascendant · MC = Midheaven (when calculated).</p>
  </details>;
}
