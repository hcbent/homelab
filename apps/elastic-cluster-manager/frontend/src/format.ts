export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export function storedNumber(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && localStorage.getItem(key) !== null ? v : fallback;
  } catch { return fallback; }
}

export function store(key: string, value: number) {
  try { localStorage.setItem(key, String(value)); } catch { /* private mode */ }
}

/** CPU as "12% of 16", or "Not available" when Proxmox sent no usage data (never "0% of null"). */
export function cpuText(usage: { cpu?: number | null; maxcpu?: number | null }): string {
  if (usage.cpu == null || usage.maxcpu == null) return "Not available";
  return `${Math.round(usage.cpu * 100)}% of ${usage.maxcpu}`;
}

/** Memory as "3.0 GB / 8.0 GB", or "Not available" when either figure is missing. */
export function memText(usage: { mem?: number | null; maxmem?: number | null }): string {
  if (usage.mem == null || usage.maxmem == null) return "Not available";
  return `${bytes(usage.mem)} / ${bytes(usage.maxmem)}`;
}
