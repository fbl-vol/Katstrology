import { expect, type Locator, type Page } from '@playwright/test';

type Event = { sequence: number; kind: string; payload: Record<string, unknown> };
type ArchivedTurn = { status: string; selected_people: { person_id: string; chart_id: string | null;
  draft_revision: number | null; attachment_id: string | null }[];
  events: Event[]; next_event_offset: number | null };

/** Read the committed synthetic archive, not a diagnostic DOM panel. */
export async function archivedTurn(page: Page, card: Locator): Promise<ArchivedTurn> {
  const id = await card.getAttribute('data-kat-turn-id');
  expect(id).toBeTruthy();
  return page.evaluate(async turnId => {
    const { conversations } = await fetch('/api/conversations').then(response => response.json());
    for (const conversation of conversations) {
      const path = `/api/conversations/${conversation.id}/turns/${turnId}`;
      const response = await fetch(path);
      if (!response.ok) continue;
      const turn: ArchivedTurn = await response.json();
      let cursor = turn.next_event_offset;
      while (cursor !== null) {
        const page = await fetch(`${path}?offset=${cursor}`).then(reply => reply.json());
        turn.events.push(...page.events);
        cursor = page.next_event_offset;
      }
      return turn;
    }
    throw new Error('The visible turn was not found in this synthetic owner’s archive');
  }, id);
}
