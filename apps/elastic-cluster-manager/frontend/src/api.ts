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
  cluster_id?: string | null; dry_run?: boolean; parent_op_id?: string | null; started_at?: string | null;
}

/** What a plan will do, as the API stores it. `configure` is what happens to the machines after Terraform. */
export interface PlanSummary {
  adds?: number; updates?: number; deletes?: number; has_changes?: boolean; configure?: string | null;
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
}

export type Preset = "single_node" | "three_node" | "dedicated_masters";
export interface CreateRequest {
  name: string; version: string; preset: Preset; dry_run: boolean;
  data_nodes?: number; coordinating_nodes?: number;
  sizing?: { cores?: number; ram_mb?: number; os_disk_gb?: number; data_disk_gb?: number };
  proxmox_connection_id?: string; network_profile?: string; template_vmid?: number; datastore?: string;
  pool_id?: string; cpu_type?: string;
}
export interface PlannedNode { name: string; host: string; address: string; vm_id: number }
export interface CreatePlan {
  cluster_id: string; operation_id: string; dry_run: boolean; nodes: PlannedNode[]; warnings: string[];
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
  managed: boolean; busy_operation_id?: string | null; teardown_of?: string | null; nodes?: string[];
  bootstrapped?: boolean; can_remove?: boolean; remove_blocker?: string | null;
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
}
export interface Infrastructure {
  connections: { id: string; name: string; api_url: string; last_sync_at: string | null;
                 last_sync_error: string | null }[];
  nodes: { name: string; status: string; usage: Partial<Record<string, number | null>> }[];
  storages: { node: string; name: string; type: string; shared: boolean; total: number;
              used: number; avail: number }[];
  templates: Vm[]; vms: Vm[];
}

export interface InUseAddress { ip: string; source: "proxmox" | "elasticsearch"; name: string }
export interface NetworkProfile {
  id: string; name: string; bridge: string; vlan: number | null; cidr: string; gateway: string;
  dns: string[]; search_domain: string | null; range_start: string; range_end: string;
  dhcp_start: string | null; dhcp_end: string | null;
  pool_size: number; in_use_in_range: InUseAddress[];
}
