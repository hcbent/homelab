import {
  EuiButton, EuiCallOut, EuiCheckboxGroup, EuiFieldNumber, EuiFormRow, EuiLink, EuiPanel,
} from "@elastic/eui";
import { useState } from "react";
import { api, ApiError, ClusterDetail } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const MAX_GB = 65536;
const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/**
 * Grow the data disks of a cluster ECM built. It only asks ECM to plan the change: the plan is approved on its
 * operation page, and a disk can only ever be grown, never shrunk. What is offered comes from the API's `lifecycle`.
 */
export function GrowDisks({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const disks = life?.data_disks ?? {};
  const names = Object.keys(disks).sort();
  const [size, setSize] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [touched, setTouched] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!life?.managed || names.length === 0) return null;

  const chosen = names.filter((n) => picked[n] ?? true);
  const largest = Math.max(0, ...chosen.map((n) => disks[n]));
  const whole = /^\d+$/.test(size.trim()) ? Number(size) : NaN;
  const problem = chosen.length === 0 ? "Choose at least one node."
    : Number.isNaN(whole) ? "Enter a whole number of GB."
    : whole <= largest ? `Must be larger than ${largest} GB, the biggest of the chosen disks. A disk can only be grown.`
    : whole > MAX_GB ? `At most ${MAX_GB} GB.` : null;

  async function plan() {
    setAsking(false);
    setError(null);
    try {
      const body: { data_disk_gb: number; nodes?: string[] } = { data_disk_gb: whole };
      if (chosen.length < names.length) body.nodes = chosen;
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/expand-disk`, {
        method: "POST", body: JSON.stringify(body),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="grow-title">
      <h3 id="grow-title" className="ecm-h3">Grow data disks</h3>
      <p>Current sizes: {names.map((n, i) => (
        <span key={n}>{i > 0 && ", "}<span className="ecm-mono">{n}</span> {disks[n]} GB</span>))}.
        A disk can only be grown, never shrunk. ECM grows the disk, the partition and the filesystem, and nothing
        restarts.</p>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work" size="s">
          <p>{error}</p></EuiCallOut>)}

      {life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before changing the disks.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          {names.length > 1 && (
            <EuiFormRow label="Nodes" fullWidth>
              <EuiCheckboxGroup options={names.map((n) => ({ id: n, label: `${n} (${disks[n]} GB)` }))}
                idToSelectedMap={Object.fromEntries(names.map((n) => [n, picked[n] ?? true]))}
                onChange={(id) => setPicked({ ...Object.fromEntries(names.map((n) => [n, picked[n] ?? true])),
                  [id]: !(picked[id] ?? true) })} />
            </EuiFormRow>)}
          <EuiFormRow label="New size of each chosen disk (GB)" isInvalid={touched && !!problem}
            error={touched ? problem ?? undefined : undefined}>
            <EuiFieldNumber value={size} isInvalid={touched && !!problem} onBlur={() => setTouched(true)}
              onChange={(e) => setSize(e.target.value)} />
          </EuiFormRow>
          <div><EuiButton iconType="sortUp" isDisabled={!!problem} onClick={() => setAsking(true)}>
            Plan the growth</EuiButton></div>
        </>)}

      {asking && (
        <ConfirmAction action="Grow data disks of" confirmText="Plan the growth" resource={cluster.name}
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will plan growing {chosen.length} data disk{chosen.length === 1 ? "" : "s"} to {whole} GB, and the
            filesystem on {chosen.length === 1 ? "it" : "each"}, and show you the plan. This step changes nothing.
            After you approve it, a disk cannot be shrunk again.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
