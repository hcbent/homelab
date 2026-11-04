/** Loads the self-hosted faces and records whether the real families (not fallbacks) are in use. */
const INTER = ["400", "500", "600", "700"];
const MONO = ["400", "500"];

export async function ensureFonts(): Promise<boolean> {
  if (typeof document === "undefined" || !("fonts" in document)) return false;
  try {
    await Promise.all([
      ...INTER.map((w) => document.fonts.load(`${w} 16px Inter`)),
      ...MONO.map((w) => document.fonts.load(`${w} 14px "Roboto Mono"`)),
    ]);
    await document.fonts.ready;
    const ok = INTER.every((w) => document.fonts.check(`${w} 16px Inter`))
      && MONO.every((w) => document.fonts.check(`${w} 14px "Roboto Mono"`));
    document.documentElement.dataset.fonts = ok ? "loaded" : "fallback";
    return ok;
  } catch {
    document.documentElement.dataset.fonts = "fallback";
    return false;
  }
}
