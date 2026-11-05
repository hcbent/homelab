"""Placement: recommend a Proxmox host for each node of a desired cluster.

A recommendation, never a decision. The user can override it, and nodes can be pinned with NodeSpec.pve_node.
Pure and deterministic: the same inputs always give the same answer, so a plan generated from fixtures is
reproducible.

How a host is chosen for a node:
  1. Hard filters: the host is online, has the datastore, enough free RAM (after a host reserve), vCPU room
     (within an overcommit ratio) and enough free disk. Shared datastores are counted once, not per host.
  2. Anti-affinity: master-eligible nodes go to the host holding the fewest master-eligible nodes already, so a
     3-master cluster on 3 hosts puts one on each. All nodes also prefer hosts holding fewer of this cluster.
  3. Score: free RAM, vCPU headroom and free disk left AFTER the placement, as a tie-breaker.

Free RAM is computed from the larger of actual use and the RAM configured for running VMs, because an idle VM
that has not touched its memory yet still needs it.
"""
from collections import Counter
from dataclasses import dataclass, field

from .models import DesiredState, NodeSpec

GIB = 1024**3


@dataclass
class Datastore:
    name: str
    shared: bool
    avail_bytes: int
    total_bytes: int


@dataclass
class HostView:
    name: str
    online: bool
    cores: int
    mem_total: int  # bytes
    mem_used: int  # bytes, as reported by Proxmox
    committed_vcpus: int = 0  # vCPUs configured on running VMs
    committed_mem: int = 0  # bytes configured on running VMs
    datastores: dict[str, Datastore] = field(default_factory=dict)


@dataclass
class PlacementConfig:
    datastore: str = "tank"
    cpu_overcommit: float = 2.0  # committed vCPUs may reach cores * this
    reserve_floor_bytes: int = 2 * GIB  # RAM always left to the host
    reserve_fraction: float = 0.05  # or this share of total RAM, whichever is larger
    w_ram: float = 0.5
    w_cpu: float = 0.3
    w_disk: float = 0.2


@dataclass
class Placement:
    host: str
    score: float


@dataclass
class PlacementIssue:
    severity: str  # "error" or "warning"
    message: str
    node: str | None = None


@dataclass
class PlacementResult:
    assignments: dict[str, Placement] = field(default_factory=dict)
    issues: list[PlacementIssue] = field(default_factory=list)
    quorum_safe: bool = True

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def hosts(self) -> dict[str, str]:
        return {name: p.host for name, p in self.assignments.items()}


def host_views_from_rows(nodes: list[dict], storages: list[dict], vms: list[dict]) -> list[HostView]:
    """Build host views from the rows ECM stores (pve_nodes, pve_storages, vms), as dicts.

    Templates and stopped VMs reserve nothing. A node with no usage data is treated as offline for placement,
    because its free capacity is unknown.
    """
    committed_cpu: Counter = Counter()
    committed_mem: Counter = Counter()
    for v in vms:
        if v.get("is_template") or v.get("status") != "running":
            continue
        committed_cpu[v["pve_node"]] += v.get("cpu_cores") or 0
        committed_mem[v["pve_node"]] += (v.get("memory_mb") or 0) * 1024 * 1024

    out: list[HostView] = []
    for n in sorted(nodes, key=lambda x: x["name"]):
        usage = n.get("usage") or {}
        known = usage.get("maxcpu") is not None and usage.get("maxmem") is not None
        stores = {
            s["name"]: Datastore(s["name"], bool(s.get("shared")), int(s.get("avail") or 0),
                                 int(s.get("total") or 0))
            for s in storages
            if s["node"] == n["name"] and s.get("active", True)
        }
        out.append(HostView(
            name=n["name"], online=n.get("status") == "online" and known,
            cores=int(usage.get("maxcpu") or 0), mem_total=int(usage.get("maxmem") or 0),
            mem_used=int(usage.get("mem") or 0), committed_vcpus=committed_cpu[n["name"]],
            committed_mem=committed_mem[n["name"]], datastores=stores))
    return out


def _disk_need(node: NodeSpec) -> int:
    return (node.os_disk_gb + (node.data_disk_gb or 0)) * GIB


class _Ledger:
    """What this plan has already claimed, so later nodes see the capacity earlier ones used."""

    def __init__(self, hosts: list[HostView], cfg: PlacementConfig):
        self.cfg = cfg
        self.hosts = {h.name: h for h in hosts}
        self.vcpus: Counter = Counter()
        self.mem: Counter = Counter()
        self.disk: Counter = Counter()  # keyed by datastore identity

    def _store_key(self, host: HostView) -> tuple:
        ds = host.datastores[self.cfg.datastore]
        return (ds.name,) if ds.shared else (host.name, ds.name)

    def _reserve(self, host: HostView) -> int:
        return max(self.cfg.reserve_floor_bytes, int(host.mem_total * self.cfg.reserve_fraction))

    def evaluate(self, host: HostView, node: NodeSpec) -> tuple[list[str], float]:
        """Reasons the node does not fit here (empty when it fits) and its score if it does."""
        why: list[str] = []
        if not host.online:
            return ["host is offline or reports no usage data"], 0.0
        ds = host.datastores.get(self.cfg.datastore)
        if ds is None:
            return [f"datastore '{self.cfg.datastore}' is not available on this host"], 0.0

        ram_need = node.ram_mb * 1024 * 1024
        free_mem = host.mem_total - max(host.mem_used, host.committed_mem) - self.mem[host.name]
        free_mem_after = free_mem - ram_need
        if free_mem_after < self._reserve(host):
            why.append(f"not enough free RAM ({free_mem / GIB:.1f} GiB free, needs "
                       f"{ram_need / GIB:.1f} GiB plus a {self._reserve(host) / GIB:.1f} GiB reserve)")

        cpu_cap = host.cores * self.cfg.cpu_overcommit
        cpu_after = host.committed_vcpus + self.vcpus[host.name] + node.cores
        if cpu_after > cpu_cap:
            why.append(f"not enough vCPU room ({cpu_after:.0f} vCPUs would exceed "
                       f"{cpu_cap:.0f}, {self.cfg.cpu_overcommit:g}x of {host.cores} cores)")

        disk_need = _disk_need(node)
        free_disk = ds.avail_bytes - self.disk[self._store_key(host)]
        if free_disk < disk_need:
            why.append(f"not enough free disk on '{ds.name}' ({free_disk / GIB:.0f} GiB free, "
                       f"needs {disk_need / GIB:.0f} GiB)")
        if why:
            return why, 0.0

        ram_frac = free_mem_after / host.mem_total if host.mem_total else 0.0
        cpu_frac = max(0.0, 1 - cpu_after / cpu_cap) if cpu_cap else 0.0
        disk_frac = (free_disk - disk_need) / ds.total_bytes if ds.total_bytes else 0.0
        c = self.cfg
        score = c.w_ram * ram_frac + c.w_cpu * cpu_frac + c.w_disk * max(0.0, disk_frac)
        return [], round(score, 6)

    def claim(self, host: HostView, node: NodeSpec) -> None:
        self.vcpus[host.name] += node.cores
        self.mem[host.name] += node.ram_mb * 1024 * 1024
        self.disk[self._store_key(host)] += _disk_need(node)


def recommend_placement(
    state: DesiredState,
    hosts: list[HostView],
    config: PlacementConfig | None = None,
    *,
    existing_master_counts: dict[str, int] | None = None,
    existing_node_counts: dict[str, int] | None = None,
) -> PlacementResult:
    """Recommend a host for every node. Pass existing_* when adding nodes to a running cluster."""
    cfg = config or PlacementConfig()
    ledger = _Ledger(hosts, cfg)
    masters: Counter = Counter(existing_master_counts or {})
    cluster: Counter = Counter(existing_node_counts or {})
    result = PlacementResult()
    known = {h.name for h in hosts}

    # Pinned nodes are inflexible, so they claim capacity first. Then masters, then the rest by RAM.
    def order(n: NodeSpec) -> tuple:
        return (n.pve_node is None, not n.is_master_eligible, -n.ram_mb, n.name)

    for node in sorted(state.nodes, key=order):
        if node.pve_node is not None and node.pve_node not in known:
            result.issues.append(PlacementIssue(
                "error", f"pinned to host '{node.pve_node}', which is not a known host", node.name))
            continue
        candidates = [h for h in hosts if node.pve_node in (None, h.name)]

        fits: list[tuple[HostView, float]] = []
        rejected: dict[str, list[str]] = {}
        for h in candidates:
            reasons, score = ledger.evaluate(h, node)
            if reasons:
                rejected[h.name] = reasons
            else:
                fits.append((h, score))

        if not fits:
            detail = "; ".join(f"{name}: {', '.join(r)}" for name, r in sorted(rejected.items()))
            result.issues.append(PlacementIssue(
                "error", f"no host can take this node ({detail})", node.name))
            continue

        def preference(item: tuple[HostView, float], node: NodeSpec = node) -> tuple:
            h, score = item
            spread = (masters[h.name],) if node.is_master_eligible else ()
            return (*spread, cluster[h.name], -score, h.name)

        host, score = min(fits, key=preference)
        ledger.claim(host, node)
        cluster[host.name] += 1
        if node.is_master_eligible:
            masters[host.name] += 1
        result.assignments[node.name] = Placement(host.name, score)

    result.assignments = {n.name: result.assignments[n.name]
                          for n in state.nodes if n.name in result.assignments}
    _quorum_findings(result, masters)
    return result


def _quorum_findings(result: PlacementResult, masters: Counter) -> None:
    total = sum(masters.values())
    if total < 2:
        return
    survivable = (total - 1) // 2  # master-eligible nodes the cluster can lose and keep a quorum
    for host, held in sorted(masters.items()):
        if held > survivable:
            result.quorum_safe = False
            result.issues.append(PlacementIssue(
                "warning",
                f"host '{host}' would hold {held} of {total} master-eligible nodes; losing it "
                f"would break the master quorum"))
    shared = sorted(h for h, c in masters.items() if c > 1)
    if shared and result.quorum_safe:
        result.issues.append(PlacementIssue(
            "warning", "master-eligible nodes share a host (" + ", ".join(shared) + "); "
            "spread them across more hosts if you can"))
