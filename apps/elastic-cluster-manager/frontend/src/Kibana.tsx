import {
  EuiButton, EuiButtonEmpty, EuiCallOut, EuiCodeBlock, EuiDescriptionList, EuiFieldNumber, EuiFieldText, EuiFormRow, EuiLink, EuiPanel,
  EuiSelect,
} from "@elastic/eui";
import { useEffect, useState } from "react";
import { api, ApiError, ClusterDetail, Infrastructure, KibanaMachine, KibanaPanel } from "./api";
import { ConfirmAction } from "./ConfirmAction";

const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));
const whole = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : NaN);
const DNS_NAME = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$/i;

/** What the operator is being asked to confirm before a plan is made. */
type Asking = "login" | "restart" | "remove" | null;

/** One Kibana machine on record: where it is, how to sign in, what can be done to it, and the Caddy block that would put it behind the proxy. */
function Machine({ cluster, machine, panel, onError }: {
  cluster: ClusterDetail; machine: KibanaMachine; panel: KibanaPanel; onError: (m: string | null) => void;
}) {
  const [asking, setAsking] = useState<Asking>(null);
  const [shown, setShown] = useState<{ username: string; password: string } | null>(null);
  const lastAdd = panel.last_add;
  const login = panel.login;

  async function plan(path: string, body?: Record<string, unknown>) {
    setAsking(null);
    onError(null);
    try {
      const out = await api<{ operation_id: string }>(`/api/clusters/${cluster.id}/${path}`, {
        method: "POST", body: JSON.stringify(body ?? {}),
      });
      window.location.hash = `#/operations/${out.operation_id}`;
    } catch (e) {
      onError(message(e));
    }
  }

  async function reveal() {
    onError(null);
    try {
      const out = await api<{ username: string; password: string }>(`/api/clusters/${cluster.id}/kibana-login/reveal`, { method: "POST" });
      setShown({ username: out.username, password: out.password });
    } catch (e) {
      onError(message(e));
    }
  }

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

      {machine.hosts_out_of_date && (
        <EuiCallOut color="warning" iconType="warning" size="s" title="Kibana is using an out-of-date list of Elasticsearch nodes">
          <p>The cluster's nodes have changed since Kibana was last configured, and it reads the list only when it starts. Kibana keeps working
            while any node in its list answers; restart it to bring the list up to date.</p></EuiCallOut>)}

      <h4 className="ecm-label">Sign in</h4>
      {login.set ? (
        <>
          <p>ECM set a password for the <span className="ecm-mono">elastic</span> user{login.reset_at ? ` on ${new Date(login.reset_at).toLocaleString()}` : ""} and
            keeps it encrypted. Showing it is recorded in the audit log every time.</p>
          {shown ? (
            <EuiCallOut color="primary" iconType="lock" size="s" title="Sign-in details (this view was recorded)">
              <EuiCodeBlock language="text" isCopyable paddingSize="m">{`Username: ${shown.username}\nPassword: ${shown.password}`}</EuiCodeBlock>
              <EuiButtonEmpty size="s" onClick={() => setShown(null)}>Hide</EuiButtonEmpty>
            </EuiCallOut>
          ) : (
            <div><EuiButton iconType="eye" onClick={reveal}>Show sign-in details</EuiButton></div>)}
        </>
      ) : (
        <EuiCallOut color="primary" iconType="info" size="s" title="Nobody can sign in to this Kibana yet">
          <p>ECM does not keep the elastic user's password. Create a sign-in and ECM sets a new, generated password for that user, checks it
            works and keeps it encrypted, so you can show it here.
            {login.last && login.last.state === "failed" && <> The last attempt did not finish:{" "}
              <EuiLink href={`#/operations/${login.last.operation_id}`}>open it</EuiLink>.</>}</p></EuiCallOut>)}

      {panel.can_change && (
        <div className="ecm-detail__actions">
          <EuiButton iconType={login.set ? "refresh" : "plusInCircle"} onClick={() => setAsking("login")}>
            {login.set ? "Reset password" : "Create sign-in"}</EuiButton>
          <EuiButton iconType="refresh" onClick={() => setAsking("restart")}>Restart Kibana</EuiButton>
          <EuiButton color="danger" iconType="trash" onClick={() => setAsking("remove")}>Remove Kibana</EuiButton>
        </div>)}

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
      {panel.ca_available && (
        <p><EuiLink href={`/api/clusters/${cluster.id}/ca.crt`} download={`${cluster.name}-ca.crt`}>
          Download the cluster CA certificate</EuiLink></p>)}

      {asking === "login" && (
        <ConfirmAction action={login.set ? "Reset the elastic password of" : "Create a sign-in for"} confirmText="Plan it" resource={cluster.name}
          onCancel={() => setAsking(null)} onConfirm={() => plan("kibana-login")}>
          <p>ECM will plan setting a new, generated password for the elastic user. This step changes nothing. After you approve it, the
            password changes: anyone using the old one can no longer sign in. ECM's own API key is not affected.</p>
        </ConfirmAction>)}
      {asking === "restart" && (
        <ConfirmAction action="Restart Kibana of" confirmText="Plan the restart" resource={cluster.name}
          onCancel={() => setAsking(null)} onConfirm={() => plan("restart-kibana")}>
          <p>ECM will plan rewriting Kibana's configuration with the cluster's current nodes and restarting it. This step changes nothing.
            After you approve it, people using Kibana are briefly disconnected; it holds no data.</p>
        </ConfirmAction>)}
      {asking === "remove" && (
        <ConfirmAction action="Remove Kibana from" confirmText="Plan the removal" resource={cluster.name} destructive
          onCancel={() => setAsking(null)} onConfirm={() => plan("remove-kibana", { confirm_name: cluster.name })}>
          <p>ECM will plan removing Kibana. This step changes nothing. After you approve it, Terraform destroys its machine for good and ECM
            deletes its service token. Its dashboards and saved objects stay in Elasticsearch, and ECM keeps the encryption keys.</p>
        </ConfirmAction>)}
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
        panel.machines.map((m) => <Machine key={m.name} cluster={cluster} machine={m} panel={panel} onError={setError} />)
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
