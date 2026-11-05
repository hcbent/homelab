import pytest
from pydantic import ValidationError

from app.desired import NodeSpec, RolesMode, TopologyPreset, build_desired_state
from app.desired.network import AllocationError, NetworkProfile, allocate_addresses, cloud_init_ipv4


def profile(**kw) -> NetworkProfile:
    base = {"name": "lab", "bridge": "vmbr0", "vlan": 10, "cidr": "192.0.2.0/24", "gateway": "192.0.2.1",
                "dns": ["192.0.2.1"], "search_domain": "lab.example.org",
                "range_start": "192.0.2.200", "range_end": "192.0.2.209"}
    return NetworkProfile(**{**base, **kw})


def nodes(n=3, **kw):
    return [NodeSpec(name=f"lab-b-0{i}", data_disk_gb=50, **kw) for i in range(1, n + 1)]


# ---- profile validation --------------------------------------------------------------------------

def test_valid_profile():
    p = profile()
    assert p.pool_size == 10 and p.network.prefixlen == 24


@pytest.mark.parametrize("change,match", [
    ({"gateway": "198.51.100.1"}, "gateway .* inside"),
    ({"gateway": "192.0.2.0"}, "gateway .* host address"),
    ({"gateway": "192.0.2.255"}, "gateway .* host address"),
    ({"range_start": "198.51.100.5"}, "range_start .* inside"),
    ({"range_end": "192.0.2.255"}, "range_end .* host address"),
    ({"range_start": "192.0.2.209", "range_end": "192.0.2.200"}, "not be after"),
    ({"range_start": "192.0.2.1", "range_end": "192.0.2.50"}, "must not include the gateway"),
    ({"dns": ["192.0.2.205"]}, "must not include the DNS server"),
    ({"cidr": "192.0.2.0/30"}, "too small"),
    ({"cidr": "192.0.2.5/24"}, "IPv4 network"),
    ({"cidr": "not-a-network"}, "IPv4 network"),
    ({"gateway": "fe80::1"}, "IPv4"),
    ({"vlan": 5000}, "less than or equal to 4094"),
    ({"name": "Lab"}, "lowercase"),
    ({"search_domain": "bad domain"}, "DNS domain"),
])
def test_invalid_profiles_are_rejected(change, match):
    with pytest.raises(ValidationError, match=match):
        profile(**change)


@pytest.mark.parametrize("change,match", [
    ({"dhcp_start": "192.0.2.205", "dhcp_end": "192.0.2.254"}, "overlaps the DHCP range"),
    ({"dhcp_start": "192.0.2.150", "dhcp_end": "192.0.2.200"}, "overlaps the DHCP range"),     # touches the start
    ({"dhcp_start": "192.0.2.209", "dhcp_end": "192.0.2.220"}, "overlaps the DHCP range"),     # touches the end
    ({"dhcp_start": "192.0.2.100", "dhcp_end": "192.0.2.254"}, "overlaps the DHCP range"),     # contains it
    ({"dhcp_start": "192.0.2.220"}, "both dhcp_start and dhcp_end"),
    ({"dhcp_end": "192.0.2.220"}, "both dhcp_start and dhcp_end"),
    ({"dhcp_start": "192.0.2.254", "dhcp_end": "192.0.2.220"}, "dhcp_start must not be after"),
    ({"dhcp_start": "198.51.100.5", "dhcp_end": "198.51.100.9"}, "must be inside"),
])
def test_the_allocation_range_must_stay_clear_of_dhcp(change, match):
    with pytest.raises(ValidationError, match=match):
        profile(**change)


def test_a_range_that_sits_right_next_to_dhcp_is_accepted():
    p = profile(range_start="192.0.2.110", range_end="192.0.2.149", dhcp_start="192.0.2.150",
                dhcp_end="192.0.2.254")
    assert p.pool_size == 40                                  # .149 is the last static address


def test_a_fixed_address_inside_the_dhcp_range_is_refused():
    p = profile(range_start="192.0.2.110", range_end="192.0.2.149", dhcp_start="192.0.2.150",
                dhcp_end="192.0.2.254")
    ns = nodes(3)
    ns[0].ip = "192.0.2.211"
    with pytest.raises(AllocationError, match="inside the DHCP range 192.0.2.150-192.0.2.254"):
        allocate_addresses(p, ns)
    ns[0].ip = "192.0.2.149"                                  # just below DHCP is fine
    assert allocate_addresses(p, ns)["lab-b-01"] == "192.0.2.149"


def test_dhcp_is_optional():
    assert profile().dhcp_start is None


def test_an_external_dns_server_is_fine():
    assert profile(dns=["198.51.100.53", "203.0.113.53"]).dns[0] == "198.51.100.53"


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        profile(colour="blue")


# ---- allocation ----------------------------------------------------------------------------------

def test_lowest_free_addresses_are_handed_out_in_node_order():
    got = allocate_addresses(profile(), nodes(3))
    assert got == {"lab-b-01": "192.0.2.200", "lab-b-02": "192.0.2.201", "lab-b-03": "192.0.2.202"}
    assert list(got) == ["lab-b-01", "lab-b-02", "lab-b-03"]


def test_addresses_already_in_use_are_skipped():
    got = allocate_addresses(profile(), nodes(3), in_use=["192.0.2.200", "192.0.2.202", "not-an-ip"])
    assert list(got.values()) == ["192.0.2.201", "192.0.2.203", "192.0.2.204"]


def test_fixed_addresses_are_kept_and_not_given_to_others():
    ns = nodes(3)
    ns[1].ip = "192.0.2.200"
    got = allocate_addresses(profile(), ns)
    assert got["lab-b-02"] == "192.0.2.200"
    assert got["lab-b-01"] == "192.0.2.201" and got["lab-b-03"] == "192.0.2.202"


def test_a_fixed_address_may_lie_outside_the_pool_but_inside_the_subnet():
    ns = nodes(3)
    ns[0].ip = "192.0.2.50"
    assert allocate_addresses(profile(), ns)["lab-b-01"] == "192.0.2.50"


@pytest.mark.parametrize("ip,match", [
    ("198.51.100.7", "outside the profile network"),
    ("192.0.2.1", "network, broadcast or gateway"),
    ("192.0.2.0", "network, broadcast or gateway"),
    ("192.0.2.255", "network, broadcast or gateway"),
    ("192.0.2.205", "already in use"),
])
def test_bad_fixed_addresses_are_refused_with_a_reason(ip, match):
    ns = nodes(3)
    ns[0].ip = ip
    with pytest.raises(AllocationError, match=match):
        allocate_addresses(profile(), ns, in_use=["192.0.2.205"])


def test_an_exhausted_pool_says_how_much_is_missing():
    with pytest.raises(AllocationError) as e:
        allocate_addresses(profile(range_end="192.0.2.201"), nodes(3))
    msg = str(e.value)
    assert "192.0.2.200-192.0.2.201" in msg and "lab-b-03" in msg
    assert "3 needed, 2 in the pool" in msg and "widen the range" in msg


def test_the_pool_never_hands_out_the_gateway_even_when_a_range_would_reach_it():
    # a profile cannot include the gateway in its range, but in_use may include anything; check the invariant
    got = allocate_addresses(profile(range_start="192.0.2.2", range_end="192.0.2.4"), nodes(3))
    assert "192.0.2.1" not in got.values()


def test_allocation_is_deterministic():
    assert allocate_addresses(profile(), nodes(3)) == allocate_addresses(profile(), nodes(3))


def test_works_with_preset_built_clusters():
    state = build_desired_state(TopologyPreset.dedicated_masters, "lab-b", "9.4.3", data_nodes=2,
                                coordinating_nodes=1)
    got = allocate_addresses(profile(), state.nodes)
    assert len(got) == 6 and len(set(got.values())) == 6


def test_coordinating_nodes_get_addresses_too():
    ns = nodes(3) + [NodeSpec(name="lab-b-04", roles_mode=RolesMode.coordinating)]
    assert len(allocate_addresses(profile(), ns)) == 4


# ---- terraform / cloud-init values ---------------------------------------------------------------

def test_cloud_init_values_include_the_prefix_gateway_and_vlan():
    got = cloud_init_ipv4(profile(), "192.0.2.201")
    assert got == {"address": "192.0.2.201/24", "gateway": "192.0.2.1", "dns": ["192.0.2.1"],
                   "search_domain": "lab.example.org", "bridge": "vmbr0", "vlan": 10}
    assert cloud_init_ipv4(profile(cidr="192.0.2.0/25", range_start="192.0.2.40", range_end="192.0.2.50"),
                           "192.0.2.5")["address"] == "192.0.2.5/25"
