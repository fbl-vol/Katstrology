import { useRef, useState } from 'react';
import { api, ApiError, type Workspace } from './api';
import { useManualChartIntent } from './manual-chart-intent';
import { TransitResult, type TransitResultData } from './transit-result';
import type { Person } from './people';

export function TransitView({ workspace, people, initialPersonId, onClose, returnLabel = 'Return to conversation' }: {
  workspace: Workspace; people: Person[]; initialPersonId?: string; onClose: () => void;
  returnLabel?: string;
}) {
  const [mode, setMode] = useState<'sky' | 'natal_transits'>('sky');
  const [date, setDate] = useState('');
  const [clock, setClock] = useState('');
  const [occurrence, setOccurrence] = useState('unspecified');
  const [showOccurrence, setShowOccurrence] = useState(false);
  const [personId, setPersonId] = useState(initialPersonId || '');
  const [result, setResult] = useState<TransitResultData | null>(null);
  const intent = useManualChartIntent(result);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const request = useRef(0);

  function changed() {
    request.current++;
    setResult(null); setError(''); setBusy(false);
    setShowOccurrence(false); setOccurrence('unspecified');
  }

  async function useNow() {
    const version = ++request.current;
    setResult(null); setError(''); setBusy(true);
    try {
      const anchor = await api<{ reporting: { date: string; time: string; occurrence: string } }>(
        `clock?zone=${encodeURIComponent(workspace.product.reporting_zone)}`);
      if (version !== request.current) return;
      setDate(anchor.reporting.date); setClock(anchor.reporting.time);
      setOccurrence(anchor.reporting.occurrence);
      setShowOccurrence(anchor.reporting.occurrence !== 'unspecified');
    } catch {
      if (version === request.current) setError('Application time could not be read. Choose a date and Copenhagen time manually; no chart was calculated.');
    } finally { if (version === request.current) setBusy(false); }
  }

  async function calculate(event: React.FormEvent) {
    event.preventDefault();
    const version = ++request.current;
    setResult(null); setError(''); setBusy(true); intent.revealResult();
    try {
      const params = new URLSearchParams({ date, time: clock,
        zone: workspace.product.reporting_zone, occurrence, mode });
      if (mode === 'natal_transits') params.set('person_id', personId);
      const output = await api<TransitResultData>(`transit-view?${params.toString()}`);
      if (version !== request.current) return;
      if (output.status === 'supported') setResult(output);
      else if (output.status === 'no_active_natal')
        setError('This person has no active generated natal. Create one first, or choose Sky only. No historical chart was substituted.');
      else if (output.status === 'unsupported_stale_birth_source')
        setError('The current natal has a superseded birth source. Update the person’s chart before comparing transits.');
      else setError('This natal has no supported exact-time positions. Use Sky only or update the birth details; no time was invented.');
    } catch (cause) {
      if (version !== request.current) return;
      const code = cause instanceof ApiError ? cause.code : '';
      if (code === 'choose_dst_occurrence') {
        setShowOccurrence(true);
        setError('This Copenhagen hour occurred twice. Choose earlier or later below; no time was guessed.');
      } else if (code === 'nonexistent_local_time') {
        setError('This Copenhagen clock time did not occur on that date. Correct the time; no result was calculated.');
      } else setError('This view could not be calculated. Check the date (1900–2099) and clock time. No prior result is shown.');
    } finally { if (version === request.current) setBusy(false); }
  }

  return <section className="transit-page" aria-label="Sky at a date">
    <div className="transit-heading"><div><span className="eyebrow">SKY AND CHART</span><h1 ref={intent.viewHeading} tabIndex={-1}>Sky at a date</h1>
      <p>Choose a date and Copenhagen time.</p></div>
      <button type="button" onClick={onClose}>{returnLabel}</button></div>
    <form className="transit-controls" onSubmit={calculate}>
      <fieldset><legend>View</legend><label><input type="radio" name="transit-mode" checked={mode === 'sky'} onChange={() => { changed(); setMode('sky'); }} /> Sky only</label>
        <label><input type="radio" name="transit-mode" checked={mode === 'natal_transits'} onChange={() => { changed(); setMode('natal_transits'); }} /> Natal + transits</label></fieldset>
      <div className="transit-fields"><label>Date<input type="date" min="1900-01-01" max="2099-12-31" value={date} required onChange={event => { changed(); setDate(event.target.value); }} /></label>
        <label>Copenhagen time<input type="time" step="1" value={clock} required onChange={event => { changed(); setClock(event.target.value); }} /></label></div>
      {showOccurrence && <label className="transit-occurrence">Repeated Copenhagen hour
        <select value={occurrence} onChange={event => { request.current++; setResult(null); setError(''); setOccurrence(event.target.value); }}>
          <option value="unspecified">Choose occurrence</option><option value="earlier">Earlier occurrence</option><option value="later">Later occurrence</option>
        </select></label>}
      {mode === 'natal_transits' && <div className="transit-fields"><label>Person<select value={personId} required onChange={event => { changed(); setPersonId(event.target.value); }}>
        <option value="">Choose person</option>{people.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <p className="natal-qualification">Uses this person’s current generated natal at calculation time. Earlier chart versions stay in History, not in this view.</p></div>}
      <div className="transit-control-actions"><button type="button" disabled={busy} onClick={() => void useNow()}>Use Now / Today</button>
        <button type="submit" className="primary" disabled={busy}>{busy ? 'Working…' : 'Show calculated view'}</button></div>
      <p className="transit-now-note">Now fills the current Copenhagen date and time. Show calculates without sending a message.</p>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div aria-live="polite"><TransitResult result={result} headingRef={intent.resultHeading} /></div>}
  </section>;
}
