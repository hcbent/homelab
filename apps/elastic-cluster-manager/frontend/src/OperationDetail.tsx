import {
  EuiBadge, EuiBasicTable, EuiBasicTableColumn, EuiButton, EuiButtonEmpty, EuiCallOut, EuiDescriptionList, EuiHealth,
  EuiLink, EuiLoadingSpinner, EuiPanel, EuiProgress,
} from "@elastic/eui";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, OperationDetail as Detail, PlanSummary } from "./api";
import { ConfirmAction } from "./ConfirmAction";
import { bytes } from "./format";
import { useInterval } from "./useInterval";

const TERMINAL = ["succeeded", "failed", "cancelled"];
export const KIND: Record<string, string> = {
  "tf.create": "Create cluster", "tf.destroy": "Tear down cluster", "tf.update": "Change cluster", "es.restart": "Restart nodes",
  "demo.noop": "Demo job",
};
const STATE_COLOR: Record<string, string> = {
  succeeded: "success", failed: "danger", running: "primary", pending_approval: "warning", cancelled: "subdued",
};
const STEP_COLOR: Record<string, string> = {
  done: "success", running: "primary", waiting: "warning", failed: "danger", pending: "subdued", cancelled: "subdued",
};
const STEP_STATUS: Record<string, string> = {
  done: "done", running: "running", waiting: "waiting for approval", failed: "failed", pending: "pending",
  cancelled: "cancelled",
};
const STEP_TEXT: Record<string, string> = {
  render: "Prepare the configuration", init: "Initialise Terraform", plan: "Plan the changes",
  approval: "Wait for your approval", restart: "Restart the nodes one at a time", drain: "Move the data off the nodes", apply: "Make the changes on Proxmox", configure: "Install and start Elasticsearch",
};
const MAX_LOG_LINES = 400;

const stateLabel = (state: string) => state.replace("_", " ").replace("pending approval", "waiting for approval");

export function duration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

/** What Terraform will do, in plain words. */
export function terraformText(kind: string, s: PlanSummary | null): string {
  if (!s) return "No plan yet";
  const parts: string[] = [];
  if (s.adds) parts.push(`create ${s.adds} virtual machine${s.adds > 1 ? "s" : ""}`);
  if (s.updates) parts.push(`change ${s.updates}`);
  if (s.deletes) parts.push(`destroy ${s.deletes} virtual machine${s.deletes > 1 ? "s" : ""}`);
  if (!parts.length) return kind === "tf.destroy" ? "Nothing left to destroy" : "No changes";
  const text = parts.join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** What a restart will do, in plain words. */
export function restartText(s: PlanSummary | null): string {
  const restart = s?.restart ?? 0;
  const start = s?.start ?? 0;
  const parts: string[] = [];
  if (restart) parts.push(`restart ${restart} node${restart > 1 ? "s" : ""}`);
  if (start) parts.push(`start ${start} node${start > 1 ? "s" : ""} that ${start > 1 ? "are" : "is"} down`);
  const text = parts.join(" and ") || "No nodes";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function configured(result: Detail["result"]) {
  const c = result?.configured as { cluster_uuid?: string; status?: string; number_of_nodes?: number } | undefined;
  return c && typeof c === "object" ? c : null;
}

interface AddedNode {
  name: string; host: string; address: string; vm_id: number; roles: string; cores: number; ram_mb: number;
  data_disk_gb: number | null;
}

/** Where each node an add-nodes change would make goes, with anything the placement wants the operator to know. */
function AddedNodes({ change, title = "Where each new node goes", first = "New node" }: {
  change: NonNullable<Detail["change"]>; title?: string; first?: string;
}) {
  const nodes = Object.entries((change.nodes ?? {}) as Record<string, Omit<AddedNode, "name">>)
    .map(([name, n]) => ({ name, ...n }));
  const columns: EuiBasicTableColumn<AddedNode>[] = [
    { name: first, render: (n: AddedNode) => <span className="ecm-mono">{n.name}</span> },
    { name: "Proxmox host", render: (n: AddedNode) => <span className="ecm-mono">{n.host}</span> },
    { name: "Address", render: (n: AddedNode) => <span className="ecm-mono">{n.address}</span> },
    { field: "vm_id", name: "VM ID" },
    { field: "roles", name: "Roles" },
    { name: "Size", render: (n: AddedNode) => `${n.cores} cores, ${n.ram_mb / 1024} GiB${n.data_disk_gb ? `, ${n.data_disk_gb} GB data` : ""}` },
  ];
  return (
    <div className="ecm-stack-lg">
      <h4 className="ecm-label">{title}</h4>
      <EuiBasicTable<AddedNode> tableCaption={title} items={nodes} columns={columns} rowHeader="name" />
      {(change.warnings ?? []).map((w) => (
        <EuiCallOut key={w} size="s" color="warning" iconType="warning" title={w} />))}
    </div>
  );
}

interface RemovedNode {
  name: string; host: string; address: string; vm_id: number; roles: string; cores: number; ram_mb: number;
  data_disk_gb: number | null; shards: number; data_bytes: number;
}

/** Which nodes a removal would destroy, where they run and how much data has to move off them first. */
function RemovedNodes({ change }: { change: NonNullable<Detail["change"]> }) {
  const nodes = Object.entries((change.nodes ?? {}) as Record<string, Omit<RemovedNode, "name">>)
    .map(([name, n]) => ({ name, ...n }));
  const columns: EuiBasicTableColumn<RemovedNode>[] = [
    { name: "Node to remove", render: (n: RemovedNode) => <span className="ecm-mono">{n.name}</span> },
    { name: "Proxmox host", render: (n: RemovedNode) => <span className="ecm-mono">{n.host}</span> },
    { name: "Address", render: (n: RemovedNode) => <span className="ecm-mono">{n.address}</span> },
    { field: "vm_id", name: "VM ID" },
    { field: "roles", name: "Roles" },
    { name: "Data to move", render: (n: RemovedNode) => (n.shards ? `${n.shards} shard${n.shards === 1 ? "" : "s"}, ${bytes(n.data_bytes)}` : "none") },
  ];
  return (
    <div className="ecm-stack-lg">
      <h4 className="ecm-label">The nodes this removes</h4>
      <EuiBasicTable<RemovedNode> tableCaption="The nodes this removes" items={nodes} columns={columns} rowHeader="name" />
      {(change.warnings ?? []).map((w) => (
        <EuiCallOut key={w} size="s" color="warning" iconType="warning" title={w} />))}
    </div>
  );
}

/** The lost nodes a forget takes out of the record: nothing on Proxmox changes, because their machines are already gone. */
function ForgottenNodes({ change }: { change: NonNullable<Detail["change"]> }) {
  const nodes = Object.entries((change.nodes ?? {}) as Record<string, Omit<AddedNode, "name">>)
    .map(([name, n]) => ({ name, ...n }));
  const columns: EuiBasicTableColumn<AddedNode>[] = [
    { name: "Node to forget", render: (n: AddedNode) => <span className="ecm-mono">{n.name}</span> },
    { name: "Was on", render: (n: AddedNode) => <span className="ecm-mono">{n.host}</span> },
    { name: "Address", render: (n: AddedNode) => <span className="ecm-mono">{n.address}</span> },
    { field: "vm_id", name: "VM ID" },
    { field: "roles", name: "Roles" },
  ];
  return (
    <div className="ecm-stack-lg">
      <h4 className="ecm-label">The lost nodes this forgets</h4>
      <EuiBasicTable<AddedNode> tableCaption="The lost nodes this forgets" items={nodes} columns={columns} rowHeader="name" />
    </div>
  );
}

interface PlannedNode {
  name: string; position: number; action: string; host: string | null; vm_id: number; roles: string;
}

/** The order a restart will go in, and what is done to each node: restarted, or started when it is down. */
function RestartOrder({ change }: { change: NonNullable<Detail["change"]> }) {
  const nodes = Object.entries((change.nodes ?? {}) as Record<string, Omit<PlannedNode, "name">>)
    .map(([name, n]) => ({ name, ...n })).sort((a, b) => a.position - b.position);
  const columns: EuiBasicTableColumn<PlannedNode>[] = [
    { field: "position", name: "Order" },
    { name: "Node", render: (n: PlannedNode) => <span className="ecm-mono">{n.name}</span> },
    { name: "What happens", render: (n: PlannedNode) => (n.action === "start" ? "Started (it is not in the cluster)" : "Restarted") },
    { name: "Proxmox host", render: (n: PlannedNode) => <span className="ecm-mono">{n.host}</span> },
    { field: "vm_id", name: "VM ID" },
    { field: "roles", name: "Roles" },
  ];
  return (
    <div className="ecm-stack-lg">
      <h4 className="ecm-label">The order the nodes go in</h4>
      <EuiBasicTable<PlannedNode> tableCaption="The order the nodes go in" items={nodes} columns={columns} rowHeader="name" />
      {(change.warnings ?? []).map((w) => (
        <EuiCallOut key={w} size="s" color="warning" iconType="warning" title={w} />))}
    </div>
  );
}

/** One operation: its steps, the plan and its digest, the actions that apply, the result and the log. */
export function OperationDetail({ id }: { id: string }) {
  const [op, setOp] = useState<Detail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const stick = useRef(true);

  const load = useCallback(() => {
    api<Detail>(`/api/operations/${id}`).then((o) => { setOp(o); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
  }, [id]);
  useEffect(load, [load]);
  const active = op === null || !TERMINAL.includes(op.state);
  useInterval(load, active ? 2 : 0);

  const logCount = op?.logs.length ?? 0;
  useEffect(() => {
    const el = logRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [logCount]);

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setActionError(null);
    try {
      await api(`/api/operations/${id}/${path}`, { method: "POST", body: body ? JSON.stringify(body) : undefined });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
      load();
    }
  }

  if (op === null) {
    return loadError
      ? <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load this operation">
        <p>{loadError}</p><EuiButton size="s" onClick={load}>Retry</EuiButton></EuiCallOut>
      : <p role="status"><EuiLoadingSpinner size="m" /> Loading operation…</p>;
  }

  const destroying = op.kind === "tf.destroy";
  const removing = op.kind === "tf.update" && op.change?.kind === "remove_nodes";
  const forgetting = op.kind === "tf.update" && op.change?.kind === "forget_nodes";
  const restarting = op.kind === "es.restart";
  const rebuilding = op.kind === "tf.update" && op.change?.kind === "rebuild_nodes";
  const drainFailed = op.steps.some((s) => s.name === "drain" && s.status === "failed");
  const summary = op.plan?.summary ?? null;
  const lines = op.logs.slice(-MAX_LOG_LINES);
  const hidden = op.logs.length - lines.length;
  const done = configured(op.result);

  return (
    <section className="ecm-detail" aria-labelledby="op-title">
      <header className="ecm-detail__head">
        <p className="ecm-eyebrow"><span className="ecm-square" aria-hidden="true" />Operation</p>
        <h2 id="op-title" className="ecm-h2">{KIND[op.kind] ?? op.kind}</h2>
        <div className="ecm-detail__meta">
          <EuiHealth color={STATE_COLOR[op.state] ?? "subdued"}>{stateLabel(op.state)}</EuiHealth>
          {op.dry_run && <EuiBadge color="hollow">dry run</EuiBadge>}
          {op.cluster_name && <span className="ecm-mono ecm-small" title="Cluster">{op.cluster_name}</span>}
          <span className="ecm-small">Elapsed {duration(op.elapsed_seconds)}</span>
          <span className="ecm-mono ecm-small" title="Operation ID">{op.id}</span>
        </div>
        {active
          ? <EuiProgress size="xs" color="primary"
            value={op.progress.total ? op.progress.done : undefined} max={op.progress.total || undefined}
            aria-label={`${op.progress.done} of ${op.progress.total} steps done`} />
          : <span className="ecm-op__rule" />}
      </header>

      {loadError && (
        <EuiCallOut color="warning" role="alert" iconType="warning" title="Could not refresh this operation" size="s">
          <p>{loadError}</p></EuiCallOut>)}

      <ol className="ecm-steps" aria-label="Steps">
        {op.steps.map((step) => (
          <li key={step.seq} className="ecm-step">
            <EuiHealth color={STEP_COLOR[step.status] ?? "subdued"}>
              <span className="ecm-step__name">{STEP_TEXT[step.name] ?? step.name}</span>{" "}
              <span className="ecm-small">{STEP_STATUS[step.status] ?? step.status}</span>
            </EuiHealth>
            {step.detail && <div role="alert" className="ecm-error-text">{step.detail}</div>}
          </li>))}
      </ol>

      {op.plan && (
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-plan"
          aria-label="The plan">
          <h3 className="ecm-h3">The plan</h3>
          <EuiDescriptionList type="column" compressed listItems={[
            { title: restarting ? "What happens" : "On Proxmox",
              description: restarting ? restartText(summary) : forgetting ? "Nothing: the machines are already gone" : terraformText(op.kind, summary) },
            ...(summary?.configure
              ? [{ title: "Then", description: summary.configure.charAt(0).toUpperCase() + summary.configure.slice(1) }]
              : []),
            { title: "Plan digest", description: <span className="ecm-mono ecm-small ecm-clip">{op.plan.digest}</span> },
          ]} />
          {op.change?.kind === "add_node" && <AddedNodes change={op.change} />}
          {op.change?.kind === "remove_nodes" && <RemovedNodes change={op.change} />}
          {op.change?.kind === "restart_nodes" && <RestartOrder change={op.change} />}
          {op.change?.kind === "rebuild_nodes" && <AddedNodes change={op.change} title="The nodes this rebuilds" first="Lost node" />}
          {op.change?.kind === "forget_nodes" && <ForgottenNodes change={op.change} />}
          {op.dry_run && (
            <EuiCallOut size="s" color="primary" iconType="info" className="ecm-gap"
              title="This was a dry run: nothing was created, and it cannot be approved.">
              <p>Go back and plan the build for real to get a plan you can approve.</p></EuiCallOut>)}
          {op.plan.approvable && (
            <div className="ecm-detail__actions">
              <EuiButton fill color={destroying || removing ? "danger" : "primary"} isDisabled={busy}
                onClick={() => setConfirming(true)}>
                {destroying ? "Approve and destroy" : removing ? "Approve and remove" : forgetting ? "Approve and forget" : restarting ? "Approve and restart"
                  : rebuilding ? "Approve and rebuild" : op.kind === "tf.update" ? "Approve the change" : "Approve and build"}</EuiButton>
              <EuiButtonEmpty isDisabled={busy} onClick={() => act("cancel")}>Cancel</EuiButtonEmpty>
              <span className="ecm-small">Nothing changes until you approve.</span>
            </div>)}
        </EuiPanel>)}

      {actionError && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work">
          <p>{actionError}</p></EuiCallOut>)}

      {op.state === "failed" && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="This operation failed">
          <p>{op.error}</p>
          {restarting && (
            <p>Nodes already restarted stay restarted. Retry plans again and needs a new approval; it skips every node that has been restarted
              since this operation began.</p>)}
          {!op.dry_run && op.kind === "tf.update" && (
            forgetting ? (
              <p>Nothing was destroyed, because the machines were already gone. Retry plans again and needs a new approval.</p>
            ) : rebuilding ? (
              <p>{"What Terraform already made is kept, so the rebuilt machines exist. Retry configures them again, which is safe to repeat."}</p>
            ) : removing ? (
              <p>{drainFailed
                ? "Nothing was destroyed: the data is moved off the nodes first, and the nodes are ordinary members of the cluster again. Retry plans the removal again and needs a new approval."
                : "Once the machines were destroyed they stay gone. If the apply failed, nothing is forgotten and Retry plans again; if a later step failed, Retry runs the rest."}</p>
            ) : (
            <p>What Terraform already changed is kept{op.change?.kind === "add_node"
              ? ", so the new machines exist. Retry configures them again, which is safe to repeat"
              : op.change?.kind === "resize"
              ? ", and so is every node already restarted. Retry plans again and carries on with the nodes not yet at their new size"
              : ". Retry plans again and runs the rest"}.</p>))}
          {!op.dry_run && op.kind === "tf.create" && (
            <p>Machines it already made are kept. Retry resumes where it stopped. To remove them instead,{" "}
              {op.cluster_id
                ? <><EuiLink href={`#/clusters/${op.cluster_id}`}>open the cluster</EuiLink> and choose Tear down cluster.</>
                : <>run <span className="ecm-mono">scripts/ecm_cli.py cleanup {op.id} &lt;cluster name&gt;</span>.</>}</p>)}
          {op.dry_run
            ? <p>A dry run is not retried. Go back to the wizard and plan again; that starts clean.</p>
            : <EuiButton size="s" isDisabled={busy} onClick={() => act("retry")}>Retry</EuiButton>}
        </EuiCallOut>)}

      {op.state === "succeeded" && op.kind === "tf.destroy" && (
        <EuiCallOut color="success" iconType="check" title="The cluster is torn down">
          <p>The machines are destroyed.{" "}
            {op.cluster_id
              ? <>ECM kept its record because something still blocks removing it: <EuiLink href={`#/clusters/${op.cluster_id}`}>open the cluster</EuiLink> to see what.</>
              : "ECM has removed its record of the cluster; this history stays."}</p></EuiCallOut>)}

      {op.state === "succeeded" && op.kind === "tf.update" && op.change?.kind === "resize" && (
        <EuiCallOut color="success" iconType="check" title="Every node has its new size">
          <p>Terraform changed the machines' configuration and ECM restarted the nodes one at a time. The cluster is
            green.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && op.kind === "tf.update" && op.change?.kind === "add_node" && (
        <EuiCallOut color="success" iconType="check" title="The new nodes joined the cluster">
          <p>ECM configured and started only the new nodes, and the cluster is green. The existing nodes were not touched.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && restarting && (
        <EuiCallOut color="success" iconType="check" title="The nodes are restarted">
          <p>Each node in the plan was restarted (or started) in turn, with the cluster green between them.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && rebuilding && (
        <EuiCallOut color="success" iconType="check" title="The rebuilt nodes joined the cluster">
          <p>Terraform made their machines again, and ECM configured and started only those nodes. The cluster is not red; the
            nodes' empty disks fill from the others, which can take a while.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && forgetting && (
        <EuiCallOut color="success" iconType="check" title="The lost nodes are forgotten">
          <p>ECM took them out of its record and brought the nodes that remain in line with it. Nothing was destroyed.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && removing && (
        <EuiCallOut color="success" iconType="check" title="The nodes are removed">
          <p>Elasticsearch moved the data off them, Terraform destroyed their machines, and the cluster is green with the
            nodes that remain.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && op.kind === "tf.update"
        && op.change?.kind !== "resize" && op.change?.kind !== "add_node" && op.change?.kind !== "remove_nodes"
        && op.change?.kind !== "rebuild_nodes" && op.change?.kind !== "forget_nodes" && (
        <EuiCallOut color="success" iconType="check" title="The change is applied">
          <p>It is applied on every node. Sizes and free space on the cluster page come from the last sync, which runs
            every few minutes; press Sync now there to see them at once.{" "}
            {op.cluster_id && <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink>}</p></EuiCallOut>)}

      {op.state === "succeeded" && done && op.cluster_id && (
        <EuiCallOut color="success" iconType="check" title="The cluster is up">
          <p>{done.number_of_nodes} nodes, {done.status}.{" "}
            <EuiLink href={`#/clusters/${op.cluster_id}`}>Open the cluster</EuiLink></p></EuiCallOut>)}

      <div className="ecm-detail__log">
        <h3 className="ecm-label">Log</h3>
        <pre ref={logRef} className="ecm-log ecm-mono" tabIndex={0} aria-label="Operation log"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
          }}>
          {lines.length
            ? lines.map((l) => `[${l.stream}] ${l.line}`).join("\n")
            : "No log lines yet."}
        </pre>
        <p className="ecm-small">
          {hidden > 0 ? `${hidden} earlier lines are not shown. ` : ""}Secrets are redacted before they are stored.</p>
      </div>

      {confirming && op.plan && (
        <ConfirmAction action="Approve" resource={destroying ? op.plan.digest.slice(0, 8) : `plan ${op.plan.digest.slice(0, 8)}`}
          destructive={destroying} onCancel={() => setConfirming(false)}
          onConfirm={() => { setConfirming(false); act("approve", { digest: op.plan!.digest }); }}>
          {destroying
            ? <p>{terraformText(op.kind, summary)}. The machines and anything stored on them are gone for good.</p>
            : restarting
            ? <p>{restartText(summary)}. Each node is briefly out of the cluster, and ECM waits for the cluster to be green before each. This
              approves exactly the plan with this digest.</p>
            : forgetting
            ? <p>Nothing is destroyed: the machines are already gone. ECM takes the nodes out of its record. This approves exactly
              the plan with this digest.</p>
            : removing
            ? <p>Elasticsearch moves the data off the nodes first. Then {terraformText(op.kind, summary).toLowerCase()}, and
              their disks go with them for good. This approves exactly the plan with this digest.</p>
            : <p>{terraformText(op.kind, summary)}.{summary?.configure
              ? ` Then ${summary.configure}.` : ""} This approves exactly the plan with this digest.</p>}
        </ConfirmAction>)}
    </section>
  );
}
