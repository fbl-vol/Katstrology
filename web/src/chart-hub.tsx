import { useEffect, useRef } from 'react';
import type { Person } from './people';

export type ChartChoice = 'hub' | 'natal' | 'child' | 'synastry' | 'solar_return' | 'lunar_return' | 'mc_transit' | 'secondary_progression' | 'relationship_derived' | 'true_solar_arc' | 'progressed_lunar_phases' | 'actual_lunations_eclipses' | 'planetary_return';

const groups = [
  { title: 'Personal charts', description: 'Begin with a birth chart.', choices: [
    { id: 'natal', title: 'Natal chart', description: 'Create or update a birth chart from supplied details.' },
    { id: 'child', title: 'Child’s natal', description: 'A family-focused starting point using the same natal chart.' },
  ] },
  { title: 'Relationships', description: 'Explore two charts together.', choices: [
    { id: 'synastry', title: 'Synastry', description: 'See how two natal charts connect through aspects.' },
    { id: 'relationship_derived', title: 'Composite and Davison', description: 'Explore two distinct symbolic charts for a pair.' },
  ] },
  { title: 'Timing', description: 'Explore dates, cycles and changes.', choices: [
    { id: 'transits', title: 'Transits', description: 'See the sky on a chosen date, alongside a natal chart if you like.' },
    { id: 'solar_return', title: 'Solar return', description: 'Choose a person and birthday-to-birthday cycle for the Sun’s return.' },
    { id: 'lunar_return', title: 'Lunar returns', description: 'Choose a person and period to find Moon returns.' },
    { id: 'planetary_return', title: 'Planetary returns', description: 'Find Jupiter, Saturn, Venus or Mars returns, including repeated passes.' },
    { id: 'mc_transit', title: 'Midheaven transit contacts', description: 'Find dated contacts to the saved Midheaven.' },
    { id: 'secondary_progression', title: 'Secondary progressions', description: 'See symbolic progressed positions for a chosen date.' },
    { id: 'true_solar_arc', title: 'Solar-arc directions', description: 'See true progressed-Sun arc directions, not a fixed yearly step.' },
    { id: 'progressed_lunar_phases', title: 'Progressed lunar phases', description: 'Explore symbolic phase changes over a lifetime.' },
    { id: 'actual_lunations_eclipses', title: 'Lunations and eclipses', description: 'Find actual New and Full Moons and global eclipse moments.' },
  ] },
] as const;

type ChoiceId = (typeof groups)[number]['choices'][number]['id'];

export function ChartHub({ choice, people, onSelect, onPerson, onAddPerson, onClose }: {
  choice: ChartChoice; people: Person[]; onSelect: (choice: ChoiceId) => void;
  onPerson: (id: string) => void; onAddPerson: () => void; onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { const frame = requestAnimationFrame(() => heading.current?.focus());
    return () => cancelAnimationFrame(frame); }, [choice]);
  return <section className="chart-hub" aria-label="Create chart">
    <div className="chart-hub-heading"><div><span className="eyebrow">EXPLORE YOUR CHARTS</span>
      <h1 ref={heading} tabIndex={-1}>{choice === 'hub' ? 'Create chart' : choice === 'child' ? 'Child’s natal chart' : 'Natal chart'}</h1>
      <p>{choice === 'child' ? 'Choose or create a person to make an ordinary natal chart, with space for a family-focused conversation afterward. No age or birth time is assumed.' :
        choice === 'hub' ? 'What would you like to explore?' :
          'Choose or create a person to make a birth chart. Earlier versions remain in History.'}</p></div>
      <button type="button" onClick={onClose}>{choice === 'hub' ? 'Return to workspace' : 'Back to chart choices'}</button></div>
    {choice === 'hub' ? <div className="chart-hub-groups">{groups.map(group => <section key={group.title} className="chart-hub-group" aria-label={group.title}>
      <div className="chart-hub-group-heading"><h2>{group.title}</h2><p>{group.description}</p></div>
      <div className="chart-hub-grid">{group.choices.map(item => <button key={item.id} type="button" className="chart-hub-choice" onClick={() => onSelect(item.id)}>
        <strong>{item.title}</strong><span>{item.description}</span><span aria-hidden="true" className="hub-arrow">→</span>
      </button>)}</div>
    </section>)}</div> : <div className="chart-hub-people"><h2>Choose a person</h2>
      <button type="button" className="primary" onClick={onAddPerson}>Create a person</button>
      {people.length ? <div className="chart-hub-list">{people.map(person => <button type="button" key={person.id} onClick={() => onPerson(person.id)}>
        {person.name}<span>{person.active_chart_id ? 'Edit current natal' : 'Create first natal'}</span>
      </button>)}</div> : <p>No people yet. Create one to supply birth details.</p>}</div>}
  </section>;
}
