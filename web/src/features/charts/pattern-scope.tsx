import { bodyLabel } from './chart-symbols';
import type { Exploration, Pattern } from './exploration-data';

export function PatternScope({ projection }: { projection: Exploration }) {
  const rules = projection.catalogue;
  if (!rules) return null;
  const skipped = rules.filter(rule => rule.status !== 'evaluated');
  return <>
    {projection.status === 'supported' && skipped.length > 0 && <p className="explorer-note">
      Some formations could not be checked. See the supported catalogue for saved-setting and house limits.</p>}
    {projection.distribution?.status === 'mixed' && <p className="explorer-note">
      The whole-chart distribution is mixed or borderline under the definitions below.</p>}
    <details className="explorer-scope"><summary>Supported patterns and definitions</summary>
      <p>Only Sun through Pluto participate, including the Sun and Moon once each. Nodes, Chiron, Lilith and angles do not count.</p>
      <p>Major connections use the saved aspects and orb limits. Quincunxes, sesquiquadrates, quintiles and biquintiles are derived from saved positions with a fixed 2° orb. They do not change the saved chart.</p>
      <p>Concentrations and whole-chart shapes use positions, not aspect polygons. Shape thresholds are a strict working convention; mixed charts are not forced into a shape.</p>
      <dl className="explorer-facts">{rules.map(rule => <div key={rule.kind}>
        <dt>{rule.name}</dt><dd>{rule.definition}
          {rule.aliases.length > 0 && <> Also called {rule.aliases.join(', ')}.</>}
          <br /><strong>{rule.status === 'evaluated' ? `${rule.matches} matches` :
            rule.status === 'excluded' ? 'Not checked: excluded by saved aspect settings.' :
              rule.reason === 'unavailable_houses' ? 'Not checked: reliable houses unavailable.' : 'Not checked: required saved facts unavailable.'}</strong>
        </dd></div>)}</dl>
      <p>Specialist learning, irritation, septile and novile figures and other higher-harmonic variants are outside this catalogue, not reported as absent.</p>
    </details>
  </>;
}

export function PatternConnections({ pattern, projection }: { pattern: Pattern; projection: Exploration | null }) {
  const evidence = projection?.evidence?.filter(edge => pattern.edges.includes(edge.id)) ?? [];
  if (!evidence.length) return null;
  return <details className="explorer-connections"><summary>{evidence.length} qualifying connections and orb limits</summary>
    <dl className="explorer-facts">{evidence.map(edge => <div key={edge.id}>
      <dt>{bodyLabel(edge.first)} {edge.kind} {bodyLabel(edge.second)}</dt>
      <dd>{edge.exact_degrees}° angle · {edge.orb_degrees.toFixed(3)}° orb · {edge.limit_degrees}° limit.
        {' '}{edge.origin === 'derived' ? 'Derived from saved positions; fixed pattern orb, not a saved aspect.' : 'Saved aspect and saved orb limit.'}</dd>
    </div>)}</dl>
  </details>;
}
