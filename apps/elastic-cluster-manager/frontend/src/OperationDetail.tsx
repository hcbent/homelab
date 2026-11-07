import {
  EuiBadge, EuiButton, EuiButtonEmpty, EuiCallOut, EuiDescriptionList, EuiHealth, EuiLink, EuiLoadingSpinner,
  EuiPanel, EuiProgress,
} from "@elastic/eui";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, OperationDetail as Detail, PlanSummary } from "./api";
import { ConfirmAction } from "./ConfirmAction";
import { useInterval } from "./useInterval";

const TERMINAL = ["succeeded", "failed", "cancelled"];
export const KIND: Record<string, string> = {
  "tf.create": "Create cluster", "tf.destroy": "Tear down cluster", "demo.noop": "Demo job",
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
  approval: "Wait for your approval", apply: "Make the changes on Proxmox", configure: "Install and start Elasticsearch",
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

function configured(result: Detail["result"]) {
  const c = result?.configured as { cluster_uuid?: string; status?: string; number_of_nodes?: number } | undefined;
  return c && typeof c === "object" ? c : null;
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
            { title: "On Proxmox", description: terraformText(op.kind, summary) },
            ...(summary?.configure
              ? [{ title: "Then", description: summary.configure.charAt(0).toUpperCase() + summary.configure.slice(1) }]
              : []),
            { title: "Plan digest", description: <span className="ecm-mono ecm-small ecm-clip">{op.plan.digest}</span> },
          ]} />
          {op.dry_run && (
            <EuiCallOut size="s" color="primary" iconType="info" className="ecm-gap"
              title="This was a dry run: nothing was created, and it cannot be approved.">
              <p>Go back and plan the build for real to get a plan you can approve.</p></EuiCallOut>)}
          {op.plan.approvable && (
            <div className="ecm-detail__actions">
              <EuiButton fill color={destroying ? "danger" : "primary"} isDisabled={busy}
                onClick={() => setConfirming(true)}>
                {destroying ? "Approve and destroy" : "Approve and build"}</EuiButton>
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
          {!op.dry_run && op.kind === "tf.create" && (
            <p>Machines it already made are kept. Retry resumes where it stopped. To remove them instead,{" "}
              {op.cluster_id
                ? <><EuiLink href={`#/clusters/${op.cluster_id}`}>open the cluster</EuiLink> and choose Tear down cluster.</>
                : <>run <span className="ecm-mono">scripts/ecm_cli.py cleanup {op.id} &lt;cluster name&gt;</span>.</>}</p>)}
          <EuiButton size="s" isDisabled={busy} onClick={() => act("retry")}>Retry</EuiButton>
        </EuiCallOut>)}

      {op.state === "succeeded" && op.kind === "tf.destroy" && (
        <EuiCallOut color="success" iconType="check" title="The cluster is torn down">
          <p>The machines are destroyed.{" "}
            {op.cluster_id
              ? <>ECM kept its record because something still blocks removing it: <EuiLink href={`#/clusters/${op.cluster_id}`}>open the cluster</EuiLink> to see what.</>
              : "ECM has removed its record of the cluster; this history stays."}</p></EuiCallOut>)}

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
            : <p>{terraformText(op.kind, summary)}.{summary?.configure
              ? ` Then ${summary.configure}.` : ""} This approves exactly the plan with this digest.</p>}
        </ConfirmAction>)}
    </section>
  );
}
