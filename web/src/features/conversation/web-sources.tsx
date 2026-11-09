import { safeLink } from './assistant-markdown';
import type { ArchiveEvent } from './turns';
import './web-sources.css';

type Source = { url: string; title: string; publication_date?: string | null; retrieved_at?: string };
const webTools = new Set(['web_search', 'fetch_web_page', 'read_web_content']);

export function webActivity(events: ArchiveEvent[]): string | null {
  const pending = new Map<string, string>();
  for (const event of events) {
    const name = String(event.payload.name || '');
    const id = String(event.payload.id || '');
    if (event.kind === 'tool_call' && webTools.has(name)) pending.set(id, name);
    if (event.kind === 'tool_result') pending.delete(id);
  }
  const name = [...pending.values()].at(-1);
  return name ? name === 'web_search' ? 'Searching public sources…' : 'Reading public sources…' : null;
}

function revealKeyboardSource(target: EventTarget | null) {
  if (!(target instanceof HTMLElement) || !target.matches(':focus-visible')) return;
  // Native focus scrolling does not account for the sticky composer. Wait for
  // that scrolling, then reveal only the deliberately focused control. No
  // streaming/resize observer may pull a reader back after they scroll away.
  requestAnimationFrame(() => {
    if (document.activeElement !== target) return;
    const main = target.closest('.chat-scroll-page');
    const dock = main?.querySelector('.composer-wrap');
    const top = (main?.querySelector('.header')?.getBoundingClientRect().bottom || 0) + 8;
    const bottom = Math.min(window.innerHeight, dock?.getBoundingClientRect().top ?? window.innerHeight) - 8;
    const rect = target.getBoundingClientRect();
    const delta = rect.top < top ? rect.top - top : Math.max(0, rect.bottom - bottom);
    if (delta) window.scrollBy({ top: delta, behavior: 'instant' });
  });
}

export function WebSources({ events }: { events: ArchiveEvent[] }) {
  const sources = new Map<string, Source>();
  let used = false, limited = false;
  for (const event of events) {
    if (event.kind !== 'tool_result' || !webTools.has(String(event.payload.name))) continue;
    used = true;
    const result = event.payload.result as Record<string, unknown> | undefined;
    if (!result || result.status !== 'ok' || event.payload.model_projection_status === 'limit') limited = true;
    if (!Array.isArray(result?.sources)) continue;
    for (const entry of result.sources) {
      if (!entry || typeof entry.url !== 'string') continue;
      const url = safeLink(entry.url);
      if (url) sources.set(url, { url, title: typeof entry.title === 'string' ? entry.title : new URL(url).hostname,
        publication_date: typeof entry.publication_date === 'string' ? entry.publication_date : null,
        retrieved_at: typeof entry.retrieved_at === 'string' ? entry.retrieved_at :
          typeof result.retrieved_at === 'string' ? result.retrieved_at : undefined });
    }
  }
  if (!used) return null;
  return <details className="web-sources" onFocus={event => revealKeyboardSource(event.target)}
    onToggle={event => revealKeyboardSource(event.currentTarget.querySelector(':focus-visible'))}>
    <summary>Public sources{limited ? ' · Limited results' : ''}</summary>
    {limited && <p>Some public information was unavailable or incomplete.</p>}
    {sources.size > 0 ? <ul>{[...sources.values()].map(source => <li key={source.url}>
      <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
      <small>{source.publication_date ? `Published ${source.publication_date}` : 'Publication date unknown'}
        {source.retrieved_at && ` · Retrieved ${source.retrieved_at.slice(0, 10)}`}</small>
    </li>)}</ul> : <p>No public source links were retained for this read.</p>}
  </details>;
}
