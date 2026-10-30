import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, Infrastructure } from "./api";
import { ago, bytes, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { useInterval } from "./useInterval";

function AddProxmox({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ name: "", api_url: "", token_id: "", token_secret: "", ca_pem: "" });
  const [insecure, setInsecure] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const c = await api<{ id: string }>("/api/proxmox", { method: "POST", body: JSON.stringify({
        ...f, ca_pem: f.ca_pem || null, verify_tls: !insecure }) });
      await api(`/api/proxmox/${c.id}/sync`, { method: "POST" });
      onDone();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
      onDone();
    }
  }
  return (
    <form onSubmit={submit} className="mb-6 space-y-2 rounded border p-4 text-sm">
      <h3 className="font-medium">Add a Proxmox connection (read-only token)</h3>
      <input aria-label="Name" placeholder="Name" className="w-full rounded border p-1" value={f.name} onChange={set("name")} />
      <input aria-label="API URL" placeholder="https://pve1.example:8006" className="w-full rounded border p-1"
        value={f.api_url} onChange={set("api_url")} />
      <input aria-label="Token ID" placeholder="user@realm!tokenname" className="w-full rounded border p-1"
        value={f.token_id} onChange={set("token_id")} />
      <input aria-label="Token secret" type="password" autoComplete="off" className="w-full rounded border p-1"
        value={f.token_secret} onChange={set("token_secret")} />
      <textarea aria-label="CA certificate" placeholder="CA certificate PEM (optional)" rows={3}
        className="w-full rounded border p-1 font-mono text-xs" value={f.ca_pem} onChange={set("ca_pem")} />
      <label className="flex items-center gap-2"><input type="checkbox" checked={insecure}
        onChange={(e) => setInsecure(e.target.checked)} /> Skip TLS verification (not recommended)</label>
      {err && <p role="alert" className="text-red-600">{err}</p>}
      <button className="rounded bg-slate-900 px-3 py-1 text-white">Add and sync</button>
    </form>
  );
}

export function InfrastructureView() {
  const [d, setD] = useState<Infrastructure | null>(null);
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => { api<Infrastructure>("/api/infrastructure").then(setD).catch(() => {}); }, []);
  useEffect(load, [load]);
  useInterval(load, seconds);
  if (!d) return <p>Loading…</p>;

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Infrastructure (Proxmox-reported)</h2>
        <div className="flex items-center gap-4">
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
          <button className="rounded border px-3 py-1 text-sm" onClick={() => setAdding(!adding)}>Add connection</button>
        </div>
      </div>
      {adding && <AddProxmox onDone={() => { setAdding(false); load(); }} />}
      {d.connections.map((c) => (
        <p key={c.id} className="text-sm">{c.name} — {c.api_url} · synced {ago(c.last_sync_at)}
          {c.last_sync_error && <span role="alert" className="text-red-600"> · {c.last_sync_error}</span>}</p>))}

      <div><h3 className="mb-1 font-medium">Hosts</h3>
        <table className="w-full text-left text-sm"><thead><tr><th>Host</th><th>Status</th><th>CPU</th><th>Memory</th></tr></thead>
          <tbody>{d.nodes.map((n) => (<tr key={n.name} className="border-t"><td>{n.name}</td><td>{n.status}</td>
            <td>{Math.round((n.usage.cpu ?? 0) * 100)}% of {n.usage.maxcpu}</td>
            <td>{bytes(n.usage.mem)} / {bytes(n.usage.maxmem)}</td></tr>))}</tbody></table></div>

      <div><h3 className="mb-1 font-medium">Storage</h3>
        <table className="w-full text-left text-sm"><thead><tr><th>Host</th><th>Pool</th><th>Type</th><th>Used</th><th>Free</th></tr></thead>
          <tbody>{d.storages.map((s) => (<tr key={s.node + s.name} className="border-t"><td>{s.node}</td>
            <td>{s.name}{s.shared ? " (shared)" : ""}</td><td>{s.type}</td><td>{bytes(s.used)}</td><td>{bytes(s.avail)}</td></tr>))}</tbody></table></div>

      <div><h3 className="mb-1 font-medium">Templates</h3>
        <ul className="text-sm">{d.templates.map((t) => <li key={t.id}>VM {t.vmid} · {t.name} · {t.pve_node}</li>)}</ul>
        {d.templates.length === 0 && <p className="text-sm text-slate-500">None found.</p>}</div>

      <div><h3 className="mb-1 font-medium">Virtual machines</h3>
        <table className="w-full text-left text-sm"><thead><tr><th>VM</th><th>Host</th><th>Status</th><th>vCPU</th><th>RAM</th><th>Addresses</th><th>Elasticsearch</th></tr></thead>
          <tbody>{d.vms.map((v) => (<tr key={v.id} className="border-t"><td>{v.vmid} {v.name}</td><td>{v.pve_node}</td>
            <td>{v.status}</td><td>{v.cpu_cores}</td><td>{v.memory_mb} MB</td>
            <td className="text-xs">{v.ips.map((i) => i.ip).join(", ")}</td>
            <td>{v.es_cluster_id ? <a className="underline" href={`#/clusters/${v.es_cluster_id}`}>{v.es_link}</a> : "—"}</td></tr>))}</tbody></table></div>
    </section>
  );
}
