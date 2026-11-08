import { createContext, useContext } from 'react';

/** Session-local identities only. The workspace owns native history for every layer. */
export const NestedNavigation = createContext<{
  state: Record<string, string>;
  change: (key: string, value: string | null, replace?: boolean, descendants?: readonly string[]) => void;
} | null>(null);

export function useNestedNavigation(key: string) {
  const navigation = useContext(NestedNavigation);
  return { value: navigation?.state[key] ?? null,
    change: (value: string | null, replace = false) => navigation?.change(key, value, replace),
    close: (descendants: readonly string[]) => navigation?.change(key, null, false, descendants),
    available: navigation !== null };
}
