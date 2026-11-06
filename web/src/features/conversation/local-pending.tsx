type PendingMessage = { payload: { id: string; text: string };
  failure?: { message: string; reconnect: boolean } };

export function LocalPendingMessage({ pending, onRetry, onReconnect, disabled }: {
  pending: PendingMessage; onRetry: () => void; onReconnect: () => void; disabled: boolean;
}) {
  return <div className="local-pending" data-kat-pending-turn-id={pending.payload.id}
    role="status" aria-label={pending.failure ? 'Message needs attention' : 'Message being sent'}>
    <p className="user-bubble">{pending.payload.text}</p>
    {pending.failure ? <div className="local-pending-recovery">
      <p role="alert">{pending.failure.message}</p>
      <div><button type="button" disabled={disabled} onClick={onRetry}>Retry this message</button>
        {pending.failure.reconnect && <button type="button" onClick={onReconnect}>Connect ChatGPT</button>}</div>
    </div> : <span>Sending…</span>}
  </div>;
}
