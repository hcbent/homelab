/// <reference types="vite/client" />
// @ts-expect-error EUI ships no type declarations for its internal icon map
import { typeToPathMap } from "@elastic/eui/lib/components/icon/icon_map";

const sources = import.meta.glob(["./*.tsx", "!./*.test.tsx"], { query: "?raw", import: "default", eager: true }) as
  Record<string, string>;

/**
 * EUI draws a broken-image box for an icon name it does not know, and TypeScript accepts any string there.
 * Every icon name written in the source has to exist in the installed EUI.
 */
test("every icon name used in the source exists in EUI", () => {
  const used = new Map<string, string>();
  for (const [file, text] of Object.entries(sources)) {
    for (const m of text.matchAll(/\b(?:iconType|icon)=\{?"([A-Za-z]+)"/g)) used.set(m[1], file);
  }
  expect(used.size).toBeGreaterThan(5);   // the scan itself found something
  const unknown = [...used].filter(([name]) => !(name in typeToPathMap)).map(([name, file]) => `${name} (${file})`);
  expect(unknown).toEqual([]);
});
