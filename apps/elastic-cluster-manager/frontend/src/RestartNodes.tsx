import { EuiButton, EuiButtonEmpty, EuiCallOut, EuiCheckboxGroup, EuiFormRow, EuiLink, EuiPanel } from "@elastic/eui";
import { useState } from "react";
import { api, ApiError, ClusterDetail } from "./api";
import { ConfirmAction } from "./ConfirmAction";
import { ids } from "./checkboxIds";

const box = ids("restart");
const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/**
 * Restart nodes of a cluster ECM built, one at a time, or start a node whose machine is stopped. ECM reads the cluster, decides the
 * order (nodes that are down first, then coordinating, data and master-eligible nodes, the elected master last) and shows it on the plan
 * page; nothing restarts until the plan is approved. This is also how a configuration change that "takes effect at the next restart"
 * (the note a converge leaves after an add or a removal) is applied.
 */
export function RestartNodes({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const roles = life?.node_roles ?? {};
  const state = life?.node_state ?? {};
  const names = Object.keys(roles).sort();
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!life?.managed || names.length < 2) return null;

  // A node with no machine and not in the cluster is lost: it is rebuilt or forgotten (Recovery), not restarted.
  const lost = (n: string) => state[n]?.machine === false && !state[n]?.in_cluster;
  const down = (n: string) => !state[n]?.in_cluster && !lost(n);
  const offerable = names.filter((n) => !lost(n));
  const chosen = offerable.filter((n) => picked[n]);
  const label = (n: string) => {
    const r = roles[n].roles.length ? roles[n].roles.join(", ") : "coordinating only";
    const note = lost(n) ? " (lost: rebuild or forget it under Recovery)"
      : down(n) ? ` (not in the cluster${state[n]?.vm_status ? `, its machine is ${state[n].vm_status}` : ""}: it will be ${state[n]?.vm_status === "stopped" ? "started" : "restarted"} first)`
      : "";
    return `${n}: ${r}${roles[n].master_eligible ? " (master-eligible)" : ""}${note}`;
  };

  async function plan() {
    setAsking(false);
    setError(null);
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/restart-nodes`, {
        method: "POST", body: JSON.stringify({ nodes: chosen }),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="restart-nodes-title">
      <h3 id="restart-nodes-title" className="ecm-h3">Restart nodes</h3>
      <EuiCallOut color="primary" iconType="info" size="s" title="Nodes are restarted one at a time, each briefly out of the cluster">
        <p>ECM waits for the cluster to be green before each node, holds back shard allocation while a node is down, restarts the master-eligible
          nodes last (the elected master last of those), and starts a node whose machine is stopped. Use it to apply a configuration change that is
          waiting for a restart, for example after nodes were added or removed, or to bring a node back that is down.</p>
      </EuiCallOut>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That cannot be done" size="s">
          <p>{error}</p></EuiCallOut>)}

      {life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before restarting nodes.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <EuiFormRow label="Nodes to restart" fullWidth>
            <EuiCheckboxGroup
              options={names.map((n) => ({ id: box.id(n), label: label(n), disabled: lost(n) }))}
              idToSelectedMap={Object.fromEntries(names.map((n) => [box.id(n), !!picked[n] && !lost(n)]))}
              onChange={(id) => setPicked({ ...picked, [box.name(id)]: !picked[box.name(id)] })} />
          </EuiFormRow>
          <div className="ecm-detail__actions">
            <EuiButton iconType="refresh" isDisabled={chosen.length === 0} onClick={() => setAsking(true)}>Plan the restart</EuiButton>
            <EuiButtonEmpty onClick={() => setPicked(Object.fromEntries(offerable.map((n) => [n, true])))}>Select every node</EuiButtonEmpty>
            <EuiButtonEmpty isDisabled={chosen.length === 0} onClick={() => setPicked({})}>Clear</EuiButtonEmpty>
          </div>
        </>)}

      {asking && (
        <ConfirmAction action="Restart nodes of" confirmText="Plan the restart" resource={cluster.name}
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will read the cluster, plan the order for {chosen.length} node{chosen.length === 1 ? "" : "s"} and show you the plan. This step
            changes nothing. After you approve it, each node is restarted in turn and is briefly out of the cluster.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
