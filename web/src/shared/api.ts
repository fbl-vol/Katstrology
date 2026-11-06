export type Workspace = { owner: string; csrf: string; workspace: string;
  product: { model: string; reporting_zone: string } };

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string,
    readonly details: { conversations?: { id: string; title: string }[]; more?: boolean } = {}) {
    super(code);
  }
}

export async function api<T>(path: string, csrf?: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(csrf ? { 'X-Kat-CSRF': csrf } : {})
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new ApiError(response.status, result.error || 'unavailable', result);
  return result as T;
}
