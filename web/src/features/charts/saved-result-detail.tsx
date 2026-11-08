import { bodyLabel } from './chart-symbols';
import { ReturnWheel, zodiac, type Chart, type NatalResult } from './natal';
import { SymbolicComparisonWheel } from './symbolic-comparison-wheel';

type Point = { id: string; longitude_degrees: number; source_longitude_degrees?: number };
type Contact = { sky_body?: string; longitude_degrees?: number; natal_target?: string;
  aspect?: string; orb_degrees?: number; in_orb?: boolean };
type SavedEvent = { instant_utc?: string; effective_utc?: string; maximum_utc?: string;
  mapped_ephemeris_utc?: string; phase?: string; family?: string; eclipse_type?: string;
  visibility?: string; pass_direction?: string; chart?: NatalResult; target_degrees?: number;
  angular_residual_degrees?: number; sun_degrees?: number; moon_degrees?: number;
  sun_degrees_at_maximum?: number; moon_degrees_at_maximum?: number;
  separation_degrees?: number; linked_syzygy_utc?: string; contacts?: Contact[];
  contacts_at_maximum?: Contact[]; cycle_index?: number;
  progressed_sun_degrees?: number; progressed_moon_degrees?: number };
export type SavedCalculation = {
  status: string; method_version?: string; person_id?: string; source_birth_id?: string;
  source_birth?: Chart['result']['birth']; source_settings?: Chart['result']['profile']['settings'];
  profile_id?: string; profile_revision?: number; engine_version?: string;
  window_utc?: string[]; effective_utc?: string; mapped_ephemeris_utc?: string;
  body?: string; branch?: string; branch_description?: string; transit_body_id?: string;
  natal_body_id?: string; natal_target?: string; aspect?: string; reference_place?: { latitude: number; longitude: number };
  reference_place_source?: { kind: string; label?: string };
  arc_degrees?: number; natal_sun_degrees?: number; progressed_sun_degrees?: number;
  natal_mc_longitude_degrees?: number; natal_mc_degrees?: number; mcp_degrees?: number;
  mc_status?: string; axis_status?: string; age_completed_years?: number;
  positions?: Point[]; natal_positions?: Point[]; events?: SavedEvent[];
  lunations?: SavedEvent[]; eclipses?: SavedEvent[];
};

const format = (utc?: string) => utc ? `${new Date(utc).toLocaleString('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })} UTC` : 'Date not recorded';
const degree = (value?: number) => typeof value === 'number' ? `${value.toFixed(4)}°` : 'Unavailable';

function EventTable({ events, technique }: { events: SavedEvent[]; technique: string }) {
  return <div className="transit-tables"><table><caption>Original saved {technique} points · {events.length}</caption>
    <thead><tr><th scope="col">Date / kind</th><th scope="col">Calculated quantity</th></tr></thead>
    <tbody>{events.map((event, index) => <tr key={`${index}-${event.instant_utc || event.effective_utc || event.maximum_utc}`}>
      <th scope="row">{format(event.maximum_utc || event.instant_utc || event.effective_utc)}
        {event.family && ` · ${event.family} eclipse`}{event.phase && ` · ${event.phase}`}
        {event.pass_direction && ` · ${event.pass_direction}`}</th>
      <td>{event.eclipse_type && `${event.eclipse_type} · `}
        {event.target_degrees != null && `Target ${degree(event.target_degrees)} · `}
        {event.angular_residual_degrees != null && `Residual ${degree(event.angular_residual_degrees)} · `}
        {event.sun_degrees != null && `Sun ${degree(event.sun_degrees)} · `}
        {event.moon_degrees != null && `Moon ${degree(event.moon_degrees)} · `}
        {event.progressed_sun_degrees != null && `Progressed Sun ${degree(event.progressed_sun_degrees)} · `}
        {event.progressed_moon_degrees != null && `Progressed Moon ${degree(event.progressed_moon_degrees)} · `}
        {event.separation_degrees != null && `Separation ${degree(event.separation_degrees)} · `}
        {event.sun_degrees_at_maximum != null && `Sun at maximum ${degree(event.sun_degrees_at_maximum)} · `}
        {event.moon_degrees_at_maximum != null && `Moon at maximum ${degree(event.moon_degrees_at_maximum)} · `}
        {event.linked_syzygy_utc && `Nearby syzygy ${format(event.linked_syzygy_utc)} · `}
        {event.visibility === 'global_only_not_calculated_for_location' && 'Global maximum; local visibility not calculated.'}
        {event.mapped_ephemeris_utc && `Mapped symbolic date ${format(event.mapped_ephemeris_utc)}`}
        {((event.contacts || event.contacts_at_maximum) || []).map((contact, n) =>
          <span key={n}> · {contact.sky_body} to natal {contact.natal_target} {contact.aspect},
            orb {degree(contact.orb_degrees)}{contact.in_orb ? ' (in saved orb)' : ' (outside saved orb)'}</span>)}</td>
    </tr>)}</tbody></table></div>;
}

/** A read-only original calculation. All arrays below come from owner-scoped GET, never a recomputation. */
export function SavedResultDetail({ result, resultId, technique, sourceStatus }: {
  result: SavedCalculation; resultId: string; technique: string; sourceStatus: string;
}) {
  const symbolic = technique === 'secondary_progression' || technique === 'true_solar_arc';
  const returns = ['solar_return', 'lunar_return', 'planetary_return'].includes(technique);
  const events = result.events || [];
  return <section className="timing-opened" aria-label="Opened saved calculation">
    <h3>{sourceStatus === 'current' ? 'Saved calculation' : 'Historical source · saved calculation'}</h3>
    <p>{result.window_utc ? `Saved interval ${format(result.window_utc[0])} to ${format(result.window_utc[1])} (end excluded).` :
      result.effective_utc ? `Effective ${format(result.effective_utc)}.` : 'Saved interval not recorded.'}
      {' '}No values were recalculated.</p>
    {technique === 'planetary_return' && result.body && <p>{bodyLabel(result.body)} returns to its saved natal longitude.
      {result.reference_place_source?.label && ` Reference place: ${result.reference_place_source.label}.`}</p>}
    {result.reference_place && !result.reference_place_source?.label && <p>Reference coordinates: {degree(result.reference_place.latitude)} latitude,
      {' '}{degree(result.reference_place.longitude)} longitude. This place does not change a geocentric crossing instant.</p>}
    {result.transit_body_id && <p>{bodyLabel(result.transit_body_id)} {result.aspect} to saved astronomical natal MC
      {result.natal_mc_longitude_degrees != null && ` at ${zodiac(result.natal_mc_longitude_degrees)}`}.
      {' '}This is not a tenth-house cusp.</p>}
    {result.branch_description && <p>{result.branch_description} · {bodyLabel(result.body || '')} {result.aspect}.</p>}
    {result.natal_target && <p>Real-sky Moon/Sun contact to saved natal {bodyLabel(result.natal_target)}
      {result.aspect && ` (${result.aspect})`}; eclipse visibility is global only.</p>}
    {symbolic && <><p>{technique === 'true_solar_arc' ?
      `True forward solar arc ${degree(result.arc_degrees)}; saved natal Sun ${degree(result.natal_sun_degrees)}, directly progressed Sun ${degree(result.progressed_sun_degrees)}.` :
      `Secondary progression for age ${result.age_completed_years ?? 'unknown'} years. Progressed MC ${degree(result.mcp_degrees)} (${result.mc_status || 'status unavailable'}).`}
      {' '}Mapped symbolic ephemeris instant: {format(result.mapped_ephemeris_utc)}. Not the simultaneous sky.</p>
      {result.positions && result.natal_positions && <SymbolicComparisonWheel
        positions={result.positions} natalPositions={result.natal_positions}
        label={technique === 'true_solar_arc' ? 'Directed' : 'Progressed'}
        description="Original saved symbolic and natal longitude positions, not current sky positions or inferred houses."
        stem={`kat-saved-${resultId}`} provenance={{ result_id: resultId, method_version: result.method_version,
          source_status: sourceStatus, effective_utc: result.effective_utc,
          mapped_ephemeris_utc: result.mapped_ephemeris_utc, positions: result.positions }} />}
      {result.positions && <details className="chart-supporting-data"><summary>Saved positions · {result.positions.length}</summary>
        <div className="transit-tables"><table><caption>{technique === 'true_solar_arc' ? 'Directed natal longitudes' : 'Progressed longitudes'}</caption>
          <thead><tr><th scope="col">Body / axis</th><th scope="col">Saved longitude</th><th scope="col">Natal longitude</th></tr></thead>
          <tbody>{result.positions.map(point => <tr key={point.id}><th scope="row">{bodyLabel(point.id)}</th>
            <td>{zodiac(point.longitude_degrees)}</td><td>{point.source_longitude_degrees == null ? 'See natal wheel' : zodiac(point.source_longitude_degrees)}</td>
          </tr>)}</tbody></table></div></details>}</>}
    {returns && events.map((event, index) => <article key={index}>
      <h4>{format(event.instant_utc)}{event.pass_direction && ` · ${event.pass_direction}`}</h4>
      {event.angular_residual_degrees != null && <p>Angular residual: {degree(event.angular_residual_degrees)}</p>}
      {event.chart && result.source_birth && result.source_settings && result.person_id &&
        result.source_birth_id && result.profile_id && result.profile_revision &&
        result.method_version && result.engine_version && <ReturnWheel natal={event.chart}
          resultId={`${resultId}-${index}`} personId={result.person_id} birthId={result.source_birth_id}
          label={result.body ? `${bodyLabel(result.body)} return` : technique === 'solar_return' ? 'Solar return' : 'Lunar return'}
          methodVersion={result.method_version} profileId={result.profile_id}
          profileRevision={result.profile_revision} sourceStatus={sourceStatus}
          sourceBirth={result.source_birth} sourceSettings={result.source_settings}
          engineVersion={result.engine_version} />}</article>)}
    {technique === 'actual_lunations_eclipses' && <>
      <p>Geocentric lunations and physically distinct global eclipse maxima. A maximum is not the nearby syzygy instant.</p>
      <EventTable events={result.lunations || []} technique="lunation" />
      <EventTable events={result.eclipses || []} technique="global eclipse maximum" /></>}
    {!symbolic && !returns && technique !== 'actual_lunations_eclipses' && <EventTable events={events} technique={technique.replaceAll('_', ' ')} />}
    {technique === 'progressed_lunar_phases' && <p>These effective dates map one ephemeris day to each lived UTC anniversary year, not actual sky phases or predicted life events.</p>}
  </section>;
}
