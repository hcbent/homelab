export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** FastAPI sends a string for most errors and a list of {msg} objects for validation failures. */
function describe(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (typeof d?.msg === "string" ? d.msg.replace(/^Value error, /, "") : null))
      .filter(Boolean);
    return msgs.length ? msgs.join("; ") : undefined;
  }
  return undefined;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-ECM-CSRF": "1", ...init.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, describe(body.detail) ?? res.statusText);
  }
  return res.json();
}

export interface User { username: string; role: string }
export interface Operation {
  id: string; kind: string; state: string; phase: string | null;
  elapsed_seconds: number | null; error: string | null;
  cluster_id?: string | null; cluster_name?: string | null; dry_run?: boolean; parent_op_id?: string | null; started_at?: string | null;
}

/** What a plan will do, as the API stores it. `configure` is what happens to the machines after Terraform. */
export interface PlanSummary {
  adds?: number; updates?: number; deletes?: number; has_changes?: boolean; configure?: string | null;
  /** A restart's plan: how many nodes are restarted and how many are started because they are down. */
  restart?: number; start?: number;
}
export interface OperationStep { seq: number; name: string; status: string; detail: string | null }
export interface OperationLogLine { ts: string; stream: string; line: string }
export interface OperationDetail extends Operation {
  started_at: string | null; finished_at: string | null;
  progress: { done: number; total: number };
  plan: { digest: string; summary: PlanSummary | null; approvable: boolean } | null;
  approval: { digest: string; by: string; at: string } | null;
  result: Record<string, unknown> | null;
  steps: OperationStep[]; logs: OperationLogLine[];
  /** What a change to a built cluster asked for, with a plain description. */
  /** The Kibana machines in the cluster's parameters. A create that asked for Kibana builds one with the cluster. */
  kibana?: PlannedKibana[];
  change?: { kind: string; describe?: string; nodes?: Record<string, unknown>; warnings?: string[]; added?: string[];
             kibana?: Record<string, unknown>; kibana_removed?: string[] } | null;
}

export type Preset = "single_node" | "three_node" | "dedicated_masters";
export interface CreateRequest {
  name: string; version: string; preset: Preset; dry_run: boolean;
  data_nodes?: number; coordinating_nodes?: number;
  sizing?: { cores?: number; ram_mb?: number; os_disk_gb?: number; data_disk_gb?: number };
  proxmox_connection_id?: string; network_profile?: string; template_vmid?: number; datastore?: string;
  pool_id?: string; cpu_type?: string;
  /** Kibana, built in the same plan as the cluster and installed once it is up. Everything in it is optional. */
  kibana?: { public_name?: string; cores?: number; ram_mb?: number; os_disk_gb?: number; pve_node?: string };
}
export interface PlannedNode { name: string; host: string; address: string; vm_id: number }
/** A Kibana machine as a plan or an operation shows it: where it goes and how it is reached. */
export interface PlannedKibana {
  name: string; host: string; address: string; vm_id: number; cores: number; ram_mb: number; os_disk_gb: number;
  public_name: string | null; url: string; public_url: string | null;
}
export interface CreatePlan {
  cluster_id: string; operation_id: string; dry_run: boolean; nodes: PlannedNode[]; warnings: string[];
  /** The Kibana machine planned with the cluster, when it was asked for (empty otherwise). */
  kibana: PlannedKibana[];
}

export interface ClusterSummary {
  id: string; name: string; uuid: string | null; version: string | null;
  health: "green" | "yellow" | "red" | null; ownership: string;
  nodes: number; data_nodes: number;
  infrastructure: { proxmox_hosts: string[]; verified_links: number; total_nodes: number };
  storage: { total_bytes: number; used_bytes: number; used_pct: number | null };
  jvm_heap_used_pct: number | null; jvm_heap_max_pct: number | null;
  last_sync_at: string | null; last_sync_error: string | null;
}

export interface NodeRow {
  id: string; name: string; ip: string | null; version: string | null; roles: string[];
  heap_used_pct: number | null; disk_total_bytes: number | null; disk_avail_bytes: number | null;
  shard_count: number;
  link: { confidence: "verified" | "probable" | "unlinked"; evidence: Record<string, unknown>;
          vm: { pve_node: string; vmid: number; name: string; cpu_cores: number;
                memory_mb: number; disks: { slot: string; size_gb: number | null }[] } | null };
}

/** What can be done to a cluster now. `teardown_of` is the create a teardown would clean up. */
export interface Lifecycle {
  managed: boolean; busy_operation_id?: string | null;
  /** When the Proxmox inventory that node_state is read from was last synced. */
  proxmox_synced_at?: string | null;
  /** Nodes ECM wrote a configuration change to without restarting them, so the change is waiting for a restart. */
  pending_restart?: string[]; teardown_of?: string | null; nodes?: string[];
  bootstrapped?: boolean; can_remove?: boolean; remove_blocker?: string | null;
  /** Each data node's disk in GB, from the recorded state, and whether a change can be planned now. */
  data_disks?: Record<string, number>; can_change?: boolean;
  /** Each node's cores and RAM (MB), from the recorded state. */
  sizes?: Record<string, { cores: number; ram_mb: number }>;
  /** Each node's roles (empty for coordinating only), Proxmox host and whether it counts towards the master quorum. */
  node_roles?: Record<string, { roles: string[]; master_eligible: boolean; holds_data: boolean; host: string | null }>;
  /** What the last syncs saw of each node: whether its machine is in Proxmox (null if unknown) and whether Elasticsearch reports it. */
  node_state?: Record<string, { machine: boolean | null; in_cluster: boolean; vm_status?: string | null }>;
  /** The cluster's Kibana: the machines on record, and whether one can be added now. */
  kibana?: KibanaPanel;
}

/** A Kibana machine on record. `caddy_snippet` is null until it has a public name; ECM only shows it, never applies it. */
export interface KibanaMachine {
  name: string; vm_id: number; address: string; host: string; cores: number; ram_mb: number; os_disk_gb: number;
  public_name: string | null; url: string; public_url: string | null; caddy_snippet: string | null;
  /** Kibana reads its list of Elasticsearch nodes when it starts, so this says the cluster's nodes have changed since: restart it. */
  hosts_out_of_date: boolean;
}
export interface KibanaOpEnd { operation_id: string; state: string; finished_at: string | null }
export interface KibanaPanel {
  machines: KibanaMachine[]; can_add: boolean;
  /** Whether Kibana can be restarted, signed in to or removed now (it exists and nothing else is running on the cluster). */
  can_change: boolean; ca_available: boolean;
  /** How the last Add Kibana ended. It includes the health check, so a succeeded one means Kibana reported itself available. */
  last_add: KibanaOpEnd | null;
  /** Whether ECM holds a working sign-in for the elastic user (never the password itself), when it was set, and how the last attempt ended. */
  login: { set: boolean; reset_at: string | null; last: KibanaOpEnd | null };
  last_restart: KibanaOpEnd | null;
}

export interface ClusterDetail extends ClusterSummary {
  lifecycle?: Lifecycle;
  elasticsearch: {
    health: Record<string, unknown>;
    shards: { by_state: Record<string, number>; by_node: Record<string, number>; unassigned: string[] };
    settings: { persistent: Record<string, unknown>; transient: Record<string, unknown> };
  };
  desired: { managed: boolean; note: string | null };
  node_list: NodeRow[];
}

export interface Vm {
  id: string; pve_node: string; vmid: number; name: string; status: string;
  cpu_cores: number | null; memory_mb: number | null; ips: { ip: string; source: string }[];
  es_cluster_id: string | null; es_link: string | null;
  /** True for machines a create ECM ran made. Only those can be torn down. */
  tf_managed?: boolean;
}
export interface Infrastructure {
  connections: { id: string; name: string; api_url: string; last_sync_at: string | null;
                 last_sync_error: string | null }[];
  nodes: { name: string; status: string; usage: Partial<Record<string, number | null>> }[];
  storages: { node: string; name: string; type: string; shared: boolean; total: number;
              used: number; avail: number }[];
  templates: Vm[]; vms: Vm[];
}

export interface InUseAddress { ip: string; source: "proxmox" | "elasticsearch" | "ecm"; name: string }
export interface NetworkProfile {
  id: string; name: string; bridge: string; vlan: number | null; cidr: string; gateway: string;
  dns: string[]; search_domain: string | null; range_start: string; range_end: string;
  dhcp_start: string | null; dhcp_end: string | null;
  pool_size: number; in_use_in_range: InUseAddress[];
}
