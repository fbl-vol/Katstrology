import { useLayoutEffect, useRef } from 'react';

type Entry<T> = { route: T; parent: string | null; x: number; y: number; focus: WeakRef<Element> | null };
const positionInterrupts = ['wheel', 'touchstart', 'pointerdown', 'keydown', 'input'] as const;

/** Native history is the journey; this session-only journal supplies its identities
 * and reading positions. No route, private content or credentials enter browser state. */
export function useBrowserHistory<T>(route: T, root: T, suspended: boolean,
  restore: (route: T) => Promise<T>, replaceTransition: (previous: T, next: T) => boolean) {
  const session = useRef(crypto.randomUUID());
  const entries = useRef(new Map<string, Entry<T>>());
  const current = useRef('');
  const restoring = useRef(false);
  const restorationVersion = useRef(0);
  const replaceNext = useRef(false);
  const backNext = useRef(false);
  const interactionVersion = useRef(0);
  const pendingBack = useRef<{ id: string; version: number; interaction: number } | null>(null);
  const latestRoute = useRef(route); latestRoute.current = route;
  const callbacks = useRef({ restore, replaceTransition });
  callbacks.current = { restore, replaceTransition };
  const stopPositionRestore = useRef<() => void>(() => {});
  const equal = (a: T, b: T) => JSON.stringify(a) === JSON.stringify(b);

  function remember(route?: T) {
    if (restoring.current) return;
    const entry = entries.current.get(current.current);
    if (entry) {
      entry.x = scrollX; entry.y = scrollY;
      entry.focus = document.activeElement ? new WeakRef(document.activeElement) : null;
      if (route) entry.route = route;
    }
  }
  function install(value: T, parent: string | null, replace: boolean) {
    const id = crypto.randomUUID();
    entries.current.set(id, { route: value, parent, x: scrollX, y: scrollY, focus: null });
    current.current = id;
    history[replace ? 'replaceState' : 'pushState']({ katNavigation: session.current, entry: id }, '');
  }
  function restorePosition(entry: Entry<T>) {
    stopPositionRestore.current();
    let frame = 0;
    const position = { x: entry.x, y: entry.y };
    const stop = () => {
      cancelAnimationFrame(frame); observer.disconnect();
      for (const event of positionInterrupts) window.removeEventListener(event, stop);
    };
    const apply = () => {
      window.scrollTo(position.x, position.y);
      if (Math.abs(scrollY - position.y) < 2) stop();
    };
    const observer = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(apply); });
    observer.observe(document.body);
    for (const event of positionInterrupts) window.addEventListener(event, stop, { passive: true });
    frame = requestAnimationFrame(() => {
      const focus = entry.focus?.deref();
      if ((focus instanceof HTMLElement || focus instanceof SVGElement) && focus.isConnected && focus.getClientRects().length && !focus.closest('[inert],[hidden]'))
        focus.focus({ preventScroll: true });
      apply();
    });
    stopPositionRestore.current = stop;
  }

  useLayoutEffect(() => {
    const previousRestoration = history.scrollRestoration;
    history.scrollRestoration = 'manual';
    install(root, null, true);
    let live = true;
    async function pop(event: PopStateEvent) {
      stopPositionRestore.current();
      const state = event.state;
      let entry = state?.katNavigation === session.current ? entries.current.get(state.entry) : undefined;
      if (!entry) {
        // Reloads and old signed-out sessions cannot revive this session's views.
        install(root, null, true); entry = entries.current.get(current.current)!;
      } else current.current = state.entry;
      const requestedBack = pendingBack.current; pendingBack.current = null;
      if (requestedBack?.id === current.current && requestedBack.version !== restorationVersion.current) {
        install(latestRoute.current, entry.parent, true); return;
      }
      const id = current.current;
      // Explicit close exposes the destination before popstate; native Back
      // exposes it during restore. Neither may override input begun meanwhile.
      const interaction = requestedBack?.id === id ? requestedBack.interaction : interactionVersion.current;
      const version = ++restorationVersion.current;
      restoring.current = true;
      const restored = await callbacks.current.restore(entry.route);
      if (!live || current.current !== id || version !== restorationVersion.current) return;
      if (!equal(entry.route, restored)) { entry.x = 0; entry.y = 0; entry.focus = null; }
      entry.route = restored;
      restoring.current = false;
      if (interactionVersion.current === interaction) restorePosition(entry);
    }
    const scroll = () => {
      if (restoring.current) return;
      const entry = entries.current.get(current.current);
      if (entry) { entry.x = scrollX; entry.y = scrollY; }
    };
    const interact = () => { interactionVersion.current++; };
    for (const event of positionInterrupts) window.addEventListener(event, interact, { passive: true });
    window.addEventListener('popstate', pop); window.addEventListener('scroll', scroll, { passive: true });
    return () => {
      live = false; stopPositionRestore.current(); entries.current.clear();
      for (const event of positionInterrupts) window.removeEventListener(event, interact);
      window.removeEventListener('popstate', pop); window.removeEventListener('scroll', scroll);
      history.scrollRestoration = previousRestoration;
    };
  }, []);

  useLayoutEffect(() => {
    if (restoring.current || suspended) return;
    const entry = entries.current.get(current.current);
    if (!entry || equal(entry.route, route)) { backNext.current = false; replaceNext.current = false; return; }
    stopPositionRestore.current();
    if (backNext.current && !replaceNext.current) {
      let id = entry.parent, distance = 1;
      while (id) {
        const ancestor = entries.current.get(id);
        if (!ancestor) break;
        if (equal(ancestor.route, route)) {
          backNext.current = false; restoring.current = true;
          pendingBack.current = { id, version: restorationVersion.current, interaction: interactionVersion.current };
          history.go(-distance); return;
        }
        id = ancestor.parent; distance++;
      }
    }
    backNext.current = false;
    const replace = replaceNext.current || callbacks.current.replaceTransition(entry.route, route);
    replaceNext.current = false;
    install(route, replace ? entry.parent : current.current, replace);
  }, [route, suspended]);

  return { remember, backNext: () => { backNext.current = true; }, replaceNext: () => { replaceNext.current = true; },
    cancelRestoration: () => {
      restorationVersion.current++; restoring.current = false; stopPositionRestore.current();
    } };
}
