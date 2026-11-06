import { useRef, useState, type RefObject } from 'react';
import { api, type Workspace } from '../../api';
import { useArchiveChat, type SelectedResult } from './archive';
import type { Conversation, Selection } from '../../conversation';
import type { Turn, TurnActions } from '../../turns';
import type { useWorkspaceNavigation } from '../../app/workspace-navigation';
import type { useConversationDiscovery } from './conversation-discovery';

type Edit = { parent: string; replaces: string; kind: 'edit' | 'regenerate' };
type Navigation = ReturnType<typeof useWorkspaceNavigation>;
type Discovery = ReturnType<typeof useConversationDiscovery>;

/** Coordinates drafts and archived conversation actions, never transport or ACK identity. */
export function useConversationWorkflow({ workspace, navigation, discovery, connected, setNotice, messageInput }: {
  workspace: Workspace | null; navigation: Navigation; discovery: Discovery; connected: boolean;
  setNotice: (notice: string) => void; messageInput: RefObject<HTMLTextAreaElement | null>;
}) {
  const { conversation, person, skyOpen, chartHub, settingsOpen } = navigation;
  const [selection, setSelection] = useState<Selection[]>([]);
  const [message, setMessage] = useState('');
  const [discuss, setDiscuss] = useState<{ selected: SelectedResult; label: string } | null>(null);
  const [editing, setEditing] = useState<Edit | null>(null);
  const pendingConversationId = useRef('');
  const submissionInFlight = useRef(false);
  const submissionVersion = useRef(0);
  const [preparingSend, setPreparingSend] = useState(false);
  const archive = useArchiveChat(workspace, discovery.onTerminal, {
    conversationId: conversation?.id || null,
    visible: !person && !skyOpen && !chartHub && !settingsOpen,
    navigation: navigation.version,
  });
  const headNotLoaded = !!conversation?.active_head &&
    !archive.turns.some(turn => turn.id === conversation.active_head);

  function invalidateSubmission() {
    submissionVersion.current++;
    submissionInFlight.current = false;
    setPreparingSend(false);
  }

  function resetDraft() {
    setSelection([]); setMessage(''); setDiscuss(null); setEditing(null);
    pendingConversationId.current = '';
  }

  function allConversations() {
    navigation.allConversations(); setDiscuss(null);
    pendingConversationId.current = '';
    discovery.clearSearch();
    if (!navigation.filterPersonId) void discovery.loadThreads(0, '');
  }

  function newChat(personIds?: string | string[]) {
    navigation.newConversation();
    resetDraft();
    setSelection((personIds ? (Array.isArray(personIds) ? personIds : [personIds]) : []).map(person_id => ({ person_id })));
  }

  async function openConversation(id: string) {
    const version = navigation.beginConversation();
    try {
      setNotice('');
      const thread = await api<Conversation>(`conversations/${id}`);
      if (!navigation.isCurrent(version)) return;
      await archive.open(id);
      if (!navigation.isCurrent(version)) return;
      invalidateSubmission();
      let selected: Selection[] = thread.people.map(item => ({ person_id: item.person_id || item.id! }));
      if (thread.active_head) {
        const active = await api<Turn>(`conversations/${id}/turns/${thread.active_head}`);
        selected = active.selected_people.map(item => ({ person_id: item.person_id }));
      }
      if (!navigation.isCurrent(version)) return;
      navigation.showConversation(thread); setSelection(selected); setDiscuss(null); setEditing(null);
    } catch { if (navigation.isCurrent(version)) setNotice('Conversation could not be opened. Your current draft remains here.'); }
  }

  function discussSavedResult(personId: string, selected: SelectedResult, label: string) {
    if (archive.hasPending) {
      setNotice('Finish or retry the current message before choosing another result.'); return;
    }
    navigation.discussResult(); setSelection([{ person_id: personId }]);
    setDiscuss({ selected, label }); setEditing(null); pendingConversationId.current = '';
    requestAnimationFrame(() => messageInput.current?.focus());
  }

  async function startConversation(selected: Selection[]): Promise<Conversation | null> {
    if (!workspace) return null;
    const version = navigation.beginConversation();
    if (!pendingConversationId.current) pendingConversationId.current = 'thread-' + crypto.randomUUID();
    try {
      const result = await api<Conversation>('conversations', workspace.csrf, 'POST', {
        id: pendingConversationId.current, title: 'New conversation', people: selected.map(item => item.person_id),
      });
      if (!navigation.isCurrent(version)) return null;
      navigation.showConversation(result); setNotice(''); pendingConversationId.current = '';
      void discovery.loadThreads(0, ''); // Sidebar failure cannot make a send ambiguous.
      return result;
    } catch {
      if (navigation.isCurrent(version))
        archive.failPending('This conversation was not confirmed. Retry this message; your other draft is unchanged.');
      return null;
    }
  }

  async function sendText(submittedMessage: string, revision?: Edit & { selected: Selection[] },
    clearComposer = true): Promise<boolean> {
    if (archive.hasPending || submissionInFlight.current || !submittedMessage.trim() || archive.busy || headNotLoaded) return false;
    if (new TextEncoder().encode(submittedMessage).length > 64 * 1024) {
      setNotice('This message is longer than 64 KiB. Shorten it before sending; your draft is still here.');
      return false;
    }
    submissionInFlight.current = true; setPreparingSend(true);
    const submission = ++submissionVersion.current;
    if (!conversation && !pendingConversationId.current)
      pendingConversationId.current = 'thread-' + crypto.randomUUID();
    const selected = (revision?.selected || selection).map(item => ({ ...item }));
    const queued = archive.queue(conversation?.id || pendingConversationId.current, submittedMessage,
      selected, revision?.parent || editing?.parent || '@active',
      revision?.kind || editing?.kind || 'normal', revision?.replaces || editing?.replaces || null,
      revision || editing ? undefined : discuss?.selected);
    if (!queued) { submissionInFlight.current = false; setPreparingSend(false); return false; }
    setDiscuss(null); // Immutable pending payload retains the selection on retry.
    if (clearComposer) {
      setMessage(current => current === submittedMessage ? '' : current);
      setEditing(null); messageInput.current?.focus();
    }
    try {
      if (!connected) archive.failPending('ChatGPT is not connected yet. Connect your plan, then retry this message.', true);
      else {
        const thread = conversation || await startConversation(selected);
        if (thread) { await archive.retry(); void discovery.loadThreads(0, ''); }
      }
      return true; // Accepted into local projection, not claimed saved.
    } finally {
      if (submission === submissionVersion.current) {
        submissionInFlight.current = false; setPreparingSend(false);
      }
    }
  }

  async function retryPending() {
    const item = archive.localPending;
    if (!item || submissionInFlight.current || archive.busy) return;
    if (item.failure?.reconnect && !connected) {
      archive.failPending('ChatGPT is not connected yet. Connect your plan, then retry this message.', true); return;
    }
    submissionInFlight.current = true; setPreparingSend(true);
    const submission = ++submissionVersion.current;
    try {
      if (!conversation && pendingConversationId.current !== item.conversationId) return;
      const thread = conversation || await startConversation(item.payload.selected_people);
      if (thread?.id === item.conversationId) { await archive.retry(); void discovery.loadThreads(0, ''); }
    } finally {
      if (submission === submissionVersion.current) {
        submissionInFlight.current = false; setPreparingSend(false);
      }
    }
  }

  async function changeBranch(head: string) {
    if (!workspace || !conversation || archive.busy) return;
    const id = conversation.id, route = navigation.version.current;
    try {
      await api(`conversations/${id}/branch`, workspace.csrf, 'POST', { head });
      if (navigation.isCurrent(route)) await openConversation(id);
    } catch { if (navigation.isCurrent(route)) setNotice('Branch selection was not saved. The original branch is unchanged.'); }
  }

  async function correctTurn(turn: Turn, action: 'correct' | 'withdraw', replacement: string | null) {
    if (!workspace || !conversation || archive.busy) return;
    const id = conversation.id, route = navigation.version.current;
    try {
      await api(`conversations/${id}/corrections`, workspace.csrf, 'POST', {
        id: 'correction-' + crypto.randomUUID(), source_turn: turn.id, action, replacement,
      });
      if (navigation.isCurrent(route)) await openConversation(id);
    } catch { if (navigation.isCurrent(route)) setNotice('Correction was not confirmed. Check the original turn before retrying.'); }
  }

  function editTurn(turn: Turn) {
    if (archive.busy) return;
    if (headNotLoaded) { setNotice('Load the current saved message before editing this conversation.'); return; }
    setMessage(String(turn.events.find(item => item.kind === 'user')?.payload.content || ''));
    setSelection(turn.selected_people.map(item => ({ person_id: item.person_id })));
    setEditing({ parent: turn.parent_id || '@root', replaces: turn.id, kind: 'edit' });
    messageInput.current?.focus();
  }

  function retryFailedTurn(turn: Turn) {
    if (!conversation || archive.busy || archive.hasPending || submissionInFlight.current) return;
    if (turn.selected_people.some(item => item.attachment_id)) {
      setNotice('Reselect the file and give fresh consent before trying again.'); return;
    }
    const text = String(turn.events.find(item => item.kind === 'user')?.payload.content || '');
    if (!text) { setNotice('Load the saved input first, then try again.'); return; }
    void sendText(text, undefined, false); // A new paid turn, not an archived-failure resend.
  }

  async function regenerateTurn(turn: Turn) {
    if (!conversation || archive.busy || headNotLoaded) return;
    const text = String(turn.events.find(item => item.kind === 'user')?.payload.content || '');
    if (!text) { setNotice('Load the original input event first.'); return; }
    await archive.submit(conversation.id, text,
      turn.selected_people.map(item => ({ person_id: item.person_id })),
      turn.parent_id || '@root', 'regenerate', turn.id);
  }

  async function renameConversation() {
    if (!workspace || !conversation || archive.busy) return;
    const title = window.prompt('Conversation title', conversation.title);
    if (title === null) return;
    const id = conversation.id, route = navigation.version.current;
    try {
      const updated = await api<Conversation>(`conversations/${id}`, workspace.csrf, 'PATCH', { title });
      if (!navigation.isCurrent(route)) return;
      navigation.updateConversation(current => current?.id === id ? updated : current);
      await discovery.loadThreads(0);
    } catch { if (navigation.isCurrent(route)) setNotice('Title was not saved. Use 1–80 characters and retry.'); }
  }

  async function deleteConversation() {
    if (!workspace || !conversation || archive.busy) return;
    if (!window.confirm('Delete this archived conversation and its owned files? Dependent conversations must be removed first. Existing exports cannot be recalled.')) return;
    const id = conversation.id, route = navigation.version.current;
    try {
      await api(`conversations/${id}`, workspace.csrf, 'DELETE');
      if (!navigation.isCurrent(route)) return;
      navigation.newConversation(); setMessage(''); setEditing(null);
      await discovery.loadThreads(0);
    } catch { if (navigation.isCurrent(route)) setNotice('Deletion was blocked or unavailable. Dependent conversations and original records remain.'); }
  }

  async function exportConversation() {
    if (!workspace || !conversation) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(conversation.id)}/export`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-Kat-CSRF': workspace.csrf },
      });
      if (!response.ok) throw new Error('Export failed');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = 'kat-conversation.jsonl';
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch { setNotice('Export was not available; the original archive remains in the local workspace.'); }
  }

  function stopResponse() {
    const turn = archive.turns.find(item => item.status === 'open');
    if (workspace && conversation && turn)
      void api(`conversations/${conversation.id}/turns/${turn.id}/cancel`, workspace.csrf, 'POST')
        .catch(() => setNotice('Cancellation could not be confirmed. Check the archived status.'));
  }

  const latestTurnActions: TurnActions = {
    onBranch: head => void changeBranch(head), onEdit: editTurn,
    onRegenerate: turn => void regenerateTurn(turn), onRetryFailed: retryFailedTurn,
    onCorrect: (turn, action, replacement) => void correctTurn(turn, action, replacement),
    onRetryEvents: turn => { if (conversation) archive.retryEvents(conversation.id, turn); },
  };
  const turnActions = useRef(latestTurnActions);
  turnActions.current = latestTurnActions;

  return { archive, message, setMessage, selection, setSelection, discuss, setDiscuss, editing,
    cancelEdit: () => { setEditing(null); setMessage(''); }, pendingConversationId, preparingSend,
    headNotLoaded, turnActions, invalidateSubmission, resetDraft, allConversations, newChat,
    openConversation, discussSavedResult, sendText, retryPending, renameConversation,
    deleteConversation, exportConversation, stopResponse };
}
