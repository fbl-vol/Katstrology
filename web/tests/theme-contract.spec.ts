import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { defaultTheme, themes } from '../src/themes';

// A palette concept is not a product palette until every shell/chart/form token
// has an explicit value. Inherited Reading Room values can conceal omissions.
test('every registered palette declares the full semantic contract and preview', () => {
  const css = readFileSync(resolve(import.meta.dirname, '../src/themes.css'), 'utf8');
  const blocks = [...css.matchAll(/(?::root,\s*)?:root\[data-theme="([^"]+)"\],\s*\[data-preview="\1"\]\s*\{([^}]*)\}/g)];
  const defaults = blocks.find(block => block[1] === defaultTheme)?.[2];
  expect(defaults, 'Default palette must declare the full token contract').toBeTruthy();
  const tokens = [...defaults!.matchAll(/(--[a-z-]+)\s*:/g)].map(match => match[1]);
  expect(tokens.length).toBeGreaterThan(25);
  expect(new Set(tokens).size).toBe(tokens.length);
  expect(new Set(themes.map(theme => theme.id)).size).toBe(themes.length);
  expect(new Set(blocks.map(block => block[1]))).toEqual(new Set(themes.map(theme => theme.id)));
  const html = readFileSync(resolve(import.meta.dirname, '../index.html'), 'utf8');
  const prepaint = html.match(/dataset\.theme\s*=\s*\[([^\]]+)\]\.includes\([^)]*\)/)?.[1];
  expect(prepaint, 'Prepaint allowlist must be explicit').toBeTruthy();
  expect(new Set([...prepaint!.matchAll(/'([^']+)'/g)].map(match => match[1])))
    .toEqual(new Set(themes.map(theme => theme.id)));
  for (const theme of themes) {
    const body = blocks.find(block => block[1] === theme.id)![2];
    expect(body, `${theme.id} missing color-scheme`).toMatch(new RegExp(`color-scheme\\s*:\\s*${theme.mode}\\s*;`));
    const declared = [...body.matchAll(/(--[a-z-]+)\s*:\s*([^;]+);/g)];
    expect(new Set(declared.map(match => match[1])), theme.id).toEqual(new Set(tokens));
    for (const [, token, value] of declared)
      expect(value.trim(), `${theme.id} ${token} needs an explicit color`).toMatch(/^#[\da-f]{3,8}$/i);
  }
});

test('all eight additions retain the ten original theme values and default', () => {
  const legacy = ['reading-room', 'linen-ink', 'coastal-slate', 'rosewood', 'amber-study',
    'midnight-pine', 'ink-copper', 'blue-hour', 'aubergine', 'charcoal-gold'];
  const added = ['peony', 'wisteria', 'apricot-silk', 'sea-pearl',
    'black-cherry', 'moonstone', 'cocoa-rose', 'midnight-orchid'];
  expect(defaultTheme).toBe('reading-room');
  expect(themes.map(theme => theme.id)).toHaveLength(18);
  for (const id of [...legacy, ...added]) expect(themes.some(theme => theme.id === id), id).toBe(true);
  expect(themes.filter(theme => theme.mode === 'light')).toHaveLength(9);
  expect(themes.filter(theme => theme.mode === 'dark')).toHaveLength(9);

  // Canonicalized values from the ten legacy blocks at the approved base tip.
  const css = readFileSync(resolve(import.meta.dirname, '../src/themes.css'), 'utf8');
  const blocks = [...css.matchAll(/(?::root,\s*)?:root\[data-theme="([^"]+)"\],\s*\[data-preview="\1"\]\s*\{([^}]*)\}/g)];
  const original = legacy.map(id => [id, [...blocks.find(block => block[1] === id)![2]
    .matchAll(/(--[a-z-]+)\s*:\s*([^;]+);/g)]
    .map(([, name, value]) => [name, value.trim().toLowerCase()])
    .sort(([a], [b]) => a.localeCompare(b))]);
  expect(createHash('sha256').update(JSON.stringify(original)).digest('hex'))
    .toBe('9d41cb7b646ee24e4f55af35b1e5883386c8e59becb82aac516b9cf79294eb1f');
});
