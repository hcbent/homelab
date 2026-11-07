import {
  EuiButton, EuiCallOut, EuiCheckboxGroup, EuiFieldNumber, EuiFormRow, EuiLink, EuiPanel,
} from "@elastic/eui";
import { useState } from "react";
import { api, ApiError, ClusterDetail } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const whole = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : NaN);
const gib = (mb: number) => `${mb / 1024} GiB`;

/**
 * Give nodes of a cluster ECM built a new number of cores and/or amount of RAM. It asks ECM to plan the change. After the
 * plan is approved on its operation page, Terraform changes the machines' configuration and ECM restarts the nodes one
 * at a time, waiting for the cluster to be green between them.
 */
export function Resize({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const sizes = life?.sizes ?? {};
  const names = Object.keys(sizes).sort();
  const [cores, setCores] = useState("");
  const [ram, setRam] = useState("");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [touched, setTouched] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!life?.managed || names.length === 0) return null;

  const chosen = names.filter((n) => picked[n] ?? true);
  const coresN = cores.trim() === "" ? null : whole(cores);
  const ramN = ram.trim() === "" ? null : whole(ram);
  const problem = chosen.length === 0 ? "Choose at least one node."
    : coresN === null && ramN === null ? "Enter a number of cores, an amount of RAM, or both."
    : coresN !== null && (Number.isNaN(coresN) || coresN < 1 || coresN > 64) ? "Cores must be a whole number from 1 to 64."
    : ramN !== null && (Number.isNaN(ramN) || ramN < 2 || ramN > 512) ? "RAM must be a whole number of GiB from 2 to 512."
    : null;

  async function plan() {
    setAsking(false);
    setError(null);
    const body: { cores?: number; ram_mb?: number; nodes?: string[] } = {};
    if (coresN !== null) body.cores = coresN;
    if (ramN !== null) body.ram_mb = ramN * 1024;
    if (chosen.length < names.length) body.nodes = chosen;
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/resize`, {
        method: "POST", body: JSON.stringify(body),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="resize-title">
      <h3 id="resize-title" className="ecm-h3">Resize nodes</h3>
      <p>Current sizes: {names.map((n, i) => (
        <span key={n}>{i > 0 && "; "}<span className="ecm-mono">{n}</span> {sizes[n].cores} cores, {gib(sizes[n].ram_mb)}</span>
      ))}.</p>
      <EuiCallOut color="primary" iconType="info" size="s" title="Each node is restarted, one at a time">
        <p>Terraform changes the machines' configuration, then ECM restarts the nodes: coordinating nodes first, then
          data nodes, then masters with the elected master last. Before each restart it waits for the cluster to be
          green, and it holds back shard allocation while a node is down. Each node is briefly out of the cluster.</p>
      </EuiCallOut>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work" size="s">
          <p>{error}</p></EuiCallOut>)}

      {names.length < 2 ? (
        <p className="ecm-muted">A single-node cluster would be down while its machine restarts, so ECM does not resize it.</p>
      ) : life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before resizing.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <EuiFormRow label="Nodes" fullWidth>
            <EuiCheckboxGroup
              options={names.map((n) => ({ id: n, label: `${n} (${sizes[n].cores} cores, ${gib(sizes[n].ram_mb)})` }))}
              idToSelectedMap={Object.fromEntries(names.map((n) => [n, picked[n] ?? true]))}
              onChange={(id) => setPicked({ ...Object.fromEntries(names.map((n) => [n, picked[n] ?? true])),
                [id]: !(picked[id] ?? true) })} />
          </EuiFormRow>
          <EuiFormRow label="Cores per node (leave empty to keep)" isInvalid={touched && !!problem}>
            <EuiFieldNumber value={cores} onBlur={() => setTouched(true)} onChange={(e) => setCores(e.target.value)} />
          </EuiFormRow>
          <EuiFormRow label="RAM per node, GiB (leave empty to keep)" isInvalid={touched && !!problem}
            error={touched ? problem ?? undefined : undefined}>
            <EuiFieldNumber value={ram} isInvalid={touched && !!problem} onBlur={() => setTouched(true)}
              onChange={(e) => setRam(e.target.value)} />
          </EuiFormRow>
          <div><EuiButton iconType="gear" isDisabled={!!problem} onClick={() => setAsking(true)}>Plan the resize</EuiButton></div>
        </>)}

      {asking && (
        <ConfirmAction action="Resize nodes of" confirmText="Plan the resize" resource={cluster.name}
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will plan the new size for {chosen.length} node{chosen.length === 1 ? "" : "s"} and show you the plan.
            This step changes nothing. After you approve it, Terraform changes the machines' configuration and ECM
            restarts the nodes one at a time, each briefly out of the cluster.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
