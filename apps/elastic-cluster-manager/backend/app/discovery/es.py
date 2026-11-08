"""Read-only Elasticsearch client and normalisation of what a cluster reports."""
from collections import Counter
from dataclasses import dataclass, field

import httpx

from app.crypto import register_secret
from app.discovery.http import build_client, get_json


class ESClient:
    def __init__(self, base_url: str, api_key: str, *, verify: bool = True,
                 ca_pem: str | None = None, transport: httpx.BaseTransport | None = None):
        register_secret(api_key)
        self._http = build_client(base_url.rstrip("/"), {"Authorization": f"ApiKey {api_key}"},
                                  verify=verify, ca_pem=ca_pem, transport=transport)

    def _get(self, path: str, what: str):
        return get_json(self._http, path, what)

    def root(self):
        return self._get("/", "cluster info")

    def health(self):
        return self._get("/_cluster/health", "cluster health")

    def nodes(self):
        return self._get("/_nodes", "node info")

    def nodes_stats(self):
        return self._get("/_nodes/stats/jvm,fs", "node stats")

    def shards(self):
        return self._get("/_cat/shards?format=json&h=index,shard,prirep,state,node,store",
                         "shard list")

    def settings(self):
        return self._get("/_cluster/settings?flat_settings=true", "cluster settings")

    def shards_sized(self):
        """Every shard copy with its size in bytes, for working out where data would go if a node left."""
        return self._get("/_cat/shards?format=json&bytes=b&h=index,shard,prirep,state,node,store",
                         "shard list with sizes")

    def master(self):
        return self._get("/_cat/master?format=json&h=node", "elected master")


@dataclass
class NodeInfo:
    es_node_id: str
    name: str
    ip: str | None
    host: str | None
    version: str | None
    roles: list[str]
    attributes: dict
    heap_used_pct: int | None = None
    heap_max_bytes: int | None = None
    disk_total_bytes: int | None = None
    disk_avail_bytes: int | None = None
    shard_count: int = 0
    uptime_ms: int | None = None        # how long this node's JVM has been running, for telling whether it restarted since a change


@dataclass
class ClusterSnapshot:
    cluster_uuid: str
    cluster_name: str
    version: str
    status: str
    nodes: list[NodeInfo] = field(default_factory=list)
    detail: dict = field(default_factory=dict)  # health, shard summary, settings


def collect(client: ESClient) -> ClusterSnapshot:
    root = client.root()
    health = client.health()
    info = client.nodes().get("nodes", {})
    stats = client.nodes_stats().get("nodes", {})
    shards = client.shards()
    settings = client.settings()

    per_node = Counter(s["node"] for s in shards if s.get("node"))
    nodes = []
    for nid, n in info.items():
        st = stats.get(nid, {})
        heap = st.get("jvm", {}).get("mem", {})
        fs = st.get("fs", {}).get("total", {})
        nodes.append(NodeInfo(
            es_node_id=nid, name=n["name"], ip=n.get("ip"), host=n.get("host"),
            version=n.get("version"), roles=sorted(n.get("roles", [])),
            attributes=n.get("attributes", {}),
            heap_used_pct=heap.get("heap_used_percent"), heap_max_bytes=heap.get("heap_max_in_bytes"),
            disk_total_bytes=fs.get("total_in_bytes"), disk_avail_bytes=fs.get("available_in_bytes"),
            shard_count=per_node.get(n["name"], 0), uptime_ms=(st.get("jvm") or {}).get("uptime_in_millis")))

    return ClusterSnapshot(
        cluster_uuid=root["cluster_uuid"], cluster_name=root["cluster_name"],
        version=root["version"]["number"], status=health["status"], nodes=sorted(nodes, key=lambda n: n.name),
        detail={"health": health,
                "shards": {"by_state": dict(Counter(s["state"] for s in shards)),
                           "by_node": dict(per_node),
                           "unassigned": [f'{s["index"]}[{s["shard"]}]{s["prirep"]}'
                                          for s in shards if s["state"] == "UNASSIGNED"][:50]},
                "settings": {"persistent": settings.get("persistent", {}),
                             "transient": settings.get("transient", {})}})


def is_data_node(roles: list[str]) -> bool:
    return any(r == "data" or r.startswith("data_") for r in roles)
