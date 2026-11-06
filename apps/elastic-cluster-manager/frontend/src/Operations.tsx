import {
  EuiBadge, EuiButton, EuiCallOut, EuiCodeBlock, EuiDescriptionList, EuiEmptyPrompt, EuiHealth, EuiLink,
  EuiLoadingSpinner, EuiProgress,
} from "@elastic/eui";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, Operation } from "./api";

const COLOR: Record<string, string> = {
  succeeded: "success", success: "success", completed: "success", done: "success",
  failed: "danger", error: "danger", running: "primary", pending: "subdued", queued: "subdued",
};
const color = (state: string) => COLOR[state.toLowerCase()] ?? "subdued";
const seconds = (n: number | null) => (n == null ? "—" : `${n}s`);

/** What the API reports for one operation, rendered as log lines. Nothing is invented. */
export function logLines(op: Operation): string {
  const lines = [`kind   ${op.kind}`, `state  ${op.state}`, `phase  ${op.phase ?? "—"}`, `time   ${seconds(op.elapsed_seconds)}`];
  if (op.error) lines.push(`error  ${op.error}`);
  return lines.join("\n");
}

function OperationCard({ op }: { op: Operation }) {
  const running = op.state.toLowerCase() === "running";
  return (
    <article className="ecm-op" aria-label={`Operation ${op.kind}`}>
      <div className="ecm-op__log">
        <EuiCodeBlock fontSize="s" paddingSize="m" isCopyable={false} overflowHeight={168} className="ecm-mono"
          aria-label="Operation log">{logLines(op)}</EuiCodeBlock>
      </div>
      <div className="ecm-op__head">
        <h3 className="ecm-op__title ecm-mono">{op.kind}</h3>
        {running ? <EuiLoadingSpinner size="m" aria-label="Running" /> : null}
        <EuiHealth color={color(op.state)}>{op.state}</EuiHealth>
        {op.dry_run && <EuiBadge color="hollow">dry run</EuiBadge>}
      </div>
      <p className="ecm-op__desc">{op.error ?? (op.phase ? `Current phase: ${op.phase}.` : "No phase reported yet.")}</p>
      <EuiLink href={`#/operations/${op.id}`}>Open details</EuiLink>
      <EuiDescriptionList compressed className="ecm-op__meta" type="column" columnWidths={[1, 1]}
        listItems={[
          { title: "Status", description: op.state },
          { title: "Phase", description: op.phase ?? "—" },
          { title: "Duration", description: seconds(op.elapsed_seconds) },
          { title: "Operation ID", description: <span className="ecm-mono ecm-small">{op.id}</span> },
        ]} />
      <div className="ecm-op__strip">{running ? <EuiProgress size="xs" color="primary" /> : <span className="ecm-op__rule" />}</div>
    </article>
  );
}

export function Operations() {
  const [ops, setOps] = useState<Operation[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Operation[]>("/api/operations").then((o) => { setOps(o); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  async function runDemo() {
    setRunError(null);
    try { await api("/api/operations/demo", { method: "POST" }); }
    catch (e) { setRunError(e instanceof ApiError ? e.message : String(e)); }
    load();
  }

  const list = ops ?? [];
  const idx = Math.max(0, list.findIndex((o) => o.id === picked));
  const current = list[idx];
  const prev = list[idx - 1];
  const next = list[idx + 1];
  const side = (op: Operation | undefined, label: string) => op && (
    <button type="button" className="ecm-op-side" onClick={() => setPicked(op.id)} aria-label={`${label}: ${op.kind}, ${op.state}`}>
      <span className="ecm-label">{label}</span>
      <span className="ecm-mono">{op.kind}</span>
      <EuiHealth color={color(op.state)}>{op.state}</EuiHealth>
    </button>);

  return (
    <section id="operations" className="ecm-ops" aria-labelledby="ops-title">
      <header className="ecm-ops__head">
        <h2 id="ops-title" className="ecm-h2">Operation log</h2>
        <p className="ecm-lede ecm-lede--small">Each ECM job reports its state and phase here. Secrets are redacted.</p>
        <EuiButton onClick={runDemo}>Run demo job</EuiButton>
      </header>
      {(loadError || runError) && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title={loadError ? "Could not load operations" : "Could not start the job"}>
          <p>{loadError ?? runError}</p>
          {loadError && <EuiButton size="s" onClick={load}>Retry</EuiButton>}
        </EuiCallOut>)}
      {ops === null && !loadError && <p role="status"><EuiLoadingSpinner size="m" /> Loading operations…</p>}
      {ops !== null && list.length === 0 && (
        <EuiEmptyPrompt iconType="clock" titleSize="s" title={<h3>No operations yet</h3>}
          body={<p>Jobs started from ECM appear here with their state and phase.</p>} />)}
      {current && (
        <div className="ecm-ops__rail">
          <div className="ecm-ops__side ecm-ops__side--prev">{side(prev, "Newer")}</div>
          <OperationCard op={current} />
          <div className="ecm-ops__side ecm-ops__side--next">{side(next, "Older")}</div>
        </div>)}
    </section>
  );
}
