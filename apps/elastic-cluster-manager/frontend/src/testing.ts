import { vi } from "vitest";

export type Handler = (url: string, init?: RequestInit) => [number, unknown];

/** Replace fetch with a handler that returns [status, body]. Returns the spy so tests can read what was sent. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const [status, body] = handler(url, init);
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Match by "METHOD /path". Anything not listed is a 404, so a missing mock fails loudly. */
export function table(routes: Record<string, [number, unknown]>): Handler {
  return (url, init) => routes[`${init?.method ?? "GET"} ${url}`] ?? [404, { detail: `no mock for ${init?.method ?? "GET"} ${url}` }];
}

/** The bodies of every POST to a path, parsed. */
export function posted(fn: ReturnType<typeof mockFetch>, path: string): Record<string, unknown>[] {
  return fn.mock.calls
    .filter(([url, init]) => url === path && (init as RequestInit | undefined)?.method === "POST")
    .map(([, init]) => JSON.parse(String((init as RequestInit).body ?? "{}")));
}
