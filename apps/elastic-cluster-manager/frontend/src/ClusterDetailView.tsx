import { useCallback, useEffect, useState } from "react";
import { api, ApiError, ClusterDetail } from "./api";
import { HealthBadge, LinkBadge, OwnershipBadge } from "./Badges";
import { ago, bytes, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { useInterval } from "./useInterval";

const TABS = ["Nodes", "Shards", "Settings", "Infrastructure", "Operations"] as const;
type Tab = (typeof TABS)[number];

export function ClusterDetailView({ id }: { id: string }) {
  const [c, setC] = useState<ClusterDetail | null>(null);
  const [tab, setTab] = useState<Tab>("Nodes");
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const load = useCallback(() => { api<ClusterDetail>(`/api/clusters/${id}`).then(setC).catch(() => {}); }, [id]);
  useEffect(load, [load]);
  useInterval(load, seconds);

  async function syncNow() {
    setSyncErr(null);
    try { await api(`/api/clusters/${id}/sync`, { method: "POST" }); }
    catch (e) { setSyncErr(e instanceof ApiError ? e.message : String(e)); }
    load();
  }

  if (!c) return <p>Loading…</p>;
  return (
    <section>
      <a href="#/" className="text-sm underline">← Clusters</a>
      <div className="mb-4 mt-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium">{c.name} <HealthBadge status={c.health} />{" "}
          <OwnershipBadge value={c.ownership} /></h2>
        <div className="flex items-center gap-3">
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
          <button className="rounded border px-2 py-1 text-sm" onClick={syncNow}>Sync now</button>
        </div>
      </div>
      {(syncErr || c.last_sync_error) && (
        <p role="alert" className="mb-3 rounded bg-red-50 p-2 text-sm text-red-700">
          {syncErr ?? c.last_sync_error} (last successful sync {ago(c.last_sync_at)})</p>)}

      <div className="mb-4 grid gap-3 text-sm md:grid-cols-3">
        <div className="rounded border p-3"><h3 className="font-medium">Elasticsearch reports</h3>
          <p>Version {c.version} · {c.nodes} nodes ({c.data_nodes} data)</p>
          <p>Storage {c.storage.used_pct ?? "—"}% of {bytes(c.storage.total_bytes)}</p>
          <p className="font-mono text-xs">{c.uuid}</p></div>
        <div className="rounded border p-3"><h3 className="font-medium">Proxmox reports</h3>
          <p>Hosts: {c.infrastructure.proxmox_hosts.join(", ") || "none linked"}</p>
          <p>{c.infrastructure.verified_links}/{c.infrastructure.total_nodes} nodes verified to a VM</p></div>
        <div className="rounded border p-3"><h3 className="font-medium">Desired state</h3>
          <p>{c.desired.managed ? "Managed by this application" : "None"}</p>
          {c.desired.note && <p className="text-slate-500">{c.desired.note}</p>}</div>
      </div>

      <div role="tablist" className="mb-3 flex gap-1 border-b">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`px-3 py-1 text-sm ${tab === t ? "border-b-2 border-slate-900 font-medium" : ""}`}>{t}</button>))}
      </div>

      {tab === "Nodes" && (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead><tr><th>Node</th><th>Roles</th><th>Heap</th><th>Disk free</th><th>Shards</th><th>VM link</th></tr></thead>
          <tbody>{c.node_list.map((n) => (
            <tr key={n.id} className="border-t align-top">
              <td>{n.name}<div className="text-xs text-slate-500">{n.ip}</div></td>
              <td className="max-w-xs text-xs">{n.roles.join(", ") || "coordinating only"}</td>
              <td>{n.heap_used_pct ?? "—"}%</td>
              <td>{bytes(n.disk_avail_bytes)} / {bytes(n.disk_total_bytes)}</td>
              <td>{n.shard_count}</td>
              <td><LinkBadge confidence={n.link.confidence} />
                {n.link.vm && <div className="text-xs">{n.link.vm.pve_node} · VM {n.link.vm.vmid}</div>}
                {n.link.confidence === "unlinked" && n.link.evidence.reason === "ambiguous" &&
                  <div className="text-xs text-slate-500">ambiguous address</div>}</td>
            </tr>))}</tbody></table></div>)}

      {tab === "Shards" && (
        <div className="grid gap-4 text-sm md:grid-cols-2">
          <div><h3 className="font-medium">By state</h3>
            <ul>{Object.entries(c.elasticsearch.shards.by_state).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul>
            {c.elasticsearch.shards.unassigned.length > 0 && (
              <p className="mt-2 text-red-700">Unassigned: {c.elasticsearch.shards.unassigned.join(", ")}</p>)}</div>
          <div><h3 className="font-medium">Distribution by node</h3>
            <ul>{Object.entries(c.elasticsearch.shards.by_node).map(([k, v]) => <li key={k}>{k}: {v}</li>)}</ul></div>
        </div>)}

      {tab === "Settings" && (
        <pre className="overflow-x-auto rounded bg-slate-50 p-3 text-xs">
          {JSON.stringify(c.elasticsearch.settings, null, 2)}</pre>)}

      {tab === "Infrastructure" && (
        <table className="w-full text-left text-sm">
          <thead><tr><th>Node</th><th>Proxmox host</th><th>VM</th><th>vCPU</th><th>RAM</th><th>Disks</th></tr></thead>
          <tbody>{c.node_list.filter((n) => n.link.vm).map((n) => (
            <tr key={n.id} className="border-t"><td>{n.name}</td>
              <td>{n.link.vm!.pve_node}</td><td>{n.link.vm!.vmid} {n.link.vm!.name}</td>
              <td>{n.link.vm!.cpu_cores}</td><td>{n.link.vm!.memory_mb} MB</td>
              <td>{n.link.vm!.disks.map((d) => `${d.slot}:${d.size_gb ?? "?"}G`).join(" ")}</td></tr>))}</tbody>
        </table>)}

      {tab === "Operations" && <p className="text-sm text-slate-500">
        Operations and provisioning history for this cluster arrive with phases 4–5.</p>}
    </section>
  );
}
