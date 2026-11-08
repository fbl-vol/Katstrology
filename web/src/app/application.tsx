import { useEffect, useState } from 'react';
import { api, ApiError, type Workspace } from '../shared/api';
import { LoginScreen } from './login-screen';
import { WorkspaceShell } from './workspace-shell';

/** Session lifetime is the boundary for all mounted workspace state. */
export function Application() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    api<Workspace>('session').then(setWorkspace).catch((error: unknown) => {
      if (!(error instanceof ApiError && error.status === 401)) setNotice('Workspace unavailable. Check the local server.');
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <main className="login-screen" aria-busy="true"><p>Opening your local workspace…</p></main>;
  if (workspace) return <WorkspaceShell key={`${workspace.owner}:${workspace.csrf}`}
    workspace={workspace} onSignedOut={() => setWorkspace(null)} />;
  return <LoginScreen initialNotice={notice} onSignedIn={setWorkspace} />;
}
