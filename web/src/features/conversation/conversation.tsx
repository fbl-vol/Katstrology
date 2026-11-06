import { useLayoutEffect, useRef, useState } from 'react';
import type { Person } from '../people/people';

export type Selection = { person_id: string };
export type Conversation = { id: string; title: string; active_head: string | null; created_at: string;
  title_origin?: 'placeholder' | 'generated' | 'manual' | 'legacy';
  title_status?: 'waiting' | 'pending' | 'generated' | 'failed' | 'stale' | 'untouched';
  people: { person_id?: string; id?: string; name: string }[]; turn_count?: number;
  preview?: string | null; preview_speaker?: 'user' | 'historical_user' | 'assistant' | 'correction' | null;
  preview_pending?: boolean };

export function ConversationBrowseList({ conversations, selectedId, zone, onOpen }: {
  conversations: Conversation[]; selectedId?: string; zone: string; onOpen: (id: string) => void;
}) {
  const month = new Intl.DateTimeFormat('en-GB', { timeZone: zone, month: 'long', year: 'numeric' });
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: zone, day: 'numeric', month: 'short', year: 'numeric' });
  let previousMonth = '';
  return <>{conversations.map(item => {
    const instant = new Date(item.created_at);
    const heading = month.format(instant);
    const newMonth = heading !== previousMonth;
    previousMonth = heading;
    const preview = item.preview ? `${item.preview_speaker === 'assistant' ? 'Kat' :
      item.preview_speaker === 'correction' ? 'Correction' : 'You'}: ${item.preview}` :
      item.preview_pending ? 'Updating current preview…' : item.turn_count ? 'Current preview unavailable' : 'No messages yet';
    return <div className="recent-entry" key={item.id}>
      {newMonth && <h3 className="recent-month">{heading}</h3>}
      <button type="button" className={selectedId === item.id ? 'active' : ''} onClick={() => onOpen(item.id)}>
        <strong className="recent-title">{item.title || 'Untitled conversation'}</strong>
        <span className="recent-preview">{preview}</span>
        <small><time dateTime={item.created_at}>{day.format(instant)}</time> · {item.people.map(p => p.name).join(' & ') || 'General'} · Copenhagen date</small>
      </button>
    </div>;
  })}</>;
}

export function ScopePicker({ people, selected, onClose, onApply }: {
  people: Person[]; selected: Selection[];
  onClose: () => void; onApply: (selection: Selection[]) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  // Mount a fresh picker with the committed selection before exposing the modal.
  const [choice, setChoice] = useState<Selection[]>(selected);
  useLayoutEffect(() => {
    dialog.current?.showModal();
    return () => { if (dialog.current?.open) dialog.current.close(); };
  }, []);

  return <dialog ref={dialog} onClose={onClose} aria-labelledby="scope-title"><div className="dialog-body">
    <div className="dialog-top"><h2 id="scope-title">Who’s this about?</h2><button type="button" aria-label="Close person selector" onClick={() => dialog.current?.close()}>×</button></div>
    <p>Choose up to eight people or nobody. Each new turn uses the current generated natal for each selected person, if available; archived turns keep their original versions.</p>
    <div className="picker-list">{people.length ? people.map(person => {
      const chosen = choice.some(item => item.person_id === person.id);
      return <label className="picker-option" key={person.id}><input type="checkbox" checked={chosen}
        onChange={event => setChoice(event.target.checked ? [...choice, { person_id: person.id }] :
          choice.filter(item => item.person_id !== person.id))} /> {person.name}
        <small>{person.active_chart_id ? 'Current generated natal' : 'No generated natal yet'}</small>
      </label>;
    }) : <p>No people yet. Leave the selection empty for a general conversation.</p>}</div>
    <div className="dialog-footer"><button type="button" onClick={() => dialog.current?.close()}>Cancel</button>
      <button type="button" className="primary" disabled={choice.length > 8}
        onClick={() => { onApply(choice); dialog.current?.close(); }}>Use selection</button></div>
  </div></dialog>;
}

export function ScopeChips({ selection, people, remove, open }: {
  selection: Selection[]; people: Person[]; remove: (id: string) => void; open: () => void;
}) {
  return <div className="scope-row"><span>About</span>
    {selection.length ? selection.map(item => {
      const person = people.find(value => value.id === item.person_id);
      return <span className="person-chip" key={item.person_id}
        data-kat-person-id={item.person_id} data-kat-chart-id={person?.active_chart_id || ''}>
        <span className="initial">{person?.name.charAt(0).toUpperCase() || '·'}</span>
        <span className="chip-name" title={person?.name || 'Selected person'}>{person?.name || 'Selected person'}</span>
        <small>{person?.active_chart_id ? 'current natal' : 'no natal'}</small>
        <button type="button" aria-label={`Remove ${person?.name || 'person'} from new turn`} onClick={() => remove(item.person_id)}>×</button>
      </span>;
    }) : <span className="scope-general">Anything you like</span>}
    <button type="button" className="add-scope" onClick={open}>＋ Add person</button>
  </div>;
}
