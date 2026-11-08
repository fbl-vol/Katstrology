import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type Workspace } from '../shared/api';
import { SourceNotice } from '../shared/source-notice';

type Availability = 'checking' | 'available' | 'outside' | 'unverified';

export function LoginScreen({ initialNotice, onSignedIn }: {
  initialNotice: string; onSignedIn: (workspace: Workspace) => void;
}) {
  const [availability, setAvailability] = useState<Availability>('checking');
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [notice, setNotice] = useState(initialNotice);
  const [success, setSuccess] = useState(false);
  const [mismatch, setMismatch] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const confirmInput = useRef<HTMLInputElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);

  async function checkAvailability() {
    setAvailability('checking');
    try {
      const result = await api<{ available: boolean }>('signup');
      if (typeof result.available !== 'boolean') throw new Error('Unknown eligibility');
      setAvailability(result.available ? 'available' : 'outside');
    } catch { setAvailability('unverified'); }
  }
  useEffect(() => { void checkAvailability(); }, []);
  useEffect(() => { if (creating) heading.current?.focus(); }, [creating]);
  useEffect(() => { if (success) passwordInput.current?.focus(); }, [success]);

  function backToSignIn() {
    setCreating(false); setUncertain(false); setPassword(''); setConfirmation('');
    setShowPasswords(false); setMismatch(false);
    setNotice(uncertain ? 'Try signing in with the same username and password to check your account.' : '');
    requestAnimationFrame(() => heading.current?.focus());
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || uncertain || (creating && availability !== 'available')) return;
    if (creating && password !== confirmation) {
      setMismatch(true); confirmInput.current?.focus(); return;
    }
    setBusy(true); setNotice(''); setMismatch(false);
    try {
      if (creating) {
        const result = await api<{ status: string }>('signup', undefined, 'POST', {
          username, password, confirm_password: confirmation,
        });
        if (result.status !== 'created') throw new Error('Creation not confirmed');
        setCreating(false); setSuccess(true); setPassword(''); setConfirmation(''); setShowPasswords(false);
      } else {
        onSignedIn(await api<Workspace>('login', undefined, 'POST', { username, password }));
        setPassword('');
      }
    } catch (error) {
      if (!creating) setNotice('Sign-in failed. Check the username and password.');
      else if (error instanceof ApiError && error.status === 403) {
        setAvailability('outside'); setPassword(''); setConfirmation('');
        setNotice('Account creation isn’t available here. Connect to the home network to create an account. You can still sign in.');
      } else if (error instanceof ApiError && error.status === 400) {
        setNotice('Check the username and passwords. Use letters, numbers, underscores or hyphens for your username and at least 12 characters for your password.');
      } else if (error instanceof ApiError && error.status === 429) {
        setNotice('Please wait at least ten seconds before trying again. You can still sign in.');
      } else {
        // Includes duplicate names and lost/malformed acknowledgements. Never
        // encourage a differently named retry when the first write may exist.
        setUncertain(true); setPassword(''); setConfirmation('');
        setNotice('Account creation wasn’t confirmed. Try signing in with these details before creating another account.');
      }
    } finally { setBusy(false); }
  }

  const blocked = creating && availability !== 'available';
  const disabledFields = busy || blocked || uncertain;
  return <main className="login-screen"><section className="login-card" aria-labelledby="access-heading">
    {creating && <button type="button" className="account-back" disabled={busy} onClick={backToSignIn}>← Back to sign in</button>}
    <span className="eyebrow">THE READING ROOM</span>
    <h1 id="access-heading" ref={heading} tabIndex={-1}>{creating ? <>Create your<br />account.</> : 'Welcome to Kat.'}</h1>
    <p>{creating ? 'A separate space for your charts and conversations.' : <>Sign in to your workspace.<br />Your ChatGPT connection is separate.</>}</p>
    {success && !creating && <p className="account-notice account-success" role="status"><strong>Your account is ready.</strong> Sign in to open your workspace.</p>}
    {notice && <p className="account-notice" role="alert">{notice}</p>}
    <form onSubmit={submit} aria-busy={busy}>
      <label htmlFor="username">Username</label>
      <input id="username" autoComplete="username" required maxLength={80} pattern={creating ? '[A-Za-z0-9_-]+' : undefined}
        disabled={disabledFields} value={username} onChange={event => setUsername(event.target.value)} />
      <label htmlFor="password">Password</label>
      <input id="password" ref={passwordInput} type={creating && showPasswords ? 'text' : 'password'}
        autoComplete={creating ? 'new-password' : 'current-password'} required minLength={creating ? 12 : undefined}
        aria-describedby={creating ? 'password-help' : undefined} disabled={disabledFields}
        value={password} onChange={event => setPassword(event.target.value)} />
      {creating && <>
        <small id="password-help">Use at least 12 characters.</small>
        <label htmlFor="confirm-password">Confirm password</label>
        <input id="confirm-password" ref={confirmInput} type={showPasswords ? 'text' : 'password'} autoComplete="new-password"
          required minLength={12} disabled={disabledFields} aria-invalid={mismatch || undefined}
          aria-describedby={mismatch ? 'password-error' : undefined} value={confirmation}
          onChange={event => { setConfirmation(event.target.value); setMismatch(false); }} />
        {mismatch && <span className="error" id="password-error" role="alert">The passwords don’t match. Try entering this one again.</span>}
        <button className="account-quiet account-show" type="button" disabled={disabledFields}
          onClick={() => setShowPasswords(!showPasswords)}>{showPasswords ? 'Hide passwords' : 'Show passwords'}</button>
      </>}
      {uncertain ? <button type="button" className="primary" onClick={backToSignIn}>Back to sign in</button> :
        <button className="primary" type="submit" disabled={busy || blocked}>
          {busy ? (creating ? 'Creating account…' : 'Signing in…') : creating ? 'Create account' : 'Open workspace'}
        </button>}
    </form>
    {creating ? <>
      <p className="account-footer">This creates a Kat account, not a ChatGPT account.</p>
      {availability === 'available' && <p className="account-availability available">Account creation is available on this network.</p>}
    </> : <section className="account-enrollment" aria-label="Create an account">
      <h2>New to Kat?</h2>
      <button type="button" className="account-secondary" disabled={busy || availability !== 'available'} aria-describedby="account-availability"
        onClick={() => { setCreating(true); setSuccess(false); setNotice(''); setPassword(''); }}>
        {availability !== 'available' && <svg className="account-lock" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <rect x="4.5" y="8.5" width="11" height="8" rx="2" stroke="currentColor" />
          <path d="M7 8.5V6a3 3 0 0 1 6 0v2.5" stroke="currentColor" />
        </svg>}Create account</button>
      <p id="account-availability" className={`account-availability ${availability === 'available' ? 'available' : ''}`} role="status">
        {availability === 'available' ? 'You’re on the home network.' : availability === 'checking' ? 'Checking where account creation is available…' :
          availability === 'unverified' ? 'Account creation couldn’t be checked. You can still sign in.' :
            'Account creation is only available on the home network. You can still sign in from here.'}
      </p>
      {availability === 'unverified' && <button className="account-quiet" type="button" disabled={busy} onClick={() => void checkAvailability()}>Check again</button>}
    </section>}
    <SourceNotice />
  </section></main>;
}
