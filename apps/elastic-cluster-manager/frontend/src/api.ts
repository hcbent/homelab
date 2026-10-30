export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-ECM-CSRF": "1", ...init.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json();
}

export interface User { username: string; role: string }
export interface Operation {
  id: string; kind: string; state: string; phase: string | null;
  elapsed_seconds: number | null; error: string | null;
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

export interface ClusterDetail extends ClusterSummary {
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
  nodes: { name: string; status: string; usage: Record<string, number> }[];
  storages: { node: string; name: string; type: string; shared: boolean; total: number;
              used: number; avail: number }[];
  templates: Vm[]; vms: Vm[];
}
