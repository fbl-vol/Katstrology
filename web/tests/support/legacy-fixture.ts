import type { Page } from '@playwright/test';

// Synthetic-only fixture for records that existed before the one-action form.
// Unlike the normal UI, these APIs may still be used to preserve and read archived versions.
export async function personIdFor(page: Page, name: string): Promise<string> {
  const people = await (await page.request.get('/api/people')).json();
  const person = people.people.find((item: { name: string }) => item.name === name);
  if (!person) throw new Error(`Synthetic person not found: ${name}`);
  return person.id;
}

export async function seedLegacy(page: Page, personId: string, options: {
  date?: string; time?: string; birthplace?: string; zone?: string;
  latitude?: number; longitude?: number; kind?: 'solar' | 'natal';
  unknown?: boolean;
}) {
  const session = await (await page.request.get('/api/session')).json();
  const post = async (path: string, data: unknown) => {
    const response = await page.request.post(path, { headers: { 'X-Kat-CSRF': session.csrf, Origin: new URL(page.url()).origin }, data });
    if (response.status() !== 201) throw new Error(`Synthetic legacy fixture rejected ${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const date = options.date || '2024-03-20';
  const time = options.time || '03:06';
  const zone = options.zone || 'UTC';
  await post(`/api/people/${personId}/drafts`, {
    birth_date: date, birth_time: options.unknown ? '' : time,
    time_unknown: !!options.unknown, birthplace: options.birthplace || 'Unverified city',
  });
  const birth = await post(`/api/people/${personId}/births`, {
    mode: 'exact', zone, wall_time: `${date}T${time}:00`,
    latitude: options.latitude ?? null, longitude: options.longitude ?? null,
  });
  const chart = await post(`/api/people/${personId}/charts`, {
    birth_id: birth.birth_id, profile_id: options.kind === 'solar' ? 'solar-default' : 'natal-default', revision: 1,
  });
  return { birthId: birth.birth_id as string, chartId: chart.id as string };
}
