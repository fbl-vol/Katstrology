import { useEffect, useRef, useState } from 'react';
import { api, type Workspace } from '../../api';

type Account = { client_id: string; email: string | null; plan_enabled: boolean; selected: boolean };
type Status = { available: boolean; connected: boolean; selected: string | null; accounts: Account[];
  registration: 'local' | 'offline'; phase?: 'not_connected' | 'ready' | 'refresh_required' | 'identity_only' | 'reauthorization_required' };
const empty: Status = { available: false, connected: false, selected: null, accounts: [], registration: 'local' };

export function useProvider(workspace: Workspace | null) {
  const [status, setStatus] = useState<Status>(empty);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [checkMessage, setCheckMessage] = useState('');
  const ownerRef = useRef(workspace?.owner || null);
  ownerRef.current = workspace?.owner || null;

  async function refresh(): Promise<boolean> {
    if (!workspace) return false;
    const owner = workspace.owner;
    try {
      const next = await api<Status>('siwc/status');
      if (ownerRef.current !== owner) return false;
      setStatus(next); setError('');
      return true;
    } catch {
      if (ownerRef.current === owner) {
        setStatus(empty);
        setError('Connection status could not be confirmed. Reopen Settings to check again.');
      }
      return false;
    }
  }
  useEffect(() => {
    setStatus(empty); setError(''); setChecking(false); setCheckMessage('');
    if (workspace) void refresh();
  }, [workspace?.owner]);

  async function choose(clientId: string) {
    if (!workspace) return;
    try {
      const owner = workspace.owner;
      const next = await api<Status>('siwc/select', workspace.csrf, 'POST', { client_id: clientId });
      if (ownerRef.current !== owner) return;
      setStatus(next);
      setError(''); setCheckMessage('');
    } catch { setError('The saved account was not selected.'); }
  }

  async function disconnect() {
    if (!workspace) return;
    try {
      const owner = workspace.owner;
      const result = await api<{ remote: string }>('siwc/disconnect', workspace.csrf, 'POST');
      if (ownerRef.current !== owner) return;
      await refresh();
      setCheckMessage('');
      setError(result.remote === 'revoked' ? '' :
        'Local credentials cleared. Remote revocation was not confirmed; disconnect this app in ChatGPT settings.');
    } catch { setError('Disconnect did not complete. Check this account before retrying.'); }
  }

  async function checkConnection() {
    if (!workspace || checking) return;
    const owner = workspace.owner;
    setChecking(true); setCheckMessage('');
    try {
      const result = await api<{ chat_available: boolean }>('siwc/models');
      if (ownerRef.current !== owner) return;
      const statusConfirmed = await refresh();
      if (ownerRef.current !== owner) return;
      setCheckMessage(!statusConfirmed ?
        'The model responded, but connection status could not be confirmed. Check again before sending.' :
        result.chat_available ?
          'The chat model is available to this account now. Sending a message is a separate request and can still fail.' :
          'The account responded, but Kat’s chat model is not available. No message was sent.');
    } catch {
      if (ownerRef.current === owner) {
        await refresh();
        setCheckMessage('The chat model could not be checked. No message was sent. If authorization needs renewing, follow the offline recovery steps.');
      }
    } finally {
      if (ownerRef.current === owner) setChecking(false);
    }
  }

  return { status, error, refresh, choose, disconnect, checkConnection, checking, checkMessage };
}

type Provider = ReturnType<typeof useProvider>;

function ProviderHelp() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return <span className="provider-help" onMouseEnter={() => setOpen(true)}
    onMouseLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setOpen(false); }}
    onFocus={() => setOpen(true)}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    onKeyDown={event => { if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false); button.current?.focus();
    } }}>
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
  return <section className="settings-connection" aria-label="Model connection">
    <h2>ChatGPT <ProviderHelp /></h2>
    {!provider.status.available ? <p className="provider-disabled">{provider.error ?
      'Connection status is unavailable. No chat message will be sent until it can be checked.' :
      provider.status.registration === 'offline' ?
      'Chat is unavailable because the server connection is disabled. Enabling it is a separate private setup step.' :
      'ChatGPT plan connection is disabled for this local build. No model or billing route will be substituted.'}</p> : <>
      {selected && <p>{provider.status.connected && <strong>{provider.status.registration === 'offline' ? 'Account saved' : 'Connected'} · </strong>}Selected account: {selected.email || selected.client_id} · {selected.plan_enabled ?
        provider.status.registration === 'offline' ? 'Saved plan permission; checked when chat is used' : 'Plan permission granted' :
        provider.status.phase === 'reauthorization_required' ? 'Authorization needs renewing' :
        'Identity only; plan use not permitted'}</p>}
      {provider.status.accounts.length > 1 && <label>Saved account<select value={provider.status.selected || ''} disabled={provider.checking} onChange={event => void provider.choose(event.target.value)}>
        {provider.status.accounts.map(account => <option key={account.client_id} value={account.client_id}>{account.email || account.client_id} · {account.plan_enabled ? 'plan enabled' : 'identity only'}</option>)}
      </select></label>}
      {provider.status.registration === 'offline' ? <div aria-live="polite">
        {selected && provider.status.phase === 'refresh_required' ?
          <p>Registration transferred. This server still needs to refresh its token before chat can work. Choose Check chat connection to attempt that check; a saved permission alone does not confirm plan eligibility.</p> :
          selected && provider.status.phase === 'reauthorization_required' ?
          <p>ChatGPT authorization needs renewing. Reconnect on the dedicated computer, then complete a new private transfer. The server cannot accept browser sign-in or silently overwrite this registration.</p> :
          selected && provider.status.phase === 'identity_only' ?
          <p>ChatGPT sign-in succeeded without plan permission. Reconnect on the dedicated computer and grant ChatGPT plan use before transferring a registration for chat.</p> :
          selected && provider.status.connected ?
          <p>This connection was set up privately on this server. Model availability is checked when chat is used.</p> :
          <div className="connection-setup"><p>Connect the account offline on a dedicated computer before using chat. Your Kat login and ChatGPT permission are separate; signing in on the ChatGPT website or opening Manage usage does not connect Kat.</p>
            <details><summary>Show offline setup steps</summary>
              <ol><li>Run Kat locally on that computer and choose Connect ChatGPT plan. Its sign-in returns to that computer’s 127.0.0.1 callback, not this website.</li>
                <li>After granting plan use, securely transfer only the selected encrypted registration to this server using the private deployment setup procedure.</li>
                <li>Open Settings again to check the saved registration, then choose Check chat connection. Do not send a message until the connection is ready.</li></ol>
            </details>
            <p>No ChatGPT credentials are entered or uploaded on this website.</p></div>}
      </div> :
      <form method="post" action="/auth/chatgpt/start" className="provider-form">
        <input type="hidden" name="csrf" value={workspace.csrf} />
        <input type="hidden" name="client_id" value={provider.status.selected || ''} />
        <button className={provider.status.connected ? 'quiet-action' : 'primary'} type="submit">{provider.status.connected ? 'Reconnect ChatGPT account' : 'Connect ChatGPT plan'}</button>
        {!provider.status.connected && <small>Sign-in does not import your ChatGPT history or send a message.</small>}
      </form>}
      {selected && provider.status.registration === 'offline' && provider.status.connected &&
        <button type="button" className="quiet-action" disabled={provider.checking}
          onClick={() => void provider.checkConnection()}>{provider.checking ? 'Checking chat connection…' : 'Check chat connection'}</button>}
      {provider.checkMessage && <p role="status">{provider.checkMessage}</p>}
      {selected && <button type="button" className="quiet-action settings-disconnect" disabled={provider.checking}
        onClick={() => {
          if (window.confirm('Disconnect the selected ChatGPT account from Kat? Chat will be unavailable until you reconnect or choose another saved account.'))
            void provider.disconnect();
        }}>{provider.status.registration === 'offline' &&
          provider.status.phase === 'reauthorization_required' ? 'Clear saved ChatGPT authorization' :
          'Disconnect ChatGPT plan'}</button>}
      {selected && <p><a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer noopener">Manage usage in ChatGPT settings</a> (usage and access only, not connection setup).</p>}
    </>}
    {provider.error && <p className="error" role="alert">{provider.error}</p>}
  </section>;
}
