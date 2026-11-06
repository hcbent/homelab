import {
  EuiBadge, EuiBasicTableColumn, EuiButton, EuiButtonEmpty, EuiCallOut, EuiEmptyPrompt,
  EuiInMemoryTable, EuiLink,
} from "@elastic/eui";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, ClusterSummary, Infrastructure } from "./api";
import { HealthBadge, OwnershipBadge } from "./Badges";
import { ago, storedNumber } from "./format";
import { RefreshControl } from "./RefreshControl";
import { StatTile } from "./StatTile";
import { useInterval } from "./useInterval";

const RANK: Record<string, number> = { green: 1, yellow: 2, red: 3 };

/** The fields a refresh can change; timestamps are excluded so every poll does not flag every row. */
function fingerprint(c: ClusterSummary) {
  return JSON.stringify([c.health, c.version, c.nodes, c.data_nodes, c.ownership, c.infrastructure,
    c.storage.used_pct, c.jvm_heap_used_pct, c.last_sync_error]);
}

export function Dashboard() {
  const [rows, setRows] = useState<ClusterSummary[] | null>(null);
  const [vms, setVms] = useState<number | null | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(() => storedNumber("ecm.refresh", 30));
  const [changed, setChanged] = useState<string[]>([]);
  const seen = useRef<Map<string, string>>(new Map());
  const timer = useRef<number>();

  const load = useCallback(() => {
    api<ClusterSummary[]>("/api/clusters").then((next) => {
      const before = seen.current;
      const after = new Map(next.map((c) => [c.id, fingerprint(c)]));
      const flagged = next.filter((c) => before.has(c.id) && before.get(c.id) !== after.get(c.id)).map((c) => c.id);
      seen.current = after;
      setRows(next);
      setLoadError(null);
      if (flagged.length) {
        setChanged(flagged);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setChanged([]), 1500);
      }
    }).catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
    api<Infrastructure>("/api/infrastructure")
      .then((d) => setVms(Array.isArray(d.vms) ? d.vms.length : null))
      .catch(() => setVms(null));
  }, []);
  useEffect(load, [load]);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useInterval(load, seconds);

  const loading = rows === null && !loadError;
  const list = rows ?? [];
  const nodeTotal = list.reduce((n, c) => n + c.nodes, 0);
  const worst = list.reduce<string | null>((w, c) => (RANK[c.health ?? ""] > (RANK[w ?? ""] ?? 0) ? c.health : w), null);
  const lastSync = list.map((c) => c.last_sync_at).filter(Boolean).sort().pop() ?? null;
  const empty = rows?.length === 0;

  const columns: EuiBasicTableColumn<ClusterSummary>[] = [
    { field: "name", name: "Name", sortable: true, render: (_: string, c: ClusterSummary) => (
      <div className="ecm-stack">
        <EuiLink href={`#/clusters/${c.id}`} className="ecm-mono ecm-nowrap">{c.name}</EuiLink>
        <div className="ecm-mono ecm-small ecm-clip" title={`Cluster UUID ${c.uuid ?? ""}`}>{c.uuid}</div>
      </div>) },
    { field: "health", name: "Health", sortable: true, render: (h: ClusterSummary["health"]) => <HealthBadge status={h} /> },
    { field: "version", name: "Version", render: (v: string | null) => v ? <EuiBadge color="hollow">{v}</EuiBadge> : "—" },
    { name: "Nodes (data)", sortable: (c: ClusterSummary) => c.nodes,
      render: (c: ClusterSummary) => `${c.nodes} (${c.data_nodes})` },
    { name: "Infrastructure", render: (c: ClusterSummary) => (
      <div className="ecm-stack">
        {c.infrastructure.proxmox_hosts.length
          ? <span className="ecm-mono">{c.infrastructure.proxmox_hosts.join(", ")}</span>
          : <span className="ecm-muted ecm-nowrap">Not linked</span>}
        <div className="ecm-small">{c.infrastructure.verified_links}/{c.infrastructure.total_nodes} nodes linked</div>
      </div>) },
    { field: "ownership", name: "Ownership", render: (o: string) => <OwnershipBadge value={o} /> },
    { name: "Last sync", sortable: (c: ClusterSummary) => c.last_sync_at ?? "", render: (c: ClusterSummary) => (
      <div className="ecm-stack">
        <span className="ecm-nowrap">{ago(c.last_sync_at)}</span>
        {c.last_sync_error && <div role="alert" className="ecm-error-text">{c.last_sync_error}</div>}
      </div>) },
  ];

  return (
    <>
      <section className="ecm-summary" aria-labelledby="summary-title">
        <div className="ecm-summary__intro">
          <h2 id="summary-title" className="ecm-h2">What the last sync saw.</h2>
          <p className="ecm-lede ecm-lede--small">
            Counts come from the most recent read-only sync of Proxmox and Elasticsearch.</p>
        </div>
        <div className="ecm-summary__tiles">
          <StatTile index={0} loading={loading} icon="cluster" label="Clusters" value={list.length}
            health={worst ? <HealthBadge status={worst} /> : undefined}
            description={empty
              ? <>Add a connection to start discovery. <EuiLink href="#/infrastructure">Go to Infrastructure</EuiLink></>
              : "Registered with ECM"} />
          <StatTile index={1} loading={loading} icon="compute" label="Nodes" value={nodeTotal}
            description={empty ? "Add a connection to start discovery." : "Seen in the last sync"} />
          <StatTile index={2} loading={loading || vms === undefined} icon="storage" label="Virtual machines"
            value={vms ?? "—"}
            description={vms === null ? "Not available: could not read Proxmox data."
              : empty ? "Add a connection to start discovery." : "Seen on Proxmox"} />
        </div>
        <div className="ecm-summary__caption">
          <span>Last sync {ago(lastSync)}</span>
          <RefreshControl seconds={seconds} onChange={setSeconds} onNow={load} />
        </div>
      </section>

      <section id="clusters" className="ecm-about" aria-labelledby="clusters-title">
        <p className="ecm-eyebrow"><span className="ecm-square" aria-hidden="true" />Clusters</p>
        <div className="ecm-about__main">
          <h2 id="clusters-title" className="ecm-h2">Every registered cluster, with the machines behind it.</h2>
          <p className="ecm-lede ecm-lede--small">Open a cluster to see its nodes, linked VMs and storage.</p>
          <div className="ecm-gap">
            <EuiButton fill iconType="plusInCircle" href="#/new">Create cluster</EuiButton>
          </div>
          {loadError && (
            <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load clusters"
              className="ecm-gap">
              <p>{loadError}</p>
              <EuiButton size="s" onClick={load}>Retry</EuiButton>
            </EuiCallOut>)}
          <div className="ecm-table">
            {empty ? (
              <EuiEmptyPrompt iconType="database" titleSize="s" title={<h3>No clusters registered</h3>}
                body={<p>Add a connection to start discovery.</p>}
                actions={<EuiButton fill href="#/infrastructure">Add connection</EuiButton>} />
            ) : (
              <>
                <div className="ecm-sr" role="status">
                  {changed.length ? `${changed.length} cluster${changed.length > 1 ? "s" : ""} updated` : ""}</div>
                <EuiInMemoryTable<ClusterSummary> tableCaption="Registered clusters" items={list} columns={columns}
                  loading={loading} itemId="id" sorting={{ sort: { field: "name", direction: "asc" } }}
                  search={{ box: { incremental: true, placeholder: "Search clusters", "aria-label": "Search clusters" } }}
                  rowProps={(c) => ({ className: changed.includes(c.id) ? "ecm-row-changed" : undefined })}
                  responsiveBreakpoint="m" tableLayout="auto" />
              </>)}
          </div>
          {!empty && <EuiButtonEmpty iconType="plusInCircle" href="#/infrastructure" className="ecm-gap">
            Add connection</EuiButtonEmpty>}
        </div>
      </section>
    </>
  );
}

