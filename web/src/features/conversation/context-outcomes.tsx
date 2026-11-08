import type { Person } from '../people/people';
import type { Turn } from './turns';

type Update = { entry_id: string; person_id?: string; outcome: string };
const labels: Record<string, string> = {
  saved: 'saved at completion', discarded: 'discarded', conflict: 'not saved because the entry or source changed',
  storage_failed: 'not saved because storage failed',
};

export function ContextOutcomes({ turn, people, inspect }: {
  turn: Turn; people: Person[]; inspect?: (id: string) => void;
}) {
  const terminal = turn.events.find(event => ['complete', 'interrupted', 'error'].includes(event.kind));
  if (!terminal) return null;
  const updates = (terminal.payload.personal_context_updates ?? []) as Update[];
  const rejected = turn.events.filter(event => event.kind === 'tool_result' &&
    event.payload.name === 'stage_personal_context' && (event.payload.result as { error?: string } | undefined)?.error).length;
  const context = turn.events.find(event => event.kind === 'user')?.payload.personal_context as
    { consent?: { enabled?: boolean } } | undefined;
  // An absent proposal has no success signal. Keep the explanation quiet and
  // opt-in-only, not a success banner on ordinary greetings.
  if (!updates.length && !rejected && !context?.consent?.enabled) return null;
  const saved = updates.filter(update => update.outcome === 'saved').length;
  const unsaved = updates.length - saved + rejected;
  return <details className="chat-source-evidence"><summary>Personal context · {saved ? `${saved} saved` : 'no confirmed saves'}{unsaved ? ` · ${unsaved} not saved` : ''}</summary>
    {!!updates.length && <ul>{updates.map(update => <li key={update.entry_id}>{labels[update.outcome] ?? 'outcome unavailable'}</li>)}</ul>}
    {!!rejected && <p>{rejected} {rejected === 1 ? 'proposal was' : 'proposals were'} rejected. Nothing was saved from those proposals.</p>}
    {!updates.length && !rejected && <p>No personal-context update was proposed. This does not mean your profile is empty or that every fact was considered.</p>}
    <p>These are this attempt’s archived outcomes, not a current storage audit. Entries can later be edited, removed or invalidated. Check Context to inspect what is available now; no automatic retry will run.</p>
    {inspect && turn.selected_people.map(selected => <button type="button" className="quiet-action" key={selected.person_id}
      onClick={() => inspect(selected.person_id)}>Inspect Context · {people.find(person => person.id === selected.person_id)?.name ?? 'selected person'}</button>)}
  </details>;
}
