import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../api';
import type { Conversation } from '../../conversation';
import type { useWorkspaceNavigation } from '../../app/workspace-navigation';

type ThreadPage = { conversations: Conversation[]; next_offset: number | null; search_pending: number };
type Navigation = ReturnType<typeof useWorkspaceNavigation>;

/** Owns sidebar queries and title refreshes; neither can gate or retry a send. */
export function useConversationDiscovery(workspace: Workspace | null, navigation: Navigation) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searched, setSearched] = useState('');
  const [nextConversationOffset, setNextConversationOffset] = useState<number | null>(null);
  const [listStatus, setListStatus] = useState('');
  const requestVersion = useRef(0);
  const browseIntent = useRef({ query: '', offset: 0 });
  const identity = `${workspace?.owner || ''}:${workspace?.csrf || ''}`;
  const context = useRef({ identity, filter: navigation.filterPersonId });
  context.current = { identity, filter: navigation.filterPersonId };

  const requestThreads = useCallback(async (offset: number, text: string) => {
    if (!workspace) return;
    const version = ++requestVersion.current;
    const filter = navigation.filterPersonId;
    const current = () => version === requestVersion.current &&
      context.current.identity === identity && context.current.filter === filter;
    setListStatus('Loading conversations…');
    try {
      const result = text ? await api<ThreadPage>('conversations/search', workspace.csrf, 'POST',
        { query: text, person: filter, offset }) :
        await api<ThreadPage>(`conversations${filter ? `?person=${encodeURIComponent(filter)}&offset=${offset}` : `?offset=${offset}`}`);
      if (!current()) return;
      setConversations(old => offset ? [...old, ...result.conversations] : result.conversations);
      setNextConversationOffset(result.next_offset);
      setListStatus(result.search_pending ? 'Search indexing is pending; results may be incomplete.' : '');
    } catch {
      if (current()) setListStatus('Conversations unavailable. Retry the search.');
    }
  }, [identity, navigation.filterPersonId]);

  function loadThreads(offset = 0, text = browseIntent.current.query) {
    browseIntent.current = { query: text, offset };
    return requestThreads(offset, text);
  }

  /** Capture before async work; a newer browsing decision wins over its refresh. */
  function captureRefresh() {
    const intent = browseIntent.current;
    const filter = navigation.filterPersonId;
    return () => {
      if (browseIntent.current !== intent || intent.offset !== 0 ||
          context.current.identity !== identity || context.current.filter !== filter) return;
      // Do not collapse loaded pages or use an unsubmitted search-box draft.
      void requestThreads(0, intent.query);
    };
  }

  function reset() {
    setConversations([]); setNextConversationOffset(null); setListStatus('');
    clearSearch();
  }

  function clearSearch() {
    browseIntent.current = { query: '', offset: 0 };
    requestVersion.current++;
    setSearched(''); setSearchQuery('');
  }
  function search() { setSearched(searchQuery); void loadThreads(0, searchQuery); }

  useEffect(() => {
    reset();
    return () => {
      requestVersion.current++;
      browseIntent.current = { query: '', offset: 0 };
    };
  }, [identity]);

  useEffect(() => {
    if (workspace) void loadThreads(0, '');
  }, [identity, navigation.filterPersonId]);

  async function refreshTitleAfterCompletion(id: string) {
    const version = navigation.version.current;
    const refresh = captureRefresh();
    const current = () => navigation.isCurrent(version) && context.current.identity === identity;
    for (let attempt = 0; attempt < 8; attempt++) {
      await new Promise(resolve => window.setTimeout(resolve, 1500));
      if (!current()) return;
      try {
        const updated = await api<Conversation>(`conversations/${id}`);
        if (!current()) return;
        navigation.updateConversation(thread => thread?.id === id ? updated : thread);
        if (updated.title_status === 'generated') {
          refresh();
          return;
        }
        if (updated.title_status !== 'waiting' && updated.title_status !== 'pending') return;
      } catch { return; }
    }
  }

  function onTerminal(id: string, status: string) {
    const version = navigation.version.current;
    void api<Conversation>(`conversations/${id}`).then(updated => {
      if (navigation.isCurrent(version) && context.current.identity === identity)
        navigation.updateConversation(thread => thread?.id === id ? updated : thread);
    }).catch(() => {});
    captureRefresh()();
    if (status === 'complete') void refreshTitleAfterCompletion(id);
  }

  return { conversations, searchQuery, setSearchQuery, searched, nextConversationOffset,
    listStatus, loadThreads, captureRefresh, search, clearSearch, reset, onTerminal };
}
