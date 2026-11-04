import {
  EuiButton, EuiCallOut, EuiFieldPassword, EuiFieldText, EuiFormRow, EuiSelect, EuiSwitch, EuiTextArea,
} from "@elastic/eui";
import { FormEvent, useState } from "react";
import { api, ApiError } from "./api";

export type ConnectionType = "proxmox" | "elasticsearch";

const TYPES = [
  { value: "proxmox", text: "Proxmox" },
  { value: "elasticsearch", text: "Elasticsearch" },
];

const CHECKLIST = [
  "Proxmox: token with the PVEAuditor role and privilege separation off",
  "Elasticsearch: API key with cluster monitor and index view_index_metadata",
  "TLS: paste the CA certificate, or skip verification (recorded in the audit log)",
];

/** Registers a read-only Proxmox token or Elasticsearch API key. Secrets are write-only and never repopulated. */
export function AddConnection({ type, onTypeChange, onDone }: {
  type: ConnectionType; onTypeChange: (t: ConnectionType) => void; onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [tokenId, setTokenId] = useState("");
  const [secret, setSecret] = useState("");
  const [ca, setCa] = useState("");
  const [insecure, setInsecure] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const proxmox = type === "proxmox";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setSaved(false);
    setBusy(true);
    let created = false;
    try {
      if (proxmox) {
        const c = await api<{ id: string }>("/api/proxmox", { method: "POST", body: JSON.stringify({
          name, api_url: url, token_id: tokenId, token_secret: secret, ca_pem: ca || null, verify_tls: !insecure }) });
        created = true;
        await api(`/api/proxmox/${c.id}/sync`, { method: "POST" });
      } else {
        await api("/api/clusters/register", { method: "POST", body: JSON.stringify({
          urls: [url], api_key: secret, ca_pem: ca || null, verify_tls: !insecure }) });
      }
      setName(""); setUrl(""); setTokenId(""); setCa(""); setInsecure(false);
      setSaved(true);
      onDone();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
      if (created) onDone();
    } finally {
      setSecret(""); // never repopulate a secret after save or failure
      setBusy(false);
    }
  }

  return (
    <section id="add-connection" className="ecm-contact" aria-labelledby="add-title">
      <h2 id="add-title" className="ecm-h2 ecm-h2--center">Add a connection.</h2>
      <div className="ecm-contact__panel">
        <div className="ecm-contact__side">
          <h3 className="ecm-h3">Before you connect</h3>
          <p className="ecm-muted">Create a read-only Proxmox token or an Elasticsearch API key first, then enter it here.</p>
          <ul className="ecm-checklist">{CHECKLIST.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
        <form onSubmit={submit} className="ecm-contact__form" autoComplete="off">
          <h3 className="ecm-h3">Connection details</h3>
          <p className="ecm-muted">Secrets are write-only. ECM never shows them again.</p>
          <EuiFormRow label="Connection type" fullWidth>
            <EuiSelect fullWidth options={TYPES} value={type}
              onChange={(e) => onTypeChange(e.target.value as ConnectionType)} />
          </EuiFormRow>
          {proxmox && (
            <EuiFormRow label="Name" fullWidth>
              <EuiFieldText fullWidth value={name} onChange={(e) => setName(e.target.value)} />
            </EuiFormRow>)}
          <EuiFormRow label={proxmox ? "API URL" : "Endpoint URL"} fullWidth
            helpText={proxmox ? "For example https://pve1.example:8006" : "For example https://es01.example:9200"}>
            <EuiFieldText fullWidth value={url} onChange={(e) => setUrl(e.target.value)} />
          </EuiFormRow>
          {proxmox && (
            <EuiFormRow label="Token ID" fullWidth helpText="Format user@realm!tokenname">
              <EuiFieldText fullWidth value={tokenId} onChange={(e) => setTokenId(e.target.value)} />
            </EuiFormRow>)}
          <EuiFormRow label={proxmox ? "Token secret" : "API key (encoded)"} fullWidth>
            <EuiFieldPassword fullWidth value={secret} autoComplete="off" onChange={(e) => setSecret(e.target.value)} />
          </EuiFormRow>
          <EuiFormRow label="CA certificate (PEM, optional)" fullWidth>
            <EuiTextArea fullWidth rows={4} value={ca} className="ecm-mono" onChange={(e) => setCa(e.target.value)} />
          </EuiFormRow>
          <EuiSwitch label="Skip TLS verification" checked={insecure} onChange={(e) => setInsecure(e.target.checked)} />
          {insecure && (
            <EuiCallOut color="warning" size="s" iconType="warning" className="ecm-callout-in"
              title="Skipping verification is recorded in the audit log." />)}
          {err && <EuiCallOut color="danger" role="alert" size="s" iconType="warning" title={err} />}
          {saved && <p role="status" className="ecm-muted">Connection saved.</p>}
          <EuiButton type="submit" fill fullWidth isLoading={busy}>Save connection</EuiButton>
        </form>
      </div>
    </section>
  );
}
