import { useEffect, useRef, type ReactNode } from 'react';

/** Floating actions use native details, with popover-style dismissal only here. */
export function ConversationMenu({ children }: { children: ReactNode }) {
  const details = useRef<HTMLDetailsElement>(null);
  const opener = useRef<HTMLElement>(null);

  useEffect(() => {
    const place = () => {
      const menu = details.current;
      const panel = menu?.querySelector<HTMLElement>('.conversation-controls');
      if (!menu?.open || !panel || !opener.current) return;
      const anchor = opener.current.getBoundingClientRect();
      const above = anchor.top - 8;
      const below = innerHeight - anchor.bottom - 8;
      const openAbove = below < 220 && above > below;
      menu.dataset.placement = openAbove ? 'above' : 'below';
      panel.style.top = openAbove ? 'auto' : '100%';
      panel.style.bottom = openAbove ? '100%' : 'auto';
      panel.style.maxHeight = `${Math.min(280, Math.max(0, openAbove ? above : below))}px`;
    };
    const menu = details.current;
    menu?.addEventListener('toggle', place);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place);

    const dismissOutside = (event: PointerEvent) => {
      if (details.current?.open && !details.current.contains(event.target as Node)) details.current.open = false;
    };
    const dismissEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || !details.current?.open) return;
      event.preventDefault();
      details.current.open = false;
      opener.current?.focus();
    };
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('keydown', dismissEscape);
    return () => {
      menu?.removeEventListener('toggle', place);
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place);
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('keydown', dismissEscape);
    };
  }, []);

  return <details className="conversation-menu" ref={details} onClick={event => {
    if ((event.target as HTMLElement).closest('.conversation-controls button')) details.current!.open = false;
  }}><summary ref={opener} onClick={() => details.current?.removeAttribute('data-placement')}
    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') details.current?.removeAttribute('data-placement'); }}>
    Conversation options</summary><div className="conversation-controls">{children}</div></details>;
}
