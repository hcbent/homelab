import {
  EuiBasicTable, EuiBasicTableColumn, EuiButton, EuiCallOut, EuiCodeBlock, EuiDescriptionList, EuiHealth,
  EuiIcon, EuiLink, EuiLoadingSpinner, EuiPanel, EuiTab, EuiTabs, EuiText,
} from "@elastic/eui";
import { CSSProperties, ReactNode, useCallback, useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, NodeRow } from "./api";
import { HealthBadge, LinkBadge, OwnershipBadge } from "./Badges";
import { ClusterLifecycle, ClusterOperations } from "./ClusterLifecycle";
import { AddNodes } from "./AddNodes";
import { Kibana } from "./Kibana";
import { GrowDisks } from "./GrowDisks";
import { Recovery } from "./Recovery";
import { rolesText } from "./roles";
import { RemoveNodes } from "./RemoveNodes";
import { Resize } from "./Resize";
import { RestartNodes } from "./RestartNodes";
import { ago, bytes, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { useReveals } from "./reveal";
import { useInterval } from "./useInterval";

const TABS = ["Nodes", "Shards", "Settings", "Infrastructure", "Operations"] as const;
type Tab = (typeof TABS)[number];

/** Up to three roles with their node counts; nodes with no roles are coordinating only. */
function roleCounts(nodes: NodeRow[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const n of nodes) {
    for (const r of n.roles.length ? n.roles : ["coordinating only"]) counts.set(r, (counts.get(r) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
}

function Card({ area, icon, title, index, children }: {
  area: string; icon: string; title: string; index: number; children: ReactNode;
}) {
  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="rise"
      data-reveal-delay={index * 80} className={`ecm-card ecm-card--${area}`}
      style={{ "--i": index } as CSSProperties}>
      <header className="ecm-card__head">
        <span className="ecm-seat ecm-seat--small" aria-hidden="true"><EuiIcon type={icon} /></span>
        <h3 className="ecm-card__title">{title}</h3>
      </header>
      {children}
    </EuiPanel>
  );
}

const NotAvailable = ({ why }: { why: string }) => (
  <p className="ecm-muted"><strong>Not available.</strong> {why}</p>);

export function ClusterDetailView({ id }: { id: string }) {
  const [c, setC] = useState<ClusterDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Nodes");
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const load = useCallback(() => {
    api<ClusterDetail>(`/api/clusters/${id}`).then((d) => { setC(d); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
  }, [id]);
  useEffect(load, [load]);
  useInterval(load, seconds);
  useReveals(c !== null);

  async function syncNow() {
    setSyncErr(null);
    setSyncing(true);
    try {
      const out = await api<{ proxmox_error?: string | null }>(`/api/clusters/${id}/sync`, { method: "POST" });
      if (out?.proxmox_error) setSyncErr(out.proxmox_error);       // Elasticsearch was read; Proxmox was not, and the page says so
    } catch (e) { setSyncErr(e instanceof ApiError ? e.message : String(e)); }
    setSyncing(false);
    load();
  }

  if (!c) {
    return loadError ? (
      <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load this cluster">
        <p>{loadError}</p>
        <EuiButton size="s" onClick={load}>Retry</EuiButton>{" "}
        <EuiLink href="#/">Back to clusters</EuiLink>
      </EuiCallOut>
    ) : <p role="status"><EuiLoadingSpinner size="m" /> Loading cluster…</p>;
  }

  const linked = c.node_list.filter((n) => n.link.vm);
  const roles = roleCounts(c.node_list);
  const syncFailed = Boolean(syncErr || c.last_sync_error);

  const nodeColumns: EuiBasicTableColumn<NodeRow>[] = [
    { name: "Node", render: (n: NodeRow) => (
      <div className="ecm-stack"><span className="ecm-mono">{n.name}</span><div className="ecm-mono ecm-small">{n.ip}</div></div>) },
    { name: "Roles", render: (n: NodeRow) => <span className="ecm-small" title={n.roles.join(", ")}>{rolesText(n.roles)}</span> },
    { name: "Heap", render: (n: NodeRow) => `${n.heap_used_pct ?? "—"}%` },
    { name: "Disk free", render: (n: NodeRow) => `${bytes(n.disk_avail_bytes)} / ${bytes(n.disk_total_bytes)}` },
    { field: "shard_count", name: "Shards" },
    { name: "VM link", render: (n: NodeRow) => (
      <div className="ecm-stack">
        <LinkBadge confidence={n.link.confidence} />
        {n.link.vm && <div className="ecm-small ecm-mono">{n.link.vm.pve_node} · VM {n.link.vm.vmid}</div>}
        {n.link.confidence === "unlinked" && n.link.evidence.reason === "ambiguous" &&
          <div className="ecm-small">ambiguous address</div>}
      </div>) },
  ];
  const vmColumns: EuiBasicTableColumn<NodeRow>[] = [
    { name: "Node", render: (n: NodeRow) => <span className="ecm-mono">{n.name}</span> },
    { name: "Proxmox host", render: (n: NodeRow) => <span className="ecm-mono">{n.link.vm!.pve_node}</span> },
    { name: "VM", render: (n: NodeRow) => <span className="ecm-mono">{n.link.vm!.vmid} {n.link.vm!.name}</span> },
    { name: "vCPU", render: (n: NodeRow) => n.link.vm!.cpu_cores },
    { name: "RAM", render: (n: NodeRow) => `${n.link.vm!.memory_mb} MB` },
    { name: "Disks", render: (n: NodeRow) =>
      <span className="ecm-mono ecm-small">{n.link.vm!.disks.map((d) => `${d.slot}:${d.size_gb ?? "?"}G`).join(" ")}</span> },
  ];

  return (
    <section aria-labelledby="detail-title">
      <EuiLink href="#/" className="ecm-back">← Clusters</EuiLink>
      <div className="ecm-detail-bar">
        <div className="ecm-title">
          <h1 id="detail-title" className="ecm-title__name ecm-mono">{c.name}</h1>
          <div className="ecm-title__badges"><HealthBadge status={c.health} /><OwnershipBadge value={c.ownership} /></div>
        </div>
        <div className="ecm-detail-bar__actions">
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
          <EuiButton onClick={syncNow} isLoading={syncing}>Sync now</EuiButton>
        </div>
      </div>
      {syncFailed && (
        <EuiCallOut color="danger" role="alert" iconType="warning" size="s" className="ecm-gap"
          title={`${syncErr ?? c.last_sync_error} (last successful sync ${ago(c.last_sync_at)})`} />)}

      <div className="ecm-feature-head">
        <h2 className="ecm-h2">Inside this cluster.</h2>
        <p className="ecm-lede ecm-lede--small">Health, nodes, linked VMs and storage from the last sync.</p>
      </div>

      <div className="ecm-bento">
        <Card area="nodes" icon="compute" title="Nodes" index={0}>
          <div className="ecm-card__value">
            <span className="ecm-card__numeral">{c.nodes}</span><HealthBadge status={c.health} />
          </div>
          <p className="ecm-card__desc">{c.data_nodes} data nodes · Elasticsearch {c.version ?? "version unknown"}
            {c.jvm_heap_used_pct != null && <> · JVM heap {c.jvm_heap_used_pct}%</>}</p>
          {roles.length > 0 && <EuiDescriptionList compressed type="column" className="ecm-roles"
            listItems={roles.map(([role, n]) => ({ title: role, description: `${n} ${n === 1 ? "node" : "nodes"}` }))} />}
          {c.uuid && <p className="ecm-mono ecm-small">{c.uuid}</p>}
        </Card>
        <Card area="vms" icon="storage" title="Virtual machines" index={1}>
          <div className="ecm-card__value"><span className="ecm-card__numeral">{linked.length}</span>
            <span className="ecm-small">of {c.infrastructure.total_nodes} nodes linked to a VM</span></div>
          <p className="ecm-card__desc">Proxmox hosts: {c.infrastructure.proxmox_hosts.join(", ") || "none linked"}</p>
          {linked.length > 0 && (
            <ul className="ecm-chips">
              {linked.slice(0, 4).map((n) => <li key={n.id} className="ecm-mono">{n.link.vm!.name}</li>)}
            </ul>)}
        </Card>
        <Card area="storage" icon="database" title="Storage" index={2}>
          {c.storage.used_pct == null
            ? <NotAvailable why="Elasticsearch did not report storage in the last sync." />
            : (<>
              <div className="ecm-card__value"><span className="ecm-card__numeral">{c.storage.used_pct}%</span></div>
              <p className="ecm-card__desc">used of {bytes(c.storage.total_bytes)}</p>
            </>)}
        </Card>
        <Card area="sync" icon="clock" title="Last sync" index={3}>
          <div className="ecm-card__value"><span className="ecm-card__numeral ecm-card__numeral--text">{ago(c.last_sync_at)}</span></div>
          <div className="ecm-card__desc">
            <EuiHealth color={c.last_sync_error ? "danger" : "success"}>
              {c.last_sync_error ? "Failed" : "Succeeded"}</EuiHealth></div>
        </Card>
      </div>

      <EuiText size="s" className="ecm-desired">
        <strong>Desired state:</strong> {c.desired.managed ? "Managed by this application" : "None"}
        {c.desired.note && <span className="ecm-muted"> · {c.desired.note}</span>}
      </EuiText>

      <EuiTabs className="ecm-tabs" aria-label="Cluster detail sections">
        {TABS.map((t) => (
          <EuiTab key={t} isSelected={tab === t} onClick={() => setTab(t)}>{t}</EuiTab>))}
      </EuiTabs>

      <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-tabpanel" data-reveal="slide">
        {tab === "Nodes" && (
          <EuiBasicTable tableCaption="Nodes" items={c.node_list} columns={nodeColumns} responsiveBreakpoint="m"
            noItemsMessage="No nodes were reported in the last sync." />)}

        {tab === "Shards" && (
          <div className="ecm-two">
            <div><h3 className="ecm-h3">By state</h3>
              <EuiDescriptionList type="column" compressed
                listItems={Object.entries(c.elasticsearch.shards.by_state).map(([k, v]) => ({ title: k, description: String(v) }))} />
              {c.elasticsearch.shards.unassigned.length > 0 && (
                <div className="ecm-gap"><EuiHealth color="danger">
                  Unassigned: {c.elasticsearch.shards.unassigned.join(", ")}</EuiHealth></div>)}
            </div>
            <div><h3 className="ecm-h3">Distribution by node</h3>
              <EuiDescriptionList type="column" compressed
                listItems={Object.entries(c.elasticsearch.shards.by_node).map(([k, v]) => ({ title: k, description: String(v) }))} />
            </div>
          </div>)}

        {tab === "Settings" && (
          <EuiCodeBlock language="json" isCopyable={false} overflowHeight={420} paddingSize="m">
            {JSON.stringify(c.elasticsearch.settings, null, 2)}</EuiCodeBlock>)}

        {tab === "Infrastructure" && (
          <EuiBasicTable tableCaption="Linked virtual machines" items={linked} columns={vmColumns} responsiveBreakpoint="m"
            noItemsMessage="No nodes are linked to a VM yet." />)}

        {tab === "Operations" && <ClusterOperations clusterId={c.id} />}
      </EuiPanel>

      <AddNodes cluster={c} />
      <RemoveNodes cluster={c} />
      <Recovery cluster={c} />
      <Resize cluster={c} />
      <RestartNodes cluster={c} />
      <GrowDisks cluster={c} />
      <Kibana cluster={c} />
      <ClusterLifecycle cluster={c} />
    </section>
  );
}
