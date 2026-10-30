import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, ClusterSummary } from "./api";
import { HealthBadge, OwnershipBadge } from "./Badges";
import { ago, bytes, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { useInterval } from "./useInterval";

function RegisterForm({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [ca, setCa] = useState("");
  const [insecure, setInsecure] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/api/clusters/register", { method: "POST", body: JSON.stringify({
        urls: [url], api_key: key, ca_pem: ca || null, verify_tls: !insecure }) });
      setUrl(""); setKey(""); setCa("");
      onDone();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    }
  }
  return (
    <form onSubmit={submit} className="mb-6 space-y-2 rounded border p-4 text-sm">
      <h3 className="font-medium">Register an existing cluster (read-only)</h3>
      <label className="block">Endpoint URL
        <input className="mt-1 w-full rounded border p-1" value={url} placeholder="https://es01.example:9200"
          onChange={(e) => setUrl(e.target.value)} />
      </label>
      <label className="block">API key (encoded)
        <input type="password" className="mt-1 w-full rounded border p-1" value={key}
          onChange={(e) => setKey(e.target.value)} autoComplete="off" />
      </label>
      <label className="block">CA certificate (PEM, optional)
        <textarea className="mt-1 w-full rounded border p-1 font-mono text-xs" rows={3} value={ca}
          onChange={(e) => setCa(e.target.value)} />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={insecure} onChange={(e) => setInsecure(e.target.checked)} />
        Skip TLS verification (not recommended)
      </label>
      {err && <p role="alert" className="text-red-600">{err}</p>}
      <button className="rounded bg-slate-900 px-3 py-1 text-white">Register</button>
    </form>
  );
}

export function Dashboard() {
  const [rows, setRows] = useState<ClusterSummary[] | null>(null);
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => { api<ClusterSummary[]>("/api/clusters").then(setRows).catch(() => {}); }, []);
  useEffect(load, [load]);
  useInterval(load, seconds);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-medium">Clusters</h2>
        <div className="flex items-center gap-4">
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
          <button className="rounded border px-3 py-1 text-sm" onClick={() => setAdding(!adding)}>
            Register cluster
          </button>
        </div>
      </div>
      {adding && <RegisterForm onDone={() => { setAdding(false); load(); }} />}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr>
            <th>Name</th><th>Health</th><th>Version</th><th>Nodes (data)</th><th>Infrastructure</th>
            <th>Storage</th><th>JVM heap</th><th>Status</th><th>Last sync</th>
          </tr></thead>
          <tbody>
            {rows?.map((c) => (
              <tr key={c.id} className="border-t align-top">
                <td><a className="underline" href={`#/clusters/${c.id}`}>{c.name}</a>
                  <div className="font-mono text-xs text-slate-500" title="Cluster UUID">{c.uuid}</div></td>
                <td><HealthBadge status={c.health} /></td>
                <td>{c.version}</td>
                <td>{c.nodes} ({c.data_nodes})</td>
                <td>{c.infrastructure.proxmox_hosts.join(", ") || "—"}
                  <div className="text-xs text-slate-500">
                    {c.infrastructure.verified_links}/{c.infrastructure.total_nodes} nodes linked</div></td>
                <td>{c.storage.used_pct ?? "—"}% <span className="text-xs text-slate-500">
                  of {bytes(c.storage.total_bytes)}</span></td>
                <td>{c.jvm_heap_used_pct ?? "—"}%</td>
                <td><OwnershipBadge value={c.ownership} /></td>
                <td>{ago(c.last_sync_at)}
                  {c.last_sync_error && <div role="alert" className="text-xs text-red-600">{c.last_sync_error}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows?.length === 0 && <p className="mt-2 text-sm text-slate-500">
        No clusters yet. Register an existing cluster to inspect it. Nothing is changed on it.</p>}
    </section>
  );
}
