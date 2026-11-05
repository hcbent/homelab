from app.discovery import es, proxmox
from app.discovery.correlate import VmView, link_node
from tests.fixtures.transport import ES_KEY, PVE_TOKEN, FixtureTransport

KEY = ES_KEY.split(" ", 1)[1]


def pve(t):
    return proxmox.ProxmoxClient("https://pve.test:8006", "ro@pve!ecm", "fixture-pve-secret-value",
                                 transport=t)


def test_proxmox_collect_from_fixtures():
    t = FixtureTransport()
    snap = proxmox.collect(pve(t))
    assert t.methods == {"GET"}
    assert {r.headers["authorization"] for r in t.requests} == {PVE_TOKEN}
    assert [n["node"] for n in snap.nodes] == ["pve1", "pve2", "pve3"]
    by_id = {v.vmid: v for v in snap.vms}
    assert by_id[8000].is_template and by_id[8000].name == "ubuntu-template"
    vm = by_id[302]
    assert vm.cpu_cores == 4 and vm.memory_mb == 16384
    assert [d["size_gb"] for d in vm.disks] == [32, 256]          # cloud-init drive excluded
    assert vm.nets[0]["bridge"] == "vmbr0" and vm.nets[0]["vlan"] == 10
    assert {"ip": "192.0.2.12", "source": "guest-agent"} in vm.ips
    assert "127.0.0.1" not in {i["ip"] for i in vm.ips}
    # secrets never leave the client
    assert not any("password" in k or "sshkeys" in k for k in vm.config)
    # agent not running -> only the static cloud-init address is known
    assert by_id[310].ips == [{"ip": "192.0.2.50", "source": "cloud-init"}]
    assert {s["name"] if "name" in s else s["storage"] for s in snap.storages} == {"tank", "local"}


def test_es_collect_from_fixtures():
    t = FixtureTransport()
    snap = es.collect(es.ESClient("https://fxa.test:9200", KEY, transport=t))
    assert t.methods == {"GET"}
    assert (snap.cluster_name, snap.version, snap.status) == ("fixture-a", "9.5.6", "green")
    assert len(snap.nodes) == 9
    assert sum(es.is_data_node(n.roles) for n in snap.nodes) == 6
    masters = [n for n in snap.nodes if n.roles == ["master"]]
    assert len(masters) == 3 and all(n.shard_count == 0 for n in masters)
    assert snap.nodes[-1].heap_used_pct and snap.nodes[-1].disk_total_bytes
    assert snap.detail["shards"]["by_state"] == {"STARTED": 18}
    assert snap.cluster_uuid == "aaaaaaaaaaaaaaaaaaaaaa"


def test_red_cluster_reports_unassigned():
    snap = es.collect(es.ESClient("https://fxc.test:9200", KEY, transport=FixtureTransport()))
    assert snap.status == "red" and snap.detail["shards"]["by_state"]["UNASSIGNED"] == 5


def test_bad_credentials_raise_discovery_error():
    import pytest

    from app.discovery.http import DiscoveryError
    with pytest.raises(DiscoveryError) as e:
        es.collect(es.ESClient("https://fxa.test:9200", "wrongwrongwrong", transport=FixtureTransport()))
    assert e.value.status == 401


def vm(key, name, *ips, template=False):
    return VmView(key, name, [{"ip": i, "source": "guest-agent"} for i in ips], template)


def test_correlation_rules():
    vms = [vm("a", "n1", "10.0.0.1"), vm("b", "n2", "10.0.0.2"), vm("c", "x", "10.0.0.9"),
           vm("d", "y", "10.0.0.9"), vm("t", "tpl", "10.0.0.5", template=True)]
    v = link_node("10.0.0.1", None, "whatever", vms)
    assert (v.vm_key, v.confidence, v.evidence["method"]) == ("a", "verified", "ip")
    amb = link_node("10.0.0.9", None, "n1", vms)                       # two VMs claim it
    assert (amb.vm_key, amb.confidence, amb.evidence["reason"]) == (None, "unlinked", "ambiguous")
    prob = link_node("10.0.0.77", None, "n2", vms)                     # name only
    assert (prob.vm_key, prob.confidence) == ("b", "probable")
    assert link_node("10.0.0.5", None, "nope", vms).confidence == "unlinked"   # templates ignored
    assert link_node(None, None, "nobody", vms).confidence == "unlinked"


def test_container_bridge_addresses_are_not_vm_evidence():
    assert all(proxmox.is_virtual_interface(n) for n in
               ("lo", "docker0", "br-3f2a9c", "veth12ab", "virbr0", "cni0", "flannel.1", "cali123", "podman1"))
    assert not any(proxmox.is_virtual_interface(n) for n in ("eth0", "ens18", "enp6s18", "bond0", "vmbr0", None))

    class Stub:
        def nodes(self): return [{"node": "pve1", "status": "online", "maxcpu": 4, "maxmem": 8 * 1024**3}]
        def networks(self, node): return []
        def storages(self, node): return []
        def vms(self, node): return [{"vmid": 116, "name": "docker", "status": "running"}]
        def vm_config(self, node, vmid): return {"name": "docker", "cores": 2, "memory": 2048}
        def vm_agent_interfaces(self, node, vmid):
            def addr(ip): return {"ip-addresses": [{"ip-address": ip, "ip-address-type": "ipv4", "prefix": 24}]}
            return [{"name": "ens18", **addr("192.0.2.10")}, {"name": "docker0", **addr("172.17.0.1")},
                    {"name": "br-1a2b3c", **addr("172.18.0.1")}]

    snap = proxmox.collect(Stub())
    assert snap.vms[0].ips == [{"ip": "192.0.2.10", "source": "guest-agent"}]
