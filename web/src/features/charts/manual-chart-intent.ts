import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../../api';

/** The app-observed UTC date, not the browser's unverified local clock or location. */
export function useApplicationUtcDate() {
  const [today, setToday] = useState('');
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let current = true;
    void api<{ instant_utc: string }>('clock?zone=UTC').then(snapshot => {
      if (current) setToday(snapshot.instant_utc.slice(0, 10));
    }).catch(() => { if (current) setUnavailable(true); });
    return () => { current = false; };
  }, []);
  return { today, unavailable };
}

export function utcDays(date: string, days: number) {
  if (!date) return '';
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400_000).toISOString().slice(0, 10);
}

/** Focus once per deliberate open/calculate, never on a background refresh or stream. */
export function useManualChartIntent(result: unknown, focusOnMount = true) {
  const viewHeading = useRef<HTMLHeadingElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const revealRequested = useRef(false);
  useEffect(() => { if (focusOnMount) viewHeading.current?.focus(); }, [focusOnMount]);
  useLayoutEffect(() => {
    if (!result || !revealRequested.current || !resultHeading.current) return;
    revealRequested.current = false;
    resultHeading.current.scrollIntoView({ block: 'start', behavior: 'instant' });
    resultHeading.current.focus({ preventScroll: true });
  }, [result]);
  return { viewHeading, resultHeading, revealResult: () => { revealRequested.current = true; } };
}
