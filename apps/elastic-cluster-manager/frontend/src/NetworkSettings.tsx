import { EuiButton, EuiCallOut, EuiFieldNumber, EuiFieldText, EuiFormRow, EuiLoadingSpinner } from "@elastic/eui";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, NetworkProfile } from "./api";

const SOURCE = { proxmox: "Proxmox", elasticsearch: "Elasticsearch", ecm: "ECM (a Kibana machine it made)" } as const;

/** A profile row is only trusted if it has the fields the form edits; anything else is ignored. */
const isProfile = (p: unknown): p is NetworkProfile =>
  typeof p === "object" && p !== null && "range_start" in p && "range_end" in p && "cidr" in p;

function ProfileForm({ profile, onSaved }: { profile: NetworkProfile; onSaved: (p: NetworkProfile) => void }) {
  const [f, setF] = useState({
    name: profile.name, bridge: profile.bridge, vlan: profile.vlan === null ? "" : String(profile.vlan),
    cidr: profile.cidr, gateway: profile.gateway, dns: profile.dns.join(", "),
    search_domain: profile.search_domain ?? "", range_start: profile.range_start, range_end: profile.range_end,
    dhcp_start: profile.dhcp_start ?? "", dhcp_end: profile.dhcp_end ?? "",
  });
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF({ ...f, [k]: e.target.value });
    setSaved(false);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setSaved(false);
    setBusy(true);
    try {
      // Only the editable fields are sent; the server computes pool size and in-use addresses.
      const next = await api<NetworkProfile>(`/api/network-profiles/${profile.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: f.name, bridge: f.bridge, vlan: f.vlan.trim() === "" ? null : Number(f.vlan),
          cidr: f.cidr, gateway: f.gateway,
          dns: f.dns.split(",").map((d) => d.trim()).filter(Boolean),
          search_domain: f.search_domain.trim() === "" ? null : f.search_domain.trim(),
          range_start: f.range_start, range_end: f.range_end,
          dhcp_start: f.dhcp_start.trim() === "" ? null : f.dhcp_start.trim(),
          dhcp_end: f.dhcp_end.trim() === "" ? null : f.dhcp_end.trim(),
        }),
      });
      onSaved(next);
      setSaved(true);
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  }

  const clash = profile.in_use_in_range;
  return (
    <form onSubmit={submit} className="ecm-network__form" aria-label={`Network profile ${profile.name}`}>
      <div className="ecm-network__range">
        <EuiFormRow label="Allocation range start" fullWidth>
          <EuiFieldText fullWidth value={f.range_start} onChange={set("range_start")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="Allocation range end" fullWidth>
          <EuiFieldText fullWidth value={f.range_end} onChange={set("range_end")} className="ecm-mono" />
        </EuiFormRow>
      </div>
      <p className="ecm-muted ecm-network__hint">
        {profile.pool_size} addresses.{" "}
        {profile.dhcp_start && profile.dhcp_end
          ? `Kept clear of your DHCP range ${profile.dhcp_start}-${profile.dhcp_end}.`
          : "Use addresses your DHCP server never hands out. ECM cannot check this unless you enter the DHCP range."}
      </p>
      {clash.length > 0 && (
        <EuiCallOut color="warning" size="s" iconType="warning"
          title={`${clash.length} address${clash.length > 1 ? "es" : ""} in this range already in use`}>
          <p>ECM skips them when it allocates, but check they are not reserved elsewhere.</p>
          <ul className="ecm-plain ecm-mono">
            {clash.map((c) => <li key={c.ip}>{c.ip} · {c.name} · {SOURCE[c.source]}</li>)}
          </ul>
        </EuiCallOut>
      )}
      <div className="ecm-network__range">
        <EuiFormRow label="DHCP range start (optional)" fullWidth
          helpText="ECM refuses an allocation range that overlaps this">
          <EuiFieldText fullWidth value={f.dhcp_start} onChange={set("dhcp_start")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="DHCP range end (optional)" fullWidth>
          <EuiFieldText fullWidth value={f.dhcp_end} onChange={set("dhcp_end")} className="ecm-mono" />
        </EuiFormRow>
      </div>
      <div className="ecm-network__grid">
        <EuiFormRow label="Subnet (CIDR)" fullWidth>
          <EuiFieldText fullWidth value={f.cidr} onChange={set("cidr")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="Gateway" fullWidth>
          <EuiFieldText fullWidth value={f.gateway} onChange={set("gateway")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="DNS servers" fullWidth helpText="Separate with commas">
          <EuiFieldText fullWidth value={f.dns} onChange={set("dns")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="Search domain" fullWidth>
          <EuiFieldText fullWidth value={f.search_domain} onChange={set("search_domain")} />
        </EuiFormRow>
        <EuiFormRow label="Bridge" fullWidth>
          <EuiFieldText fullWidth value={f.bridge} onChange={set("bridge")} className="ecm-mono" />
        </EuiFormRow>
        <EuiFormRow label="VLAN" fullWidth helpText="Leave empty for untagged">
          <EuiFieldNumber fullWidth min={1} max={4094} value={f.vlan} onChange={set("vlan")} />
        </EuiFormRow>
      </div>
      {err && <EuiCallOut color="danger" role="alert" size="s" iconType="warning" title={err} />}
      {saved && <p role="status" className="ecm-muted">Saved. New clusters will use this range.</p>}
      <EuiButton type="submit" fill isLoading={busy}>Save network settings</EuiButton>
    </form>
  );
}

export function NetworkSettings() {
  const [profiles, setProfiles] = useState<NetworkProfile[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<unknown>("/api/network-profiles")
      .then((rows) => { setProfiles(Array.isArray(rows) ? rows.filter(isProfile) : []); setLoadError(null); })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  return (
    <section id="network" className="ecm-network" aria-labelledby="network-title">
      <h2 id="network-title" className="ecm-h2 ecm-h2--center">Network for new nodes.</h2>
      <p className="ecm-lede ecm-lede--small ecm-network__lede">
        New Elasticsearch nodes get their addresses from this range. Change it here whenever your DHCP
        reservations change.
      </p>
      {loadError && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not load network settings">
          <p>{loadError}</p><EuiButton size="s" onClick={load}>Retry</EuiButton>
        </EuiCallOut>)}
      {profiles === null && !loadError && <p role="status"><EuiLoadingSpinner size="m" /> Loading network settings…</p>}
      {profiles?.map((p) => (
        <div key={p.id} className="ecm-network__panel">
          <h3 className="ecm-h3">{p.name}</h3>
          <ProfileForm profile={p}
            onSaved={(next) => setProfiles((all) => all?.map((x) => (x.id === next.id ? next : x)) ?? null)} />
        </div>))}
    </section>
  );
}
