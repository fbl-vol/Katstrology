import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Workspace } from '../../shared/api';

type Result = { status: string; id?: string; source_status?: string };
type History = { id: string };
type CalculationOptions<R extends Result, H extends History> = {
  prefix: string;
  invalid: string;
  uncertain: string;
  unavailable: (status: string) => string;
  firstRow?: (result: R, id: string) => H;
  reloadHistory?: { error: string };
  displayWithoutSaving?: string[];
  onResult?: (result: R) => void;
};

/** Own the manual result's identity, uncertain-write retry, stale reads and save/open state.
 * Forms still own numerical inputs and specialist result meaning/rendering. */
export function useManualResultLifecycle<R extends Result, H extends History>(workspace: Workspace) {
  const [result, setResult] = useState<R | null>(null);
  const [history, setHistory] = useState<H[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const historyGeneration = useRef(0);
  const request = useRef<{ key: string; id: string } | null>(null);
  useEffect(() => () => { generation.current++; historyGeneration.current++; }, []);

  function change() {
    generation.current++;
    request.current = null;
    setResult(null); setError(''); setBusy(false);
  }

  async function loadHistory(personId: string, technique: string, failure: string) {
    if (!personId) return;
    const version = ++historyGeneration.current;
    try {
      const page = await api<{ results: H[] }>(
        `advanced-results?person_id=${encodeURIComponent(personId)}&technique=${technique}`);
      if (version === historyGeneration.current) setHistory(page.results);
    } catch { if (version === historyGeneration.current) setError(failure); }
  }

  function choosePerson(personId: string, technique: string, historyFailure: string) {
    change(); historyGeneration.current++; setHistory([]);
    void loadHistory(personId, technique, historyFailure);
  }

  async function calculate(personId: string, technique: string, parameters: object,
                           options: CalculationOptions<R, H>) {
    const key = JSON.stringify({ personId, technique, parameters });
    if (request.current?.key !== key)
      request.current = { key, id: `${options.prefix}-${crypto.randomUUID()}` };
    const id = request.current.id;
    const version = ++generation.current;
    setResult(null); setBusy(true); setError('');
    try {
      const saved = await api<R>('advanced-results', workspace.csrf, 'POST', {
        id, person_id: personId, technique, parameters,
      });
      if (version !== generation.current) return;
      if (saved.status === 'supported') {
        setResult(saved);
        options.onResult?.(saved);
        // A pending history read started before this write must not replace it.
        historyGeneration.current++;
        if (options.firstRow) setHistory(rows => rows.some(row => row.id === id) ? rows :
          [options.firstRow!(saved, id), ...rows]);
        if (options.reloadHistory) void loadHistory(personId, technique, options.reloadHistory.error);
      } else {
        request.current = null; // An acknowledged, unsaved result is not a lost ACK.
        if (options.displayWithoutSaving?.includes(saved.status)) {
          setResult(saved); options.onResult?.(saved);
        } else setError(options.unavailable(saved.status));
      }
    } catch (cause) {
      if (version !== generation.current) return;
      if (cause instanceof ApiError && cause.status === 400) {
        request.current = null; // The server definitively rejected this identity.
        setError(options.invalid);
      } else setError(options.uncertain); // Retry the same input with the same identity.
    } finally { if (version === generation.current) setBusy(false); }
  }

  async function openSaved(id: string, failure: string, onOpened?: (saved: R) => void) {
    const version = ++generation.current;
    setResult(null); setError(''); setBusy(false);
    try {
      const saved = await api<{ result: R; source_status: string }>(
        `advanced-results/${encodeURIComponent(id)}`);
      if (version !== generation.current) return;
      const opened = { ...saved.result, id, source_status: saved.source_status };
      setResult(opened); onOpened?.(opened);
    } catch { if (version === generation.current) setError(failure); }
  }

  return { result, history, busy, error, setError, change, choosePerson,
    loadHistory, calculate, openSaved };
}
