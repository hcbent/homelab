import "@testing-library/jest-dom/vitest";

// jsdom has no matchMedia; EUI and the reveal helper both read it.
if (typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// Newer Node versions expose an experimental localStorage that shadows jsdom's and throws or is undefined.
// Tests get a plain in-memory Storage instead.
{
  let ok = false;
  try { ok = typeof globalThis.localStorage?.clear === "function"; } catch { ok = false; }
  if (!ok) {
    const data = new Map<string, string>();
    const memory = {
      get length() { return data.size; },
      clear: () => data.clear(),
      getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
      key: (i: number) => [...data.keys()][i] ?? null,
      removeItem: (k: string) => { data.delete(k); },
      setItem: (k: string, v: string) => { data.set(k, String(v)); },
    } as Storage;
    Object.defineProperty(globalThis, "localStorage", { value: memory, configurable: true });
    Object.defineProperty(window, "localStorage", { value: memory, configurable: true });
  }
}

// jsdom has no canvas. EUI's multi-select (EuiComboBox) measures the width of each selected pill with one, so it gets a
// stand-in that reports a fixed width per character. Nothing here draws.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = (() => ({
    font: "", measureText: (text: string) => ({ width: text.length * 7 }),
  })) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}
