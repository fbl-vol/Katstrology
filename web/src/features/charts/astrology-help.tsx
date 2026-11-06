export function AstrologyHelp() {
  return <details className="detail-section profile-secondary astrology-help">
    <summary>What do these chart terms mean?</summary>
    <dl>
      <dt>MC (Midheaven)</dt><dd>A calculated angle tied to the local meridian at a known birth time and place. Without reliable time or supported houses, this angle may be unavailable. Traditional meanings about public life are interpretation, not a measured outcome.</dd>
      <dt>Aspects</dt><dd>Measured angular separations between chart positions. The tables give the selected aspect and its distance from exactness (orb); their personal significance is an interpretive choice.</dd>
      <dt>Returns</dt><dd>Real-sky instants when a body reaches its saved natal longitude. A solar return has an anniversary cycle; Moon and other planetary returns can cross more than once, including retrograde repeats. A reference place changes the chart's local angles, not the crossing instant.</dd>
      <dt>Transits</dt><dd>Real-sky positions on actual dates compared with a saved natal chart. Exact contacts are dated points; an influence interval is a separate qualified range, not proof that something will happen.</dd>
      <dt>Secondary progressions and solar arc</dt><dd>Symbolic timing methods, not current sky positions. Secondary progression maps days after birth to years of life; solar arc advances natal positions by the progressed Sun's angular change. Their effective dates and methods are shown with saved results.</dd>
      <dt>Synastry and composite</dt><dd>Synastry compares two actual saved charts and, when supported, each person's placements in the other's houses. A midpoint composite is a calculated midpoint of two charts; the uncorrected Davison method uses averaged birth coordinates and time. Neither is a third person's measured birth or a relationship verdict.</dd>
    </dl>
  </details>;
}
