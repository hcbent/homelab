import {
  EuiButton, EuiCallOut, EuiCodeBlock, EuiDescriptionList, EuiFieldNumber, EuiFieldText, EuiFormRow, EuiLink, EuiPanel,
  EuiSelect,
} from "@elastic/eui";
import { useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, Infrastructure, KibanaMachine } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const whole = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : NaN);
const DNS_NAME = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$/i;

/** One Kibana machine on record: where it is, how it was last checked, and the Caddy block that would put it behind the proxy. */
function Machine({ cluster, machine, lastAdd }: {
  cluster: ClusterDetail; machine: KibanaMachine;
  lastAdd: NonNullable<NonNullable<ClusterDetail["lifecycle"]>["kibana"]>["last_add"];
}) {
  const ca = cluster.lifecycle?.kibana?.ca_available;
  return (
    <>
      <EuiDescriptionList type="column" compressed listItems={[
        { title: "Machine", description: <span className="ecm-mono">{machine.name}</span> },
        { title: "Address", description: <span className="ecm-mono">{machine.url}</span> },
        { title: "Public name", description: machine.public_url
          ? <span className="ecm-mono">{machine.public_url}</span> : <span className="ecm-muted">none</span> },
        { title: "Proxmox host", description: <span className="ecm-mono">{machine.host}</span> },
        { title: "Size", description: `${machine.cores} cores, ${machine.ram_mb / 1024} GiB, ${machine.os_disk_gb} GB disk` },
        { title: "Last check", description: lastAdd
          ? (lastAdd.state === "succeeded"
              ? <>Reported itself available when it was added.{" "}
                <EuiLink href={`#/operations/${lastAdd.operation_id}`}>Open the operation</EuiLink></>
              : <>The last attempt {lastAdd.state === "failed" ? "did not finish" : `is ${lastAdd.state.replace("_", " ")}`}.{" "}
                <EuiLink href={`#/operations/${lastAdd.operation_id}`}>Open the operation</EuiLink></>)
          : <span className="ecm-muted">not checked</span> },
      ]} />
      {lastAdd && lastAdd.state === "failed" && (
        <EuiCallOut color="danger" iconType="warning" size="s" title="Kibana did not finish being added">
          <p>The machine exists and is kept. Open the operation and press Retry: it configures the machine again with the
            same token and keys, which is safe to repeat.</p></EuiCallOut>)}
      <EuiCallOut color="primary" iconType="info" size="s" title="Nobody can sign in to this Kibana yet">
        <p>ECM does not create a Kibana login yet, so the machine runs and reports itself available but has no user to sign in as.
          Creating one is planned for the next step of this phase, and has not been built.</p></EuiCallOut>
      <h4 className="ecm-label">Caddy</h4>
      {machine.caddy_snippet ? (
        <>
          <p>Add this to your Caddyfile yourself. ECM shows it and never edits the Caddyfile. Caddy checks Kibana's certificate
            against the cluster's CA, so the connection is verified end to end; put the CA certificate at the path in the
            snippet.</p>
          <EuiCodeBlock language="text" isCopyable paddingSize="m">{machine.caddy_snippet}</EuiCodeBlock>
        </>
      ) : (
        <p className="ecm-muted">This Kibana was added without a public name, so there is no snippet to show.</p>)}
      {ca && (
        <p><EuiLink href={`/api/clusters/${cluster.id}/ca.crt`} download={`${cluster.name}-ca.crt`}>
          Download the cluster CA certificate</EuiLink></p>)}
    </>
  );
}

/**
 * Kibana for a cluster ECM built: add one (a new machine, installed at the cluster's exact version, with its token, encryption keys
 * and certificate made by ECM), or see the one it has. Adding only makes a plan; nothing changes until it is approved.
 */
export function Kibana({ cluster }: { cluster: ClusterDetail }) {
  const life = cluster.lifecycle;
  const panel = life?.kibana;
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [hosts, setHosts] = useState<string[]>([]);
  const [cores, setCores] = useState("");
  const [ram, setRam] = useState("");
  const [disk, setDisk] = useState("");
  const [touched, setTouched] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Infrastructure>("/api/infrastructure").then((i) => setHosts(i.nodes.map((n) => n.name).sort()))
      .catch(() => setHosts([]));   // the host choice is optional, so a failure to list hosts costs only the choice
  }, []);
  if (!life?.managed || !life.bootstrapped || !panel) return null;

  const optional = (v: string, min: number, max: number, what: string) => {
    if (v.trim() === "") return null;
    const x = whole(v);
    return Number.isNaN(x) || x < min || x > max ? `${what} must be a whole number from ${min} to ${max}.` : null;
  };
  const problem = name.trim() && !DNS_NAME.test(name.trim()) ? "The public name must be a DNS name such as kibana.example.org, with no https:// or port."
    : optional(cores, 1, 64, "Cores") ?? optional(ram, 2, 512, "RAM (GiB)") ?? optional(disk, 16, 2048, "The disk");

  async function plan() {
    setAsking(false);
    setError(null);
    const body: Record<string, unknown> = {};
    if (name.trim()) body.public_name = name.trim();
    if (host) body.pve_node = host;
    if (cores.trim()) body.cores = Number(cores);
    if (ram.trim()) body.ram_mb = Number(ram) * 1024;
    if (disk.trim()) body.os_disk_gb = Number(disk);
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/add-kibana`, {
        method: "POST", body: JSON.stringify(body),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-lifecycle" aria-labelledby="kibana-title">
      <h3 id="kibana-title" className="ecm-h3">Kibana</h3>
      {error && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="That did not work" size="s"><p>{error}</p></EuiCallOut>)}

      {panel.machines.length > 0 ? (
        panel.machines.map((m) => <Machine key={m.name} cluster={cluster} machine={m} lastAdd={panel.last_add} />)
      ) : life.busy_operation_id ? (
        <EuiCallOut color="primary" iconType="info" size="s" title="An operation is running on this cluster">
          <p>Wait for it to finish before adding Kibana.{" "}
            <EuiLink href={`#/operations/${life.busy_operation_id}`}>Open it</EuiLink></p></EuiCallOut>
      ) : !panel.can_add ? (
        <p className="ecm-muted">This cluster cannot be changed right now.</p>
      ) : (
        <>
          <p>Adds one Kibana to this cluster, on a new machine of its own. ECM installs the same version as the cluster, asks the
            cluster for Kibana's service-account token, makes its encryption keys and certificate, and checks it reports itself
            available. The Elasticsearch nodes are not touched or restarted.</p>
          <EuiFormRow label="Public name (optional)" fullWidth isInvalid={touched && !!problem && !!name.trim()}
            helpText="The DNS name people will use, such as kibana.example.org. It goes on the certificate and in the Caddy snippet. Leave empty to reach Kibana by its address.">
            <EuiFieldText fullWidth value={name} onBlur={() => setTouched(true)} onChange={(e) => setName(e.target.value)} />
          </EuiFormRow>
          <div className="ecm-form-row">
            <EuiFormRow label="Cores (default 2)">
              <EuiFieldNumber value={cores} onBlur={() => setTouched(true)} onChange={(e) => setCores(e.target.value)} />
            </EuiFormRow>
            <EuiFormRow label="RAM, GiB (default 4)">
              <EuiFieldNumber value={ram} onBlur={() => setTouched(true)} onChange={(e) => setRam(e.target.value)} />
            </EuiFormRow>
            <EuiFormRow label="Disk, GB (default 32)">
              <EuiFieldNumber value={disk} onBlur={() => setTouched(true)} onChange={(e) => setDisk(e.target.value)} />
            </EuiFormRow>
          </div>
          {hosts.length > 0 && (
            <EuiFormRow label="Proxmox host" helpText="Leave on automatic to use the host with the most room.">
              <EuiSelect value={host} options={[{ value: "", text: "Automatic" }, ...hosts.map((h) => ({ value: h, text: h }))]}
                onChange={(e) => setHost(e.target.value)} />
            </EuiFormRow>)}
          {touched && problem && <p role="alert" className="ecm-error-text">{problem}</p>}
          <div><EuiButton iconType="plusCircle" isDisabled={!!problem} onClick={() => setAsking(true)}>Plan adding Kibana</EuiButton></div>
        </>)}

      {asking && (
        <ConfirmAction action="Add Kibana to" confirmText="Plan adding Kibana" resource={cluster.name}
          onCancel={() => setAsking(false)} onConfirm={plan}>
          <p>ECM will plan one new machine for Kibana and show you where it would go. This step changes nothing. After you approve
            it, Terraform makes the machine and ECM installs and starts Kibana on it; no Elasticsearch node is restarted.</p>
        </ConfirmAction>)}
    </EuiPanel>
  );
}
