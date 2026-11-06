import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, type Workspace } from '../api';
import { SourceNotice } from '../source-notice';
import { WorkspaceShell } from './workspace-shell';

/** Session lifetime is the boundary for all mounted workspace state. */
export function Application() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    api<Workspace>('session').then(setWorkspace).catch((error: unknown) => {
      if (!(error instanceof ApiError && error.status === 401)) setNotice('Workspace unavailable. Check the local server.');
    }).finally(() => setLoading(false));
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setNotice('');
      const user = await api<Workspace>('login', undefined, 'POST', { username, password });
      setWorkspace(user); setPassword('');
    } catch { setNotice('Sign-in failed. Check the local username and password.'); }
  }

  if (loading) return <main className="login-screen" aria-busy="true"><p>Opening your local workspace…</p></main>;
  if (workspace) return <WorkspaceShell key={`${workspace.owner}:${workspace.csrf}`}
    workspace={workspace} onSignedOut={() => setWorkspace(null)} />;
  return <main className="login-screen"><section className="login-card">
    <span className="eyebrow">THE READING ROOM · LOCAL</span>
    <h1>Welcome to Kat.</h1><p>Sign in to your local workspace. Your ChatGPT connection is separate.</p>
    <form onSubmit={signIn}>
      <label htmlFor="username">Username</label>
      <input id="username" autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} />
      <label htmlFor="password">Password</label>
      <input id="password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
      {notice && <p className="error" role="alert">{notice}</p>}
      <button className="primary" type="submit">Open workspace</button>
    </form>
    <SourceNotice />
  </section></main>;
}
