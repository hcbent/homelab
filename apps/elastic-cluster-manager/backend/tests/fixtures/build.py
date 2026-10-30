"""Generate SYNTHETIC API fixtures (response shapes follow the real Proxmox and Elasticsearch
APIs; every name, address, and number here is invented, using RFC 5737 TEST-NET addresses).
Replace with recorded real responses later by dropping files in the same layout.

Run: python -m tests.fixtures.build
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent / "data"
GB = 1024**3


def write(rel: str, data) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def vm_config(name, vmid, ip, *, data_gb=256, static_ip=True, tag=10):
    cfg = {
        "name": name, "cores": 4, "sockets": 1, "memory": 16384, "ostype": "l26",
        "scsi0": f"tank:vm-{vmid}-disk-0,size=32G",
        "scsi1": f"tank:vm-{vmid}-disk-1,size={data_gb}G",
        "ide2": f"tank:vm-{vmid}-cloudinit,media=cdrom",
        "net0": f"virtio=BC:24:11:00:{vmid // 256:02X}:{vmid % 256:02X},bridge=vmbr0,tag={tag}",
        "agent": "1", "tags": "elasticsearch",
        "cipassword": "**********", "sshkeys": "ssh-ed25519%20AAAAFAKE%20fixture",
    }
    if static_ip:
        cfg["ipconfig0"] = f"ip={ip}/24,gw=192.0.2.1"
    else:
        cfg["ipconfig0"] = "ip=dhcp"
    return cfg


def build_proxmox():
    nodes = ["pve1", "pve2", "pve3"]
    write("proxmox/nodes.json", {"data": [
        {"node": n, "status": "online", "cpu": 0.12 + i * 0.05, "maxcpu": 32,
         "mem": (40 + i * 10) * GB, "maxmem": 128 * GB, "uptime": 1000000}
        for i, n in enumerate(nodes)]})
    vms = {n: [] for n in nodes}
    configs, agent = {}, {}

    def add(node, vmid, name, ip, *, running=True, template=False, with_agent=True,
            static_ip=True, data_gb=256):
        vms[node].append({"vmid": vmid, "name": name, "status": "running" if running else "stopped",
                          "template": 1 if template else 0, "cpus": 4, "cpu": 0.07,
                          "mem": 9 * GB, "maxmem": 16 * GB, "maxdisk": 32 * GB, "uptime": 5000})
        if not template:
            configs[(node, vmid)] = vm_config(name, vmid, ip, static_ip=static_ip, data_gb=data_gb)
        else:
            configs[(node, vmid)] = {"name": name, "template": 1, "cores": 2, "memory": 2048,
                                     "scsi0": "tank:base-8000-disk-0,size=10G"}
        if running and with_agent and ip:
            agent[(node, vmid)] = {"result": [
                {"name": "lo", "hardware-address": "00:00:00:00:00:00",
                 "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4", "prefix": 8}]},
                {"name": "eth0", "hardware-address": f"bc:24:11:00:{vmid // 256:02x}:{vmid % 256:02x}",
                 "ip-addresses": [{"ip-address": ip, "ip-address-type": "ipv4", "prefix": 24}]}]}

    # Cluster A: 9 nodes, VMs 301-309 round-robin on pve1-3 (agent-reported IPs).
    for i in range(1, 10):
        add(nodes[(i - 1) % 3], 300 + i, f"fxa-0{i}", f"192.0.2.{10 + i}",
            static_ip=not i % 2)
    # fxa-07's agent reports a different address than ES does: name match only => probable.
    agent[("pve1", 307)]["result"][1]["ip-addresses"][0]["ip-address"] = "192.0.2.77"
    configs[("pve1", 307)]["ipconfig0"] = "ip=dhcp"
    # Cluster B: single node, agent not running, only a static cloud-init IP => verified via cloud-init.
    add("pve2", 310, "fxb-01", "192.0.2.50", with_agent=False)
    # Two VMs claim the same address => ambiguous, must stay unlinked (cluster C node).
    add("pve3", 501, "dup-a", "192.0.2.99")
    add("pve3", 502, "dup-b", "192.0.2.99")
    # Unrelated VMs and the template.
    add("pve1", 200, "web", "192.0.2.200")
    add("pve1", 8000, "ubuntu-template", None, running=False, template=True)

    for n in nodes:
        write(f"proxmox/nodes/{n}/qemu.json", {"data": vms[n]})
        write(f"proxmox/nodes/{n}/storage.json", {"data": [
            {"storage": "tank", "type": "zfspool", "content": "images,rootdir", "shared": 1,
             "active": 1, "enabled": 1, "total": 4000 * GB, "used": 1500 * GB, "avail": 2500 * GB},
            {"storage": "local", "type": "dir", "content": "iso,vztmpl", "shared": 0, "active": 1,
             "enabled": 1, "total": 100 * GB, "used": 20 * GB, "avail": 80 * GB}]})
        write(f"proxmox/nodes/{n}/network.json", {"data": [
            {"iface": "vmbr0", "type": "bridge", "active": 1, "bridge_vlan_aware": 1,
             "cidr": "192.0.2.5/24"},
            {"iface": "eno1", "type": "eth", "active": 1}]})
    for (n, vmid), cfg in configs.items():
        write(f"proxmox/nodes/{n}/qemu/{vmid}/config.json", {"data": cfg})
    for (n, vmid), a in agent.items():
        write(f"proxmox/nodes/{n}/qemu/{vmid}/agent/network-get-interfaces.json", {"data": a})
    # VMs without a running agent have no agent file => the transport answers 500 like Proxmox.


def es_cluster(host, cluster_name, uuid, version, nodes, *, status, unassigned=0, settings=None):
    """nodes: list of (name, ip, roles, data_bytes_total, heap_pct)"""
    nmap, smap, shards = {}, {}, []
    for i, (name, ip, roles, disk, heap) in enumerate(nodes):
        nid = f"{uuid[:8]}n{i:02d}"
        nmap[nid] = {"name": name, "host": ip, "ip": ip, "transport_address": f"{ip}:9300",
                     "version": version, "roles": roles,
                     "attributes": {"ml.machine_memory": "17179869184"}}
        smap[nid] = {"name": name,
                     "jvm": {"mem": {"heap_used_percent": heap, "heap_max_in_bytes": 8 * GB,
                                     "heap_used_in_bytes": heap * 8 * GB // 100}},
                     "fs": {"total": {"total_in_bytes": disk, "available_in_bytes": disk * 6 // 10}}}
        if any(r.startswith("data") for r in roles):
            for s in range(3):
                shards.append({"index": f"logs-{s}", "shard": str(s), "prirep": "p", "state": "STARTED",
                               "node": name, "store": "1gb"})
    for s in range(unassigned):
        shards.append({"index": "broken", "shard": str(s), "prirep": "r", "state": "UNASSIGNED",
                       "node": None, "store": None})
    base = f"elasticsearch/{host}"
    write(f"{base}/root.json", {"name": nodes[0][0], "cluster_name": cluster_name,
                                "cluster_uuid": uuid, "version": {"number": version},
                                "tagline": "You Know, for Search"})
    write(f"{base}/_cluster/health.json", {
        "cluster_name": cluster_name, "status": status, "number_of_nodes": len(nodes),
        "number_of_data_nodes": sum(1 for n in nodes if any(r.startswith("data") for r in n[2])),
        "active_primary_shards": sum(1 for s in shards if s["state"] == "STARTED"),
        "unassigned_shards": unassigned})
    write(f"{base}/_nodes.json", {"cluster_name": cluster_name, "nodes": nmap})
    write(f"{base}/_nodes/stats/jvm,fs.json", {"cluster_name": cluster_name, "nodes": smap})
    write(f"{base}/_cat/shards.json", shards)
    write(f"{base}/_cluster/settings.json", settings or {"persistent": {}, "transient": {}})


def build_es():
    data_roles = ["data", "data_content", "data_hot", "data_warm", "data_cold", "ingest",
                  "remote_cluster_client", "transform", "ml"]
    a = [(f"fxa-0{i}", f"192.0.2.{10 + i}", ["master"] if i <= 3 else data_roles,
          500 * GB, 40 + i * 3) for i in range(1, 10)]
    es_cluster("fxa.test", "fixture-a", "aaaaaaaaaaaaaaaaaaaaaa", "9.5.6", a, status="green",
               settings={"persistent": {"cluster.routing.allocation.enable": "all"}, "transient": {}})
    es_cluster("fxb.test", "fixture-b", "bbbbbbbbbbbbbbbbbbbbbb", "9.5.6",
               [("fxb-01", "192.0.2.50", ["master"] + data_roles, 256 * GB, 55)], status="yellow",
               unassigned=2)
    es_cluster("fxc.test", "fixture-c", "cccccccccccccccccccccc", "8.19.24",
               [("fxc-01", "192.0.2.99", ["master"] + data_roles, 256 * GB, 91)], status="red",
               unassigned=5)


if __name__ == "__main__":
    shutil.rmtree(ROOT, ignore_errors=True)
    build_proxmox()
    build_es()
    print("fixtures written to", ROOT)
