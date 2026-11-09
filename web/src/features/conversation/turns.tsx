import { memo, useMemo, useState } from 'react';
import { AssistantMarkdown } from './assistant-markdown';
import { ThinkingIndicator } from './thinking';
import { ContextOutcomes } from './context-outcomes';
import type { Person } from '../people/people';
import { TransitResult, type TransitResultData } from '../charts/transit-result';
import { SaveInsight } from '../people/insights';
import type { Workspace } from '../../shared/api';

export type ArchiveEvent = { sequence: number; kind: string; payload: Record<string, unknown>; stored_at?: string };
export type Turn = {
  id: string; parent_id: string | null; status: string; revision_kind: string;
  replaces_turn_id: string | null; on_active_branch?: boolean;
  selected_people: { person_id: string; draft_revision: number | null; chart_id: string | null;
    attachment_id?: string | null }[];
  corrections: { id: string; action: string; replacement: string | null }[];
  events: ArchiveEvent[]; event_count: number; next_event_offset: number | null;
};

export function awaitingFirstWords(turn: Turn): boolean {
  return turn.status === 'open' && !turn.events.some(event =>
    event.kind === 'assistant_chunk' && !!String(event.payload.content || ''));
}

function TransitDisclosure({ item, turn, people }: { item: ArchiveEvent; turn: Turn; people: Person[] }) {
  const [open, setOpen] = useState(false);
  const result = item.payload.result as TransitResultData;
  const bound = turn.selected_people.find(selected => selected.chart_id && selected.chart_id === result.chart_id);
  const subject = result.mode === 'sky' ? undefined : bound ?
    people.find(person => person.id === bound.person_id)?.name || 'A person no longer in this workspace' : 'Unmatched saved natal chart';
  const supported = result.status === 'supported' && Array.isArray(result.positions) &&
    Array.isArray(result.natal_positions) && Array.isArray(result.same_sky_aspects) &&
    Array.isArray(result.transit_to_natal_aspects) && !!result.reporting;
  return <details className="chat-transit-card" onToggle={event => setOpen(event.currentTarget.open)}><summary>
    {supported ? `Open ${subject || 'Sky'} · calculated ${result.mode === 'sky' ? 'sky' : 'natal + transits'} chart · ${result.reporting.date} ${result.reporting.time}` :
      'Requested full chart unavailable for this selection'}
  </summary>{open && (supported || result.status !== 'supported' ?
    <TransitResult result={result} subject={subject} /> :
    <p>Only a partial saved chart is available. No unsupported wheel or invented natal positions are shown.</p>)}</details>;
}

type PassageRead = {
  source_id: string; passage_id: string; author: string; title: string;
  edition: string; section: string; content: string; source_url?: string | null;
  offset: number; next_offset: number | null;
};

function archivedPassage(event: ArchiveEvent): PassageRead | null {
  if (event.kind !== 'tool_result' || event.payload.name !== 'get_reference_passage') return null;
  const result = event.payload.result;
  if (!result || typeof result !== 'object') return null;
  const row = result as Record<string, unknown>;
  if (['source_id', 'passage_id', 'author', 'title', 'edition', 'section', 'content']
      .some(key => typeof row[key] !== 'string')) return null;
  return row as PassageRead;
}

function SourceEvidence({ passages }: { passages: { sequence: number; read: PassageRead }[] }) {
  if (!passages.length) return null;
  return <details className="chat-source-evidence"><summary>Sources consulted ({passages.length})</summary>
    <p>These are the actual saved excerpts, not a check that each claim follows from them. A source may have changed or been withdrawn since this reply.</p>
    {passages.map(({ sequence, read }) => <section key={sequence} className="chat-source-passage">
      <p><strong>{read.author}</strong>, <cite>{read.title}</cite> · {read.edition} · {read.section}</p>
      <blockquote>{read.content}</blockquote>
      {read.next_offset !== null && <p>More of this passage was available than this read retrieved.</p>}
      {read.source_url?.startsWith('https://') && <a href={read.source_url} target="_blank" rel="noreferrer noopener">Original source</a>}
    </section>)}
  </details>;
}

export type TurnActions = {
  onBranch: (id: string) => void;
  onEdit: (turn: Turn) => void;
  onRegenerate: (turn: Turn) => void;
  onRetryFailed: (turn: Turn) => void;
  onCorrect: (turn: Turn, action: 'correct' | 'withdraw', replacement: string | null) => void;
  onRetryEvents: (turn: Turn) => void;
};

export const TurnCard = memo(function TurnCard({ turn, people, workspace, conversationId, activeHead, actions,
  eventFailure, displayBody = true, showRevisionActions = true, onInspectContext }: {
  turn: Turn; people: Person[]; workspace: Workspace; conversationId: string; activeHead: string | null;
  actions: { current: TurnActions }; eventFailure?: string;
  displayBody?: boolean; showRevisionActions?: boolean;
  onInspectContext?: (id: string) => void;
}) {
  const [correction, setCorrection] = useState(false);
  const [replacement, setReplacement] = useState('');
  const { user, chunks, calculatedViews, passages, terminalError } = useMemo(() => {
    let user: ArchiveEvent | undefined;
    let terminalError: Record<string, unknown> | undefined;
    const text: string[] = [];
    const calculatedViews: ArchiveEvent[] = [];
    const passages: { sequence: number; read: PassageRead }[] = [];
    for (const event of turn.events) {
      if (event.kind === 'user' && !user) user = event;
      if (event.kind === 'error' && !terminalError) terminalError = event.payload;
      if (event.kind === 'assistant_chunk') text.push(String(event.payload.content || ''));
      const read = archivedPassage(event);
      if (read) passages.push({ sequence: event.sequence, read });
      if (event.kind === 'tool_result' && event.payload.name === 'get_transit_view' &&
          event.payload.result && typeof event.payload.result === 'object') calculatedViews.push(event);
    }
    return { user, chunks: text.join(''), calculatedViews, passages, terminalError };
  }, [turn.events]);
  const compacting = turn.status === 'open' && turn.events.some(event =>
    event.kind === 'compaction' && event.payload.status === 'starting') &&
    !turn.events.some(event => event.kind === 'compaction' && event.payload.status !== 'starting');
  const waiting = turn.status === 'open' && !chunks;
  const terminalVisible = turn.events.some(event => ['complete', 'interrupted', 'error'].includes(event.kind));
  const loadingEvents = turn.next_event_offset !== null || (turn.status !== 'open' && !terminalVisible);
  const hasAnswer = waiting || chunks.length > 0 ||
    (turn.status === 'complete' && !loadingEvents && !eventFailure);
  const selectedNames = turn.selected_people.map(item =>
    people.find(person => person.id === item.person_id)?.name || 'A person no longer in this workspace').join(' & ');
  const earlierChart = turn.selected_people.some(item => item.chart_id &&
    people.some(person => person.id === item.person_id && person.active_chart_id !== item.chart_id));
  const savedFile = turn.selected_people.some(item => item.attachment_id);
  return <article data-kat-turn-id={turn.id} data-kat-status={turn.status}
    className={`turn-card${turn.on_active_branch === false ? ' historical' : ''}`}>
    {(turn.on_active_branch === false || turn.revision_kind !== 'normal' || turn.status !== 'complete') &&
      <div className="turn-state">{turn.on_active_branch === false && <span>Historical branch</span>}
        {turn.revision_kind !== 'normal' && <span>{turn.revision_kind === 'edit' ? 'Edited message' :
          turn.revision_kind === 'regenerate' ? 'Regenerated reply' : 'Revised message'}</span>}
        {turn.status === 'open' && <span>Writing</span>}</div>}
    {selectedNames && <p className="turn-context">About {selectedNames}
      {earlierChart && ' · Earlier chart used for this message'}
      {savedFile && ' · Saved file supplied with this turn'}</p>}
    {displayBody && <><p className="user-bubble">{String(user?.payload.content || 'Archived input on another event page')}</p>
      {hasAnswer && <div className="assistant-answer"><span className="assistant-signature">kat.</span>
        {waiting ? <ThinkingIndicator waitId={turn.id} /> : <AssistantMarkdown text={chunks || 'No text returned.'} />}</div>}</>}
    {calculatedViews.map(item => <TransitDisclosure key={item.sequence} item={item} turn={turn} people={people} />)}
    <SourceEvidence passages={passages} />
    {compacting && <p className="compaction-status" role="status">Summarizing earlier conversation before responding…</p>}
    {turn.status === 'error' && <p className="turn-warning" role="alert">{terminalError?.tool ?
      'A chart or source lookup could not finish.' :
      terminalError?.code === 'local_model_context_limit' ?
      `The local test model's ${String(terminalError.context_limit)}-token window cannot fit this message with its required instructions and selected chart facts. No model ran. To discuss the full chart, explicitly choose a connected hosted model; sending a new message is your choice.` :
      terminalError?.code === 'tool_round_capacity_exceeded' ?
      'A requested read was saved, but its continuation would exceed the selected model’s estimated context allowance. No further model call ran; narrow the question in a new turn.' :
      terminalError?.code === 'tool_round_limit' ?
      'An earlier turn stopped at the old combined read-round/duplicate-ID guard. The archived code alone does not identify which condition occurred; this turn will not rerun automatically.' :
      terminalError?.code === 'duplicate_tool_call_id' ?
      'The provider repeated a native tool-call identity. Kat stopped rather than associate a result with the wrong call.' :
      terminalError?.code === 'tool_result_capacity' ?
      'A requested read was too large for the bounded model evidence allowance. No further model call ran; ask for a narrower passage or window in a new turn.' :
      terminalError?.code === 'hosted_text_capacity_exceeded' ?
      `The selected model's ${String(terminalError.context_limit)}-token context allowance cannot fit the estimated instructions, selected facts and this message. Older history cannot displace these required facts. This is Kat's preflight estimate, not a measured provider error. Shorten the request or select fewer charts, then send a new message.` :
      terminalError?.reason === 'model_context_capacity_unknown' ?
      'A safe context and output capacity pair is unavailable for this hosted model. No inference ran. Select a model with known bounds for a new message; Kat will not guess a 4K limit.' :
      terminalError?.reason === 'invalid_model_context_metadata' ?
      'The hosted model catalog supplied invalid capacity metadata, so Kat did not send this message. Choose another known-capacity model or try the connection again later.' :
      terminalError?.code === 'compaction_failed' ?
      'The older conversation could not be summarized safely. No reply was sent; the last valid summary and original turns remain. Send a new message when ready.' :
      terminalError?.reason === 'selected_context_exceeds_model_budget' ?
      'The message and selected profiles exceed this model’s bounded text context. Choose fewer people or shorten the message.' :
      terminalError?.reason === 'unsupported_provider_output' ?
      'The provider returned an incomplete or unsupported response. No tool from this response was run.' :
      'The selected model or archive write failed before this reply could finish.'}
      {' '}The original input and any committed prefix remain. This saved attempt will not run again automatically.
      {terminalError?.reason === 'subscription_sharing_usage_limit_exceeded' && <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer noopener"> Manage usage</a>}
      {savedFile ? <span> To try again, reselect the file and give fresh consent.</span> :
        <button className="quiet-action" onClick={() => actions.current.onRetryFailed(turn)}>
          Try again as a new message with current selection</button>}</p>}
    <ContextOutcomes turn={turn} people={people} inspect={onInspectContext} />
    {turn.status === 'interrupted' && <p className="turn-warning">Interrupted. The committed prefix is preserved; continue in a new turn if needed.</p>}
    {eventFailure ? <p className="turn-warning" role="alert">{eventFailure}{' '}
      <button className="quiet-action" onClick={() => actions.current.onRetryEvents(turn)}>Retry loading saved reply</button></p> :
      loadingEvents && <p className="turn-state" role="status">Loading the rest of this saved reply…</p>}
    {turn.corrections.map(item => <p key={item.id} className="correction-note">{item.action === 'withdraw' ? 'This turn was withdrawn.' : `Correction: ${item.replacement}`}</p>)}
    {turn.status === 'complete' && <div className="reply-support">
      {turn.on_active_branch !== false && !turn.corrections.length && people.length > 0 &&
        <div className="turn-actions"><SaveInsight turn={turn} conversationId={conversationId} workspace={workspace} people={people} /></div>}
      <details className="reference-disclosure reply-maintenance"><summary>Reply actions</summary>
        <div className="turn-actions">
          {showRevisionActions && <><button onClick={() => actions.current.onEdit(turn)}>Edit input</button>
            <button onClick={() => actions.current.onRegenerate(turn)}>Regenerate</button></>}
          <button onClick={() => actions.current.onBranch(turn.id)} disabled={activeHead === turn.id}>Use this branch</button>
          <button onClick={() => setCorrection(value => !value)}>Correct or withdraw</button>
        </div>
      </details>
    </div>}
    {correction && <div className="correction-form"><label>Correct the record<textarea value={replacement} onChange={e => setReplacement(e.target.value)} placeholder="State the correction without overwriting the original" /></label>
      <div><button disabled={!replacement.trim()} onClick={() => { actions.current.onCorrect(turn, 'correct', replacement); setCorrection(false); }}>Save correction</button>
        <button onClick={() => { actions.current.onCorrect(turn, 'withdraw', null); setCorrection(false); }}>Withdraw turn</button></div></div>}
  </article>;
});
