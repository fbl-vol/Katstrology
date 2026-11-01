import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from './api';

type Account = { client_id: string; email: string | null; plan_enabled: boolean; selected: boolean };
type Status = { available: boolean; connected: boolean; selected: string | null; accounts: Account[]; registration: 'local' | 'offline' };
const empty: Status = { available: false, connected: false, selected: null, accounts: [], registration: 'local' };

export function useProvider(workspace: Workspace | null) {
  const [status, setStatus] = useState<Status>(empty);
  const [error, setError] = useState('');
  const ownerRef = useRef(workspace?.owner || null);
  ownerRef.current = workspace?.owner || null;

  async function refresh() {
    if (!workspace) return;
    const owner = workspace.owner;
    try {
      const next = await api<Status>('siwc/status');
      if (ownerRef.current !== owner) return;
      setStatus(next); setError('');
    } catch {
      if (ownerRef.current === owner) {
        setStatus(empty);
        setError('Connection status could not be confirmed. Reopen Settings to check again.');
      }
    }
  }
  useEffect(() => {
    setStatus(empty); setError('');
    if (workspace) void refresh();
  }, [workspace?.owner]);

  async function choose(clientId: string) {
    if (!workspace) return;
    try {
      const owner = workspace.owner;
      const next = await api<Status>('siwc/select', workspace.csrf, 'POST', { client_id: clientId });
      if (ownerRef.current !== owner) return;
      setStatus(next);
      setError('');
    } catch { setError('The saved account was not selected.'); }
  }

  async function disconnect() {
    if (!workspace) return;
    try {
      const owner = workspace.owner;
      const result = await api<{ remote: string }>('siwc/disconnect', workspace.csrf, 'POST');
      if (ownerRef.current !== owner) return;
      await refresh();
      setError(result.remote === 'revoked' ? '' :
        'Local credentials cleared. Remote revocation was not confirmed; disconnect this app in ChatGPT settings.');
    } catch { setError('Disconnect did not complete. Check this account before retrying.'); }
  }

  return { status, error, refresh, choose, disconnect };
}

type Provider = ReturnType<typeof useProvider>;

function ProviderHelp() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return <span className="provider-help" onMouseEnter={() => setOpen(true)}
    onMouseLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setOpen(false); }}
    onFocus={() => setOpen(true)}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    onKeyDown={event => { if (event.key === 'Escape') { setOpen(false); button.current?.focus(); } }}>
    <button ref={button} type="button" aria-label="About ChatGPT plan connection" aria-expanded={open}
      aria-controls="provider-help-text" onClick={() => setOpen(true)}>ⓘ</button>
    {open && <span id="provider-help-text" className="provider-help-text" role="note">
      Your local workspace account and archive remain separate. ChatGPT sign-in does not import your ChatGPT history or provide an API key. Plan use requires a separate permission.
      <button type="button" onClick={() => setOpen(false)}>Close explanation</button>
    </span>}
  </span>;
}

export function ProviderSettings({ provider, workspace }: { provider: Provider; workspace: Workspace }) {
  useEffect(() => { void provider.refresh(); }, []);
  const selected = provider.status.accounts.find(account => account.selected);
  return <section className="settings-section" aria-labelledby="provider-title">
    <h2 id="provider-title">Model connection <ProviderHelp /></h2>
    {!provider.status.available ? <p className="provider-disabled">{provider.error ?
      'Connection status is unavailable. No chat message will be sent until it can be checked.' :
      provider.status.registration === 'offline' ?
      'Chat is not connected. This personal workspace needs an offline ChatGPT registration before chat can be used.' :
      'ChatGPT plan connection is disabled for this local build. No model or billing route will be substituted.'}</p> : <>
      {selected && <p>{provider.status.connected && <strong>Connected · </strong>}Selected account: {selected.email || selected.client_id} · {selected.plan_enabled ? 'Plan permission granted' : 'Identity only; plan use not permitted'}</p>}
      {provider.status.accounts.length > 1 && <label>Saved account<select value={provider.status.selected || ''} onChange={event => void provider.choose(event.target.value)}>
        {provider.status.accounts.map(account => <option key={account.client_id} value={account.client_id}>{account.email || account.client_id} · {account.plan_enabled ? 'plan enabled' : 'identity only'}</option>)}
      </select></label>}
      {provider.status.registration === 'offline' ?
        <p>{provider.status.connected ? 'This connection was set up privately on this server.' :
          'Connect the account offline on the dedicated computer before using chat. Browser sign-in is not available here.'}</p> :
      <form method="post" action="/auth/chatgpt/start" className="provider-form">
        <input type="hidden" name="csrf" value={workspace.csrf} />
        <input type="hidden" name="client_id" value={provider.status.selected || ''} />
        <button className={provider.status.connected ? 'quiet-action' : 'primary'} type="submit">{provider.status.connected ? 'Reconnect ChatGPT account' : 'Connect ChatGPT plan'}</button>
        {!provider.status.connected && <small>Sign-in does not import your ChatGPT history or send a message.</small>}
      </form>}
      {selected && <button className="quiet-action" onClick={() => void provider.disconnect()}>Disconnect ChatGPT plan</button>}
      <p><a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer noopener">Manage usage in ChatGPT settings</a></p>
    </>}
    {provider.error && <p className="error" role="alert">{provider.error}</p>}
  </section>;
}
