import { EuiButton, EuiCallOut, EuiCheckboxGroup, EuiFormRow, EuiLink, EuiPanel } from "@elastic/eui";
import { useState } from "react";
import { api, ApiError, ClusterDetail } from "./api";
import { ConfirmAction } from "./ConfirmAction";
import { ids } from "./checkboxIds";

const box = ids("remove");
const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/**
 * Remove nodes from a cluster ECM built. ECM reads the cluster before it plans and refuses anything that could lose data
 * or the master quorum, saying why. After the plan is approved on its operation page, Elasticsearch moves the data off the
 * nodes, then Terraform destroys the machines and their disks.
 */
export function RemoveNodes({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const info = life?.node_roles ?? {};
  const names = Object.keys(info).sort();
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planning, setPlanning] = useState(false);
  if (!life?.managed || names.length < 2) return null;

  const chosen = names.filter((n) => picked[n]);
  const masters = names.filter((n) => info[n].master_eligible).length;
  const label = (n: string) => {
    const i = info[n];
    const roles = i.roles.length ? i.roles.join(", ") : "coordinating only";
    return `${n}: ${roles}${i.master_eligible ? " (counts towards the master quorum)" : ""}${i.host ? `, on ${i.host}` : ""}`;
  };

  async function plan() {
    setAsking(false);
    setError(null);
    setPlanning(true);
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/remove-nodes`, {
        method: "POST", body: JSON.stringify({ nodes: chosen, confirm_name: cluster.name }),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    } finally {
      setPlanning(false);
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="remove-nodes-title">
      <h3 id="remove-nodes-title" className="ecm-h3">Remove nodes</h3>
      <EuiCallOut color="primary" iconType="info" size="s" title="The data is moved off a node before its machine is destroyed">
        <p>ECM reads the cluster first and refuses a removal that could lose data or the master quorum. Elasticsearch then
          moves the node's shards to the other nodes; only when that is finished does Terraform destroy the machine and its
          disks. The cluster has {masters} master-eligible node{masters === 1 ? "" : "s"}: it needs at least 3 to survive
          losing one, and fewer than half of them can be removed at once.</p>
      </EuiCallOut>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That cannot be done" size="s">
          <p>{error}</p></EuiCallOut>)}

      {life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before removing nodes.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <EuiFormRow label="Nodes to remove" fullWidth>
            <EuiCheckboxGroup
              options={names.map((n) => ({ id: box.id(n), label: label(n) }))}
              idToSelectedMap={Object.fromEntries(names.map((n) => [box.id(n), !!picked[n]]))}
              onChange={(id) => setPicked({ ...picked, [box.name(id)]: !picked[box.name(id)] })} />
          </EuiFormRow>
          <div>
            <EuiButton iconType="trash" color="danger" isDisabled={chosen.length === 0 || planning}
              onClick={() => setAsking(true)}>Plan the removal</EuiButton>
          </div>
        </>)}

      {asking && (
        <ConfirmAction action="Remove nodes from" confirmText="Plan the removal" resource={cluster.name} destructive
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will check whether {chosen.join(", ")} can be removed and show you the plan. This step changes nothing.
            After you approve it, Elasticsearch moves the data off {chosen.length === 1 ? "the node" : "the nodes"} and
            Terraform destroys {chosen.length === 1 ? "its machine" : "their machines"} and disks for good.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
