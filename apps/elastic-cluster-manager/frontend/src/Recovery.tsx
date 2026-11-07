import { EuiButton, EuiCallOut, EuiCheckboxGroup, EuiFormRow, EuiLink, EuiPanel, EuiSelect } from "@elastic/eui";
import { useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, Infrastructure } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/**
 * Nodes whose machine is gone from Proxmox and that Elasticsearch no longer reports. They can be rebuilt (the same name, address
 * and VM ID, an empty disk that fills from the other nodes) or forgotten (taken out of the record, nothing destroyed). Shown only
 * when a node is lost; the data of a red cluster is dealt with by hand first, and ECM says so when it refuses.
 */
export function Recovery({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const state = life?.node_state ?? {};
  const lost = Object.keys(state).filter((n) => state[n].machine === false && !state[n].in_cluster).sort();
  const down = Object.keys(state).filter((n) => state[n].machine === true && !state[n].in_cluster).sort();
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [host, setHost] = useState("");
  const [hosts, setHosts] = useState<string[]>([]);
  const [asking, setAsking] = useState<"forget" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Infrastructure>("/api/infrastructure").then((i) => setHosts(i.nodes.map((n) => n.name).sort()))
      .catch(() => setHosts([]));   // the host choice is optional, so a failure to list hosts costs only the choice
  }, []);
  if (!life?.managed || (lost.length === 0 && down.length === 0)) return null;

  const chosen = lost.filter((n) => picked[n] ?? true);

  async function plan(what: "rebuild-nodes" | "forget-nodes") {
    setAsking(null);
    setError(null);
    const body: Record<string, unknown> = { nodes: chosen };
    if (what === "rebuild-nodes" && host) body.pve_node = host;
    if (what === "forget-nodes") body.confirm_name = cluster.name;
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/${what}`, {
        method: "POST", body: JSON.stringify(body),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="recovery-title">
      <h3 id="recovery-title" className="ecm-h3">Recovery</h3>
      {lost.length > 0 && (
        <EuiCallOut color="warning" iconType="warning" size="s"
          title={`${lost.length} node${lost.length === 1 ? " is" : "s are"} lost: ${lost.join(", ")}`}>
          <p>Each one's machine is gone from Proxmox and Elasticsearch no longer reports it. Rebuilding makes the machine again
            with the same name, address and VM ID and an empty disk, then starts the node, and the other nodes refill it.
            Forgetting takes it out of ECM's record and destroys nothing. ECM recovers a node only while the cluster is yellow or
            green: a red cluster has lost data, which has to be dealt with by hand first.</p>
        </EuiCallOut>)}
      {down.length > 0 && (
        <p className="ecm-muted">{down.join(", ")} {down.length === 1 ? "has" : "have"} a machine in Proxmox but {down.length === 1 ? "is" : "are"} not
          in the cluster. That needs starting or restarting, which ECM does not do yet; it is not a rebuild.</p>)}
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That cannot be done" size="s">
          <p>{error}</p></EuiCallOut>)}

      {lost.length > 0 && (life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before recovering nodes.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <EuiFormRow label="Lost nodes" fullWidth>
            <EuiCheckboxGroup
              options={lost.map((n) => ({ id: n, label: n }))}
              idToSelectedMap={Object.fromEntries(lost.map((n) => [n, picked[n] ?? true]))}
              onChange={(id) => setPicked({ ...Object.fromEntries(lost.map((n) => [n, picked[n] ?? true])),
                [id]: !(picked[id] ?? true) })} />
          </EuiFormRow>
          <EuiFormRow label="Proxmox host for a rebuild" helpText="Leave on automatic: each node goes back to its old host if that is online, and ECM places it otherwise.">
            <EuiSelect options={[{ value: "", text: "Automatic" }, ...hosts.map((h) => ({ value: h, text: h }))]}
              value={host} onChange={(e) => setHost(e.target.value)} />
          </EuiFormRow>
          <div className="ecm-detail__actions">
            <EuiButton iconType="refresh" isDisabled={chosen.length === 0} onClick={() => plan("rebuild-nodes")}>
              Plan the rebuild</EuiButton>
            <EuiButton iconType="trash" color="danger" isDisabled={chosen.length === 0} onClick={() => setAsking("forget")}>
              Forget these nodes</EuiButton>
          </div>
        </>))}

      {asking === "forget" && (
        <ConfirmAction action="Forget nodes of" confirmText="Plan forgetting them" resource={cluster.name} destructive
          onCancel={() => setAsking(null)} onConfirm={() => plan("forget-nodes")}>
          <p>ECM will check that {chosen.join(", ")} {chosen.length === 1 ? "is" : "are"} lost and show you the plan. After you
            approve it, {chosen.length === 1 ? "the node is" : "the nodes are"} taken out of ECM's record; nothing is destroyed, because
            the machines are already gone. A node that is later brought back would be a stranger to ECM.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
