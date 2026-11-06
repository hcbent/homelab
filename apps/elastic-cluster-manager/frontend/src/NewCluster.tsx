import {
  EuiBasicTable, EuiBasicTableColumn, EuiButton, EuiButtonEmpty, EuiCallOut, EuiDescriptionList, EuiFieldNumber,
  EuiFieldText, EuiFormRow, EuiLink, EuiLoadingSpinner, EuiPanel, EuiRadioGroup, EuiSelect, EuiStepsHorizontal,
} from "@elastic/eui";
import { useEffect, useRef, useState } from "react";
import {
  api, ApiError, CreatePlan, CreateRequest, Infrastructure, NetworkProfile, OperationDetail, PlannedNode, Preset,
} from "./api";
import { terraformText } from "./OperationDetail";
import { useInterval } from "./useInterval";

export const WIZARD_STEPS = ["Name", "Topology", "Sizing", "Infrastructure", "Review", "Build"] as const;
const REVIEW = 4;
const BUILD = 5;

/** What a node gets when nothing is changed (data nodes; master-only and coordinating nodes default smaller). */
export const SIZE_DEFAULTS = { cores: "4", ramGb: "8", osDisk: "32", dataDisk: "100" };

export interface Form {
  name: string; version: string; preset: Preset; dataNodes: string; coordinating: string;
  cores: string; ramGb: string; osDisk: string; dataDisk: string;
  connection: string; profile: string; template: string; datastore: string; pool: string; cpuType: string;
}
export const EMPTY_FORM: Form = {
  name: "", version: "", preset: "three_node", dataNodes: "3", coordinating: "0", ...SIZE_DEFAULTS,
  connection: "", profile: "", template: "", datastore: "", pool: "", cpuType: "",
};

const NAME_RE = /^[a-z][a-z0-9-]{0,38}[a-z0-9]$/;
const VERSION_RE = /^\d+\.\d+\.\d+$/;
const PVE_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const STEP_FIELDS: (keyof Form)[][] = [
  ["name", "version"], ["dataNodes", "coordinating"], ["cores", "ramGb", "osDisk", "dataDisk"],
  ["pool", "cpuType"], [], [],
];

const whole = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : NaN);
function range(v: string, min: number, max: number, what: string): string | null {
  const n = whole(v);
  if (Number.isNaN(n)) return `${what} must be a whole number.`;
  return n < min || n > max ? `${what} must be between ${min} and ${max}.` : null;
}

/** Problems with the form, keyed by field. Only fields that apply to the chosen topology are checked. */
export function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {};
  if (!f.name) e.name = "Enter a name.";
  else if (!NAME_RE.test(f.name)) {
    e.name = "Use 2 to 40 lowercase letters, digits and hyphens, starting with a letter and not ending with a hyphen.";
  }
  if (!f.version) e.version = "Choose a version.";
  else if (!VERSION_RE.test(f.version)) e.version = "A version looks like 9.5.6.";
  if (f.preset === "dedicated_masters") {
    const d = range(f.dataNodes, 1, 40, "Data nodes");
    const c = range(f.coordinating, 0, 20, "Coordinating nodes");
    if (d) e.dataNodes = d;
    if (c) e.coordinating = c;
  }
  const sizes: [keyof Form, number, number, string][] = [
    ["cores", 1, 64, "Cores"], ["ramGb", 2, 512, "RAM"], ["osDisk", 16, 2048, "The OS disk"],
    ["dataDisk", 10, 65536, "The data disk"],
  ];
  for (const [key, min, max, what] of sizes) {
    const problem = range(f[key], min, max, what);
    if (problem) e[key] = problem;
  }
  if (f.pool && !PVE_RE.test(f.pool)) e.pool = "Use letters, digits, dots, underscores and hyphens.";
  if (f.cpuType && !PVE_RE.test(f.cpuType)) e.cpuType = "Use letters, digits, dots, underscores and hyphens.";
  return e;
}

/** The request for this form. Sizes are sent only when changed, so a preset's own smaller defaults for master-only
 * and coordinating nodes are not overridden by accident. */
export function toRequest(f: Form, dryRun: boolean): CreateRequest {
  const body: CreateRequest = { name: f.name, version: f.version, preset: f.preset, dry_run: dryRun };
  if (f.preset === "dedicated_masters") {
    body.data_nodes = Number(f.dataNodes);
    body.coordinating_nodes = Number(f.coordinating);
  }
  const sizing: NonNullable<CreateRequest["sizing"]> = {};
  if (f.cores !== SIZE_DEFAULTS.cores) sizing.cores = Number(f.cores);
  if (f.ramGb !== SIZE_DEFAULTS.ramGb) sizing.ram_mb = Number(f.ramGb) * 1024;
  if (f.osDisk !== SIZE_DEFAULTS.osDisk) sizing.os_disk_gb = Number(f.osDisk);
  if (f.dataDisk !== SIZE_DEFAULTS.dataDisk) sizing.data_disk_gb = Number(f.dataDisk);
  if (Object.keys(sizing).length) body.sizing = sizing;
  if (f.connection) body.proxmox_connection_id = f.connection;
  if (f.profile) body.network_profile = f.profile;
  if (f.template) body.template_vmid = Number(f.template);
  if (f.datastore) body.datastore = f.datastore;
  if (f.pool) body.pool_id = f.pool;
  if (f.cpuType) body.cpu_type = f.cpuType;
  return body;
}

const PRESETS: { id: Preset; label: string }[] = [
  { id: "single_node", label: "Single node: one node with every role. No replicas, so health stays yellow." },
  { id: "three_node", label: "Three nodes: each can be master and holds data. The smallest cluster that survives losing a node." },
  { id: "dedicated_masters", label: "Dedicated masters: three master-only nodes plus data nodes, and optional coordinating nodes." },
];

export function topologyText(f: Form): string {
  if (f.preset === "single_node") return "Single node";
  if (f.preset === "three_node") return "Three nodes, all roles";
  const c = Number(f.coordinating) || 0;
  return `3 masters + ${f.dataNodes || "?"} data${c ? ` + ${c} coordinating` : ""}`;
}
const sizingText = (f: Form) => `${f.cores} cores, ${f.ramGb} GiB RAM, ${f.dataDisk} GB data`;
const message = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

interface Choices {
  connections: Infrastructure["connections"]; templates: Infrastructure["templates"];
  storages: string[]; profiles: NetworkProfile[];
}

/** The dry run's own operation: polls until the plan is made, then reports whether it can be built. */
function PlanPreview({ plan, onSettled }: { plan: CreatePlan; onSettled: (ok: boolean) => void }) {
  const [op, setOp] = useState<OperationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const settled = useRef(false);
  const load = () => {
    api<OperationDetail>(`/api/operations/${plan.operation_id}`).then((o) => {
      setOp(o);
      if (!settled.current && ["succeeded", "failed", "cancelled"].includes(o.state)) {
        settled.current = true;
        onSettled(o.state === "succeeded" && o.plan !== null);
      }
    }).catch((e) => setError(message(e)));
  };
  useEffect(load, [plan.operation_id]);
  useInterval(load, settled.current ? 0 : 1.5);

  const columns: EuiBasicTableColumn<PlannedNode>[] = [
    { field: "name", name: "Node", render: (v: string) => <span className="ecm-mono">{v}</span> },
    { field: "host", name: "Proxmox host", render: (v: string) => <span className="ecm-mono">{v}</span> },
    { field: "address", name: "Address", render: (v: string) => <span className="ecm-mono">{v}</span> },
    { field: "vm_id", name: "VM ID" },
  ];
  const summary = op?.plan?.summary ?? null;
  return (
    <div className="ecm-stack-lg">
      <h4 className="ecm-label">Where each node would run</h4>
      <EuiBasicTable<PlannedNode> tableCaption="Where each node would run" items={plan.nodes} columns={columns}
        rowHeader="name" />
      {plan.warnings.map((w) => (
        <EuiCallOut key={w} size="s" color="warning" iconType="warning" title={w} />))}
      {error && <EuiCallOut color="danger" role="alert" iconType="warning" title="Could not read the plan"><p>{error}</p></EuiCallOut>}
      {!op && !error && <p role="status"><EuiLoadingSpinner size="m" /> Checking the plan with Terraform…</p>}
      {op && op.state === "running" && <p role="status"><EuiLoadingSpinner size="m" /> Checking the plan with Terraform…</p>}
      {op && op.state === "failed" && (
        <EuiCallOut color="danger" role="alert" iconType="warning" title="The plan could not be made">
          <p>{op.error}</p></EuiCallOut>)}
      {op && op.state === "succeeded" && summary && <h4 className="ecm-label">If you approve</h4>}
      {op && op.state === "succeeded" && summary && (
        <EuiDescriptionList type="column" compressed listItems={[
          { title: "On Proxmox", description: terraformText(op.kind, summary) },
          ...(summary.configure
            ? [{ title: "Then", description: summary.configure.charAt(0).toUpperCase() + summary.configure.slice(1) }]
            : []),
        ]} />)}
    </div>
  );
}

export function NewCluster() {
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [step, setStep] = useState(0);
  const [reach, setReach] = useState(0);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [versions, setVersions] = useState<string[] | null>(null);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Choices | null>(null);
  const [choicesError, setChoicesError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [review, setReview] = useState<{ key: string; phase: "running" | "planned" | "refused";
    plan?: CreatePlan; error?: string } | null>(null);
  const [previewOk, setPreviewOk] = useState<boolean | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const requested = useRef<string | null>(null);

  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));
  const touch = (k: string) => setTouched((t) => new Set(t).add(k));
  const errors = validate(form);
  const stepOk = (n: number) => STEP_FIELDS[n].every((k) => !errors[k]);
  const err = (k: keyof Form) => (touched.has(k) && errors[k] ? errors[k] : undefined);

  useEffect(() => {
    api<{ versions: string[] }>("/api/versions").then((r) => {
      setVersions(r.versions);
      setForm((f) => (f.version || !r.versions.length ? f : { ...f, version: r.versions[0] }));
    }).catch((e) => setVersionsError(message(e)));
    Promise.all([api<Infrastructure>("/api/infrastructure"), api<NetworkProfile[]>("/api/network-profiles")])
      .then(([infra, profiles]) => {
        setChoices({
          connections: infra.connections, templates: infra.templates, profiles,
          storages: [...new Set(infra.storages.map((s) => s.name))].sort(),
        });
        setForm((f) => ({
          ...f,
          profile: f.profile || (profiles.find((p) => p.name === "default") ?? (profiles.length === 1 ? profiles[0] : undefined))?.name || "",
          connection: f.connection || (infra.connections.length === 1 ? infra.connections[0].id : ""),
        }));
      }).catch((e) => setChoicesError(message(e)));
  }, []);

  const dryRequest = JSON.stringify(toRequest(form, true));
  const runKey = `${attempt}:${dryRequest}`;
  useEffect(() => {
    if (step !== REVIEW || requested.current === runKey) return;
    requested.current = runKey;
    setReview({ key: runKey, phase: "running" });
    setPreviewOk(null);
    api<CreatePlan>("/api/clusters", { method: "POST", body: dryRequest })
      .then((plan) => { if (requested.current === runKey) setReview({ key: runKey, phase: "planned", plan }); })
      .catch((e) => { if (requested.current === runKey) setReview({ key: runKey, phase: "refused", error: message(e) }); });
  }, [step, runKey, dryRequest]);

  const go = (n: number) => {
    const next = Math.max(0, Math.min(BUILD, n));
    setStep(next);
    setReach((r) => Math.max(r, next));
  };
  const canContinue = stepOk(step) && (step !== REVIEW || (review?.phase === "planned" && previewOk === true));

  async function planBuild() {
    setBuilding(true);
    setBuildError(null);
    try {
      const plan = await api<CreatePlan>("/api/clusters", { method: "POST", body: JSON.stringify(toRequest(form, false)) });
      window.location.hash = `#/operations/${plan.operation_id}`;
    } catch (e) {
      setBuildError(message(e));
    } finally {
      setBuilding(false);
    }
  }

  const connection = choices?.connections.find((c) => c.id === form.connection);
  const summary = [
    { title: "Name", description: form.name || "Not set" },
    { title: "Version", description: form.version || "Not set" },
    { title: "Topology", description: topologyText(form) },
    { title: "Sizing", description: sizingText(form) },
    { title: "Infrastructure", description: [connection?.name, form.profile && `network ${form.profile}`]
      .filter(Boolean).join(", ") || "ECM defaults" },
  ];

  const field = (label: string, key: keyof Form, props: { help?: string; placeholder?: string } = {}) => (
    <EuiFormRow label={label} fullWidth helpText={props.help} isInvalid={!!err(key)} error={err(key)}>
      <EuiFieldText fullWidth value={form[key]} placeholder={props.placeholder} isInvalid={!!err(key)}
        onChange={(e) => set({ [key]: e.target.value } as Partial<Form>)} onBlur={() => touch(key)} />
    </EuiFormRow>);
  const num = (label: string, key: keyof Form, help?: string) => (
    <EuiFormRow label={label} fullWidth helpText={help} isInvalid={!!err(key)} error={err(key)}>
      <EuiFieldNumber fullWidth value={form[key]} isInvalid={!!err(key)}
        onChange={(e) => set({ [key]: e.target.value } as Partial<Form>)} onBlur={() => touch(key)} />
    </EuiFormRow>);

  const heap = Math.min(Math.floor((Number(form.ramGb) || 0) / 2), 31);

  return (
    <section className="ecm-wizard" aria-labelledby="wizard-title">
      <div className="ecm-wizard__top">
        <div>
          <p className="ecm-eyebrow"><span className="ecm-square" aria-hidden="true" />New cluster</p>
          <h2 id="wizard-title" className="ecm-h2 ecm-h2--large">Create a cluster, one decision at a time.</h2>
          <p className="ecm-lede ecm-lede--small">
            ECM checks the plan with a dry run first. Nothing is created until you approve the plan.</p>
        </div>
        <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-wizard__summary">
          <EuiDescriptionList type="column" compressed listItems={summary} />
        </EuiPanel>
      </div>

      <EuiPanel hasBorder hasShadow={false} paddingSize="l" borderRadius="m" className="ecm-wizard__form ecm-step-in"
        key={`step-${step}`}>
        <span className="ecm-wizard__num">{String(step + 1).padStart(2, "0")}</span>
        <h3 className="ecm-h3 ecm-mono">/ {WIZARD_STEPS[step]}</h3>

        {step === 0 && (
          <>
            {field("Cluster name", "name", { help: `2 to 40 lowercase letters, digits and hyphens. Nodes are named ${form.name || "name"}-01, ${form.name || "name"}-02 and so on.` })}
            {versions ? (
              <EuiFormRow label="Elasticsearch version" fullWidth isInvalid={!!err("version")} error={err("version")}
                helpText="Published releases of 8.x and later, newest first.">
                <EuiSelect fullWidth value={form.version} onBlur={() => touch("version")}
                  options={versions.map((v, i) => ({ value: v, text: i === 0 ? `${v} (newest)` : v }))}
                  onChange={(e) => set({ version: e.target.value })} />
              </EuiFormRow>
            ) : versionsError ? (
              <>
                <EuiCallOut size="s" color="warning" iconType="warning" title="Could not load the list of versions">
                  <p>{versionsError} Type a version instead; ECM checks it when it plans.</p></EuiCallOut>
                {field("Elasticsearch version", "version", { placeholder: "9.5.6" })}
              </>
            ) : <p role="status"><EuiLoadingSpinner size="m" /> Loading versions…</p>}
          </>)}

        {step === 1 && (
          <>
            <EuiRadioGroup name="preset" legend={{ children: "Topology", display: "hidden" }} options={PRESETS.map(({ id, label }) => ({ id, label }))}
              idSelected={form.preset} onChange={(id) => set({ preset: id as Preset })} />
            {form.preset === "dedicated_masters" && (
              <div className="ecm-form-row">
                {num("Data nodes", "dataNodes", "Each holds data and runs ingest.")}
                {num("Coordinating nodes", "coordinating", "Route requests only; no data and no master role.")}
              </div>)}
            <EuiCallOut size="s" color="primary" iconType="iInCircle" className="ecm-gap"
              title="Master-eligible nodes go on different Proxmox hosts">
              <p>A plan that would leave a host holding enough of them to break the master quorum if it were lost is
                refused, and the review step says which host and why.</p></EuiCallOut>
          </>)}

        {step === 2 && (
          <>
            <div className="ecm-form-row">
              {num("Cores per node", "cores")}
              {num("RAM per node (GiB)", "ramGb", `JVM heap is half of RAM, at most 31 GiB: ${heap} GiB here.`)}
            </div>
            <div className="ecm-form-row">
              {num("OS disk (GB)", "osDisk")}
              {num("Data disk (GB)", "dataDisk", "Only nodes that hold data get one.")}
            </div>
            {form.preset === "dedicated_masters" && (
              <p className="ecm-small">Master-only and coordinating nodes default to 2 cores and 4 GiB. A value you
                change here applies to every node.</p>)}
          </>)}

        {step === 3 && (
          <>
            {choicesError && (
              <EuiCallOut size="s" color="warning" iconType="warning" title="Could not load the choices">
                <p>{choicesError} ECM will use its defaults for everything below.</p></EuiCallOut>)}
            {!choices && !choicesError && <p role="status"><EuiLoadingSpinner size="m" /> Loading choices…</p>}
            {choices && (
              <>
                {choices.connections.length > 1 ? (
                  <EuiFormRow label="Proxmox connection" fullWidth>
                    <EuiSelect fullWidth hasNoInitialSelection={!form.connection} value={form.connection}
                      options={choices.connections.map((c) => ({ value: c.id, text: c.name }))}
                      onChange={(e) => set({ connection: e.target.value })} />
                  </EuiFormRow>
                ) : <p className="ecm-small">Proxmox connection: <span className="ecm-mono">{connection?.name ?? "none"}</span></p>}
                <EuiFormRow label="Network profile" fullWidth helpText="Its bridge, VLAN, subnet and address range.">
                  <EuiSelect fullWidth value={form.profile}
                    options={[{ value: "", text: "ECM default" }, ...choices.profiles.map((p) => ({
                      value: p.name, text: `${p.name} (${p.cidr}${p.vlan ? `, VLAN ${p.vlan}` : ""})` }))]}
                    onChange={(e) => set({ profile: e.target.value })} />
                </EuiFormRow>
                <EuiFormRow label="VM template" fullWidth>
                  <EuiSelect fullWidth value={form.template}
                    options={[{ value: "", text: "ECM default" }, ...choices.templates.map((t) => ({
                      value: String(t.vmid), text: `${t.name} (${t.vmid} on ${t.pve_node})` }))]}
                    onChange={(e) => set({ template: e.target.value })} />
                </EuiFormRow>
                <EuiFormRow label="Datastore" fullWidth>
                  <EuiSelect fullWidth value={form.datastore}
                    options={[{ value: "", text: "ECM default" }, ...choices.storages.map((s) => ({ value: s, text: s }))]}
                    onChange={(e) => set({ datastore: e.target.value })} />
                </EuiFormRow>
              </>)}
            <div className="ecm-form-row">
              {field("Proxmox pool", "pool", { placeholder: "ecm" })}
              {field("CPU type", "cpuType", { placeholder: "host", help: "host exposes the real CPU features." })}
            </div>
          </>)}

        {step === REVIEW && (
          <>
            {review?.phase === "running" && <p role="status"><EuiLoadingSpinner size="m" /> Planning a dry run…</p>}
            {review?.phase === "refused" && (
              <EuiCallOut color="danger" role="alert" iconType="warning" title="ECM cannot plan this cluster">
                <p>{review.error}</p>
                <p>Go back and change the choices, or free capacity in Proxmox. ECM plans from its last sync, so
                  after moving machines sync Proxmox from <EuiLink href="#/infrastructure">Infrastructure</EuiLink>, then
                  try again.</p>
                <EuiButton size="s" onClick={() => setAttempt((a) => a + 1)}>Try again</EuiButton>
              </EuiCallOut>)}
            {review?.phase === "planned" && review.plan && (
              <PlanPreview key={review.plan.operation_id} plan={review.plan} onSettled={setPreviewOk} />)}
          </>)}

        {step === BUILD && (
          <>
            <p>ECM will make a plan you can approve. You review and approve it on the next screen; nothing is created
              before then.</p>
            <EuiDescriptionList type="column" compressed listItems={summary} />
            {buildError && (
              <EuiCallOut color="danger" role="alert" iconType="warning" title="ECM cannot plan this cluster">
                <p>{buildError}</p></EuiCallOut>)}
            <div className="ecm-wizard__actions">
              <EuiButton fill isLoading={building} onClick={planBuild}>Plan the build</EuiButton>
            </div>
          </>)}

        <div className="ecm-wizard__actions">
          <EuiButtonEmpty iconType="arrowLeft" isDisabled={step === 0} onClick={() => go(step - 1)}>Back</EuiButtonEmpty>
          {step < BUILD && (
            <EuiButton fill isDisabled={!canContinue} onClick={() => go(step + 1)}>Continue</EuiButton>)}
        </div>
      </EuiPanel>

      <EuiStepsHorizontal className="ecm-wizard__strip" steps={WIZARD_STEPS.map((title, i) => ({
        title, status: i < step ? "complete" : i === step ? "current" : "incomplete",
        disabled: i > reach, onClick: () => go(i),
      }))} />
    </section>
  );
}
