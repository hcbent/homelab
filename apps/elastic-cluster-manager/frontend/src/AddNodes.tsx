import {
  EuiButton, EuiCallOut, EuiComboBox, EuiComboBoxOptionOption, EuiFieldNumber, EuiFormRow, EuiLink, EuiPanel,
  EuiRadioGroup, EuiSelect,
} from "@elastic/eui";
import { useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, Infrastructure } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const whole = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : NaN);

/** The roles Elasticsearch accepts in `node.roles`. */
export const ROLES = ["master", "voting_only", "data", "data_content", "data_hot", "data_warm", "data_cold",
  "data_frozen", "ingest", "ml", "remote_cluster_client", "transform"];
const DATA_ROLES = ["data", "data_content", "data_hot", "data_warm", "data_cold", "data_frozen"];
const MODES = [
  { id: "default", label: "Default roles: every role except voting_only (what a node gets when none are set)" },
  { id: "coordinating", label: "Coordinating only: no roles, so it only routes requests" },
  { id: "custom", label: "Choose the roles" },
];

/**
 * Add one or more nodes of one kind to a cluster ECM built. ECM chooses their names, hosts, addresses and VM IDs and
 * shows them in the plan; after the plan is approved, Terraform makes the machines and ECM configures and starts only the
 * new nodes and waits for them to join.
 */
export function AddNodes({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const sizes = life?.sizes ?? {};
  const [count, setCount] = useState("1");
  const [mode, setMode] = useState("default");
  const [picked, setPicked] = useState<EuiComboBoxOptionOption<string>[]>([]);
  const [cores, setCores] = useState("");
  const [ram, setRam] = useState("");
  const [osDisk, setOsDisk] = useState("");
  const [dataDisk, setDataDisk] = useState("");
  const [host, setHost] = useState("");
  const [hosts, setHosts] = useState<string[]>([]);
  const [touched, setTouched] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Infrastructure>("/api/infrastructure").then((i) => setHosts(i.nodes.map((n) => n.name).sort()))
      .catch(() => setHosts([]));   // the host choice is optional, so a failure to list hosts costs only the choice
  }, []);
  if (!life?.managed || Object.keys(sizes).length === 0) return null;

  const roles = picked.map((o) => o.label);
  const holdsData = mode === "default" || (mode === "custom" && roles.some((r) => DATA_ROLES.includes(r)));
  const n = whole(count);
  const optional = (v: string, min: number, max: number, what: string) => {
    if (v.trim() === "") return null;
    const x = whole(v);
    return Number.isNaN(x) || x < min || x > max ? `${what} must be a whole number from ${min} to ${max}.` : null;
  };
  const problem = Number.isNaN(n) || n < 1 || n > 10 ? "Add between 1 and 10 nodes at a time."
    : mode === "custom" && roles.length === 0 ? "Choose at least one role, or pick Coordinating only."
    : roles.includes("voting_only") && !roles.includes("master") ? "voting_only needs the master role too."
    : optional(cores, 1, 64, "Cores") ?? optional(ram, 2, 512, "RAM (GiB)") ?? optional(osDisk, 16, 2048, "The OS disk")
      ?? (holdsData ? optional(dataDisk, 10, 65536, "The data disk") : null);

  async function plan() {
    setAsking(false);
    setError(null);
    const body: Record<string, unknown> = { count: n };
    if (mode === "coordinating") body.roles = [];
    if (mode === "custom") body.roles = roles;
    if (cores.trim()) body.cores = Number(cores);
    if (ram.trim()) body.ram_mb = Number(ram) * 1024;
    if (osDisk.trim()) body.os_disk_gb = Number(osDisk);
    if (holdsData && dataDisk.trim()) body.data_disk_gb = Number(dataDisk);
    if (host) body.pve_node = host;
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/add-nodes`, {
        method: "POST", body: JSON.stringify(body),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle"
      aria-labelledby="add-title">
      <h3 id="add-title" className="ecm-h3">Add nodes</h3>
      <p>Adds nodes of one kind to this cluster. ECM chooses their names, hosts, addresses and VM IDs and shows them in the
        plan. Only the new nodes are configured and started; the existing nodes are not touched.</p>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work" size="s">
          <p>{error}</p></EuiCallOut>)}

      {Object.keys(sizes).length < 2 ? (
        <p className="ecm-muted">A single-node cluster is started in a mode that cannot take other nodes, so nodes cannot be
          added to it.</p>
      ) : life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before adding nodes.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !life.can_change ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <EuiFormRow label="How many" helpText="Of the kind chosen below. Run this again to add a different kind.">
            <EuiFieldNumber value={count} min={1} max={10} onBlur={() => setTouched(true)}
              onChange={(e) => setCount(e.target.value)} />
          </EuiFormRow>
          <EuiFormRow label="Roles" fullWidth>
            <EuiRadioGroup name="add-roles" legend={{ children: "Roles", display: "hidden" }} options={MODES}
              idSelected={mode} onChange={setMode} />
          </EuiFormRow>
          {mode === "custom" && (
            <EuiFormRow label="Choose roles" fullWidth isInvalid={touched && roles.length === 0}
              helpText="Pick one or more. A node with master among its roles can be elected; data_* roles give it a data disk.">
              <EuiComboBox<string> fullWidth aria-label="Roles" placeholder="Select roles"
                options={ROLES.map((r) => ({ label: r }))} selectedOptions={picked}
                onChange={(o) => { setPicked(o); setTouched(true); }} />
            </EuiFormRow>)}
          <EuiCallOut color="primary" size="s" iconType="info" title="Master-eligible nodes must be spread over the hosts">
            <p>A host may hold at most (master-eligible nodes − 1) ÷ 2 of them, so the cluster survives losing a host. With
              three masters on three hosts, adding one more is refused, because four need four hosts; adding two at once is
              allowed. The plan says which host and why if it cannot place them.</p></EuiCallOut>
          <div className="ecm-form-row">
            <EuiFormRow label="Cores (leave empty to copy a similar node)">
              <EuiFieldNumber value={cores} onBlur={() => setTouched(true)} onChange={(e) => setCores(e.target.value)} />
            </EuiFormRow>
            <EuiFormRow label="RAM, GiB (leave empty to copy)">
              <EuiFieldNumber value={ram} onBlur={() => setTouched(true)} onChange={(e) => setRam(e.target.value)} />
            </EuiFormRow>
          </div>
          <div className="ecm-form-row">
            <EuiFormRow label="OS disk, GB (leave empty to copy)">
              <EuiFieldNumber value={osDisk} onBlur={() => setTouched(true)} onChange={(e) => setOsDisk(e.target.value)} />
            </EuiFormRow>
            <EuiFormRow label="Data disk, GB (leave empty to copy)"
              helpText={holdsData ? undefined : "These roles hold no data, so there is no data disk."}>
              <EuiFieldNumber value={dataDisk} disabled={!holdsData} onBlur={() => setTouched(true)}
                onChange={(e) => setDataDisk(e.target.value)} />
            </EuiFormRow>
          </div>
          {hosts.length > 0 && (
            <EuiFormRow label="Proxmox host" helpText="Leave on automatic to let ECM place them.">
              <EuiSelect value={host} options={[{ value: "", text: "Automatic" }, ...hosts.map((h) => ({ value: h, text: h }))]}
                onChange={(e) => setHost(e.target.value)} />
            </EuiFormRow>)}
          {touched && problem && <p role="alert" className="ecm-error-text">{problem}</p>}
          <div><EuiButton iconType="plusCircle" isDisabled={!!problem} onClick={() => setAsking(true)}>
            Plan adding nodes</EuiButton></div>
        </>)}

      {asking && (
        <ConfirmAction action="Add nodes to" confirmText="Plan adding nodes" resource={cluster.name}
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will plan adding {n} node{n === 1 ? "" : "s"} and show you where each would go. This step changes
            nothing. After you approve it, Terraform makes the machines, and ECM configures and starts the new nodes and
            waits for them to join; the existing nodes are not restarted.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
