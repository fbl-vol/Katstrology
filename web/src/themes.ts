export const themes = [
  { id: 'reading-room', label: 'Reading Room', mode: 'light', description: 'Forest green and warm ivory' },
  { id: 'linen-ink', label: 'Linen & Ink', mode: 'light', description: 'Quiet parchment and blue ink' },
  { id: 'coastal-slate', label: 'Coastal Slate', mode: 'light', description: 'Sea glass and slate' },
  { id: 'rosewood', label: 'Rosewood', mode: 'light', description: 'Soft blush and burgundy' },
  { id: 'amber-study', label: 'Amber Study', mode: 'light', description: 'Honey paper and umber' },
  { id: 'peony', label: 'Peony', mode: 'light', description: 'Petal pink and raspberry ink' },
  { id: 'wisteria', label: 'Wisteria', mode: 'light', description: 'Lilac and mulberry ink' },
  { id: 'apricot-silk', label: 'Apricot Silk', mode: 'light', description: 'Peach porcelain and terracotta' },
  { id: 'sea-pearl', label: 'Sea Pearl', mode: 'light', description: 'Pale jade and pearly white' },
  { id: 'midnight-pine', label: 'Midnight Pine', mode: 'dark', description: 'Deep evergreen and sage' },
  { id: 'ink-copper', label: 'Ink & Copper', mode: 'dark', description: 'Smoky ink and copper' },
  { id: 'blue-hour', label: 'Blue Hour', mode: 'dark', description: 'Indigo and silver blue' },
  { id: 'aubergine', label: 'Aubergine', mode: 'dark', description: 'Plum and dusty lavender' },
  { id: 'charcoal-gold', label: 'Charcoal & Gold', mode: 'dark', description: 'Graphite and antique gold' },
  { id: 'black-cherry', label: 'Black Cherry', mode: 'dark', description: 'Cherry velvet and rose-petal light' },
  { id: 'moonstone', label: 'Moonstone', mode: 'dark', description: 'Smoky mauve and silver lilac' },
  { id: 'cocoa-rose', label: 'Cocoa Rose', mode: 'dark', description: 'Warm cocoa and dusty pink' },
  { id: 'midnight-orchid', label: 'Midnight Orchid', mode: 'dark', description: 'Deep violet and orchid light' },
] as const;

export type ThemeId = (typeof themes)[number]['id'];
export const defaultTheme: ThemeId = 'reading-room';
export const themeStorageKey = 'kat.appearance.theme';

export function resolveTheme(value: string | null): ThemeId {
  return themes.find(theme => theme.id === value)?.id ?? defaultTheme;
}

export function readTheme(storage: Pick<Storage, 'getItem'> | null = safeStorage()): ThemeId {
  try { return resolveTheme(storage?.getItem(themeStorageKey) ?? null); }
  catch { return defaultTheme; }
}

function safeStorage(): Storage | null {
  try { return window.localStorage; }
  catch { return null; }
}

function showTheme(id: ThemeId): void {
  document.documentElement.dataset.theme = id;
  // The stylesheet is the palette authority; browser chrome follows its reading surface.
  const paper = getComputedStyle(document.documentElement).getPropertyValue('--paper').trim();
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute('content', paper);
}

export function applyTheme(id: ThemeId, storage: Pick<Storage, 'setItem'> | null = safeStorage()): void {
  showTheme(id);
  try { storage?.setItem(themeStorageKey, id); }
  catch { /* Private browsing or disabled storage still permits in-session selection. */ }
}

export function initializeTheme(): ThemeId {
  const id = readTheme();
  showTheme(id);
  return id;
}
