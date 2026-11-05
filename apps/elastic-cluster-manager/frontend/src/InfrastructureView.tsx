import {
  EuiBasicTable, EuiBasicTableColumn, EuiButton, EuiCallOut, EuiHealth, EuiIcon, EuiLink, EuiLoadingSpinner,
  EuiPanel,
} from "@elastic/eui";
import { CSSProperties, ReactNode, useCallback, useEffect, useState } from "react";
import { AddConnection, ConnectionType } from "./AddConnection";
import { NetworkSettings } from "./NetworkSettings";
import { api, ApiError, ClusterSummary, Infrastructure, Vm } from "./api";
import { HealthBadge } from "./Badges";
import { ago, bytes, cpuText, memText, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { useReveals } from "./reveal";
import { useInterval } from "./useInterval";

type Host = Infrastructure["nodes"][number];
type Pool = Infrastructure["storages"][number];

function ConnectionPanel({ icon, title, subtitle, count, index, action, children }: {
  icon: string; title: string; subtitle: string; count: number; index: number; action: ReactNode; children: ReactNode;
}) {
  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="rise"
      data-reveal-delay={index * 80} className="ecm-connection" style={{ "--i": index } as CSSProperties}>
      <span className="ecm-seat ecm-seat--small" aria-hidden="true"><EuiIcon type={icon} /></span>
      <h3 className="ecm-connection__title">{title}</h3>
      <p className="ecm-label">{subtitle}</p>
      <p className="ecm-connection__count"><span className="ecm-numeral">{count}</span>
        <span className="ecm-label">/connections</span></p>
      <div className="ecm-connection__list">{children}</div>
      {action}
    </EuiPanel>
  );
}

export function InfrastructureView() {
  const [d, setD] = useState<Infrastructure | null>(null);
  const [clusters, setClusters] = useState<ClusterSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [type, setType] = useState<ConnectionType>("proxmox");
  const load = useCallback(() => {
    api<Infrastructure>("/api/infrastructure").then((x) => { setD(x); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
    api<ClusterSummary[]>("/api/clusters").then(setClusters).catch(() => setClusters(null));
  }, []);
  useEffect(load, [load]);
  useInterval(load, seconds);
  useReveals(d !== null);

  function choose(t: ConnectionType) {
    setType(t);
    const target = document.getElementById("add-connection");
    const calm = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    target?.scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
    target?.querySelector<HTMLElement>("select")?.focus({ preventScroll: true });
  }

  if (!d) {
    return loadError ? (
      <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load infrastructure">
        <p>{loadError}</p><EuiButton size="s" onClick={load}>Retry</EuiButton>
      </EuiCallOut>
    ) : <p role="status"><EuiLoadingSpinner size="m" /> Loading infrastructure…</p>;
  }

  const hostColumns: EuiBasicTableColumn<Host>[] = [
    { name: "Host", render: (n: Host) => <span className="ecm-mono">{n.name}</span> },
    { field: "status", name: "Status" },
    { name: "CPU", render: (n: Host) => <span className={n.usage.cpu == null ? "ecm-muted" : undefined}>{cpuText(n.usage)}</span> },
    { name: "Memory", render: (n: Host) => <span className={n.usage.mem == null ? "ecm-muted" : undefined}>{memText(n.usage)}</span> },
  ];
  const poolColumns: EuiBasicTableColumn<Pool>[] = [
    { name: "Host", render: (s: Pool) => <span className="ecm-mono">{s.node}</span> },
    { name: "Pool", render: (s: Pool) => <span className="ecm-mono">{s.name}{s.shared ? " (shared)" : ""}</span> },
    { field: "type", name: "Type" },
    { name: "Used", render: (s: Pool) => bytes(s.used) },
    { name: "Free", render: (s: Pool) => bytes(s.avail) },
  ];
  const vmColumns: EuiBasicTableColumn<Vm>[] = [
    { name: "VM", render: (v: Vm) => <span className="ecm-mono">{v.vmid} {v.name}</span> },
    { name: "Host", render: (v: Vm) => <span className="ecm-mono">{v.pve_node}</span> },
    { field: "status", name: "Status" },
    { field: "cpu_cores", name: "vCPU" },
    { name: "RAM", render: (v: Vm) => `${v.memory_mb} MB` },
    { name: "Addresses", render: (v: Vm) => <span className="ecm-mono ecm-small">{v.ips.map((i) => i.ip).join(", ")}</span> },
    { name: "Elasticsearch", render: (v: Vm) => v.es_cluster_id
      ? <EuiLink href={`#/clusters/${v.es_cluster_id}`}>{v.es_link}</EuiLink> : "—" },
  ];

  return (
    <>
      <section id="infrastructure" className="ecm-pricing" aria-labelledby="infra-title">
        <h2 id="infra-title" className="ecm-h2 ecm-h2--center">Where ECM reads from.</h2>
        <div className="ecm-pricing__toolbar">
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
        </div>
        <div className="ecm-pricing__panels">
          <ConnectionPanel index={0} icon="compute" title="Proxmox" subtitle="VMs, hosts and storage"
            count={d.connections.length}
            action={<EuiButton fill fullWidth onClick={() => choose("proxmox")}>Add Proxmox connection</EuiButton>}>
            {d.connections.length === 0 && <p className="ecm-muted">No connections yet.</p>}
            <ul className="ecm-rows">
              {d.connections.map((c) => (
                <li key={c.id}>
                  <EuiHealth color={c.last_sync_error ? "danger" : "success"}>
                    <span className="ecm-mono">{c.name}</span></EuiHealth>
                  <span className="ecm-mono ecm-small">{c.api_url}</span>
                  <span className="ecm-small">Synced {ago(c.last_sync_at)}</span>
                  {c.last_sync_error && <span role="alert" className="ecm-error-text">{c.last_sync_error}</span>}
                </li>))}
            </ul>
          </ConnectionPanel>
          <ConnectionPanel index={1} icon="cluster" title="Elasticsearch" subtitle="Clusters and nodes"
            count={clusters?.length ?? 0}
            action={<EuiButton fullWidth onClick={() => choose("elasticsearch")}>Add Elasticsearch connection</EuiButton>}>
            {clusters === null && <p className="ecm-muted"><strong>Not available.</strong> Could not read registered clusters.</p>}
            {clusters?.length === 0 && <p className="ecm-muted">No connections yet.</p>}
            <ul className="ecm-rows">
              {clusters?.map((c) => (
                <li key={c.id}>
                  <div className="ecm-inline"><EuiLink href={`#/clusters/${c.id}`} className="ecm-mono">{c.name}</EuiLink>
                    <HealthBadge status={c.health} /></div>
                  <span className="ecm-small">{c.nodes} nodes · synced {ago(c.last_sync_at)}</span>
                  {c.last_sync_error && <span role="alert" className="ecm-error-text">{c.last_sync_error}</span>}
                </li>))}
            </ul>
          </ConnectionPanel>
        </div>
      </section>

      <AddConnection type={type} onTypeChange={setType} onDone={load} />

      <NetworkSettings />

      <section className="ecm-inventory" aria-labelledby="inventory-title">
        <h2 id="inventory-title" className="ecm-h2">Proxmox inventory</h2>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="slide">
          <h3 className="ecm-h3">Hosts</h3>
          <EuiBasicTable tableCaption="Proxmox hosts" items={d.nodes} columns={hostColumns} responsiveBreakpoint="m"
            noItemsMessage="No hosts reported." />
        </EuiPanel>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="slide">
          <h3 className="ecm-h3">Storage</h3>
          <EuiBasicTable tableCaption="Proxmox storage" items={d.storages} columns={poolColumns} responsiveBreakpoint="m"
            noItemsMessage="No storage reported." />
        </EuiPanel>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="rise">
          <h3 className="ecm-h3">Templates</h3>
          {d.templates.length === 0 ? <p className="ecm-muted">None found.</p> : (
            <ul className="ecm-plain">{d.templates.map((t) =>
              <li key={t.id} className="ecm-mono">VM {t.vmid} · {t.name} · {t.pve_node}</li>)}</ul>)}
        </EuiPanel>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" data-reveal="rise">
          <h3 className="ecm-h3">Virtual machines</h3>
          <EuiBasicTable tableCaption="Proxmox virtual machines" items={d.vms} columns={vmColumns}
            responsiveBreakpoint="m" noItemsMessage="No virtual machines reported." />
        </EuiPanel>
      </section>
    </>
  );
}
