"""Reading what a token may do: rights outside the pool, and what an operation needs before it is planned."""
import httpx
import pytest

from app.discovery import proxmox
from app.discovery.http import DiscoveryError

ALLOC = {"VM.Allocate": 1}


# ---- rights outside the pool ---------------------------------------------------------------------------

def test_a_token_limited_to_the_pool_has_no_rights_outside_it():
    perms = {"/pool/ecm": {"VM.Allocate": 1, "VM.Clone": 1}, "/vms/500": ALLOC, "/vms/8000": {"VM.Clone": 1},
             "/storage/tank": {"Datastore.AllocateSpace": 1}}
    assert proxmox.vm_rights_outside_the_pool(perms, "ecm", members=lambda: {500, 501, 502}) == []


@pytest.mark.parametrize("path", ["/", "/vms", "/pool", "/pool/other", "/storage/tank", "/nodes"])
def test_a_grant_that_reaches_beyond_the_pool_is_flagged(path):
    assert proxmox.vm_rights_outside_the_pool({"/pool/ecm": ALLOC, path: ALLOC}, "ecm") == [path]


def test_the_pool_and_what_is_below_it_are_inside_but_a_pool_that_only_shares_a_prefix_is_not():
    assert proxmox.vm_rights_outside_the_pool({"/pool/ecm": ALLOC, "/pool/ecm/sub": ALLOC}, "ecm") == []
    assert proxmox.vm_rights_outside_the_pool({"/pool/ecm": ALLOC, "/pool/ecmx": ALLOC}, "ecm") == ["/pool/ecmx"]


def test_a_vm_path_is_judged_by_whether_the_vm_is_in_the_pool():
    perms = {"/vms/500": ALLOC, "/vms/999": ALLOC}
    assert proxmox.vm_rights_outside_the_pool(perms, "ecm", members=lambda: {500}) == ["/vms/999"]


def test_vm_paths_are_ignored_rather_than_guessed_when_membership_cannot_be_read():
    perms = {"/vms/500": ALLOC, "/pool": ALLOC}

    def unreadable():
        raise DiscoveryError("read pool ecm: HTTP 403", 403)

    assert proxmox.vm_rights_outside_the_pool(perms, "ecm", members=unreadable) == ["/pool"]
    assert proxmox.vm_rights_outside_the_pool(perms, "ecm", members=None) == ["/pool"]


def test_the_members_are_only_fetched_when_a_vm_path_needs_judging():
    calls = []
    proxmox.vm_rights_outside_the_pool({"/pool/ecm": ALLOC, "/": ALLOC}, "ecm", members=lambda: calls.append(1) or set())
    assert calls == []
    proxmox.vm_rights_outside_the_pool({"/vms/500": ALLOC}, "ecm", members=lambda: calls.append(1) or set())
    assert calls == [1]


def test_a_privilege_other_than_vm_allocate_is_not_counted():
    assert proxmox.vm_rights_outside_the_pool({"/": {"VM.Audit": 1, "VM.Clone": 1}}, "ecm") == []


# ---- what an operation needs before it is planned -------------------------------------------------------

def preflight(perms, **kw):
    return proxmox.preflight_problems(perms, **{"pool_id": "ecm", "datastore": "tank", "template_vmid": 8000,
                                                 "creating": True, **kw})


GOOD = {"/pool/ecm": ALLOC, "/storage/tank": {"Datastore.AllocateSpace": 1}, "/vms/8000": {"VM.Clone": 1}}


def test_a_create_needs_the_pool_the_datastore_and_the_template():
    assert preflight(GOOD) == []
    problems = preflight({})
    assert len(problems) == 3
    assert "VM.Allocate on /pool/ecm" in problems[0]
    assert "Datastore.AllocateSpace on /storage/tank" in problems[1]
    assert "VM.Clone on the template /vms/8000" in problems[2]


def test_a_removal_needs_only_the_pool():
    assert preflight({"/pool/ecm": ALLOC}, creating=False) == []
    assert len(preflight({}, creating=False)) == 1


def test_a_listed_path_replaces_its_parents_rights_it_does_not_add_to_them():
    perms = {"/": {"VM.Allocate": 1, "VM.Clone": 1, "Datastore.AllocateSpace": 1}, "/pool/ecm": {"VM.Audit": 1}}
    assert "VM.Allocate on /pool/ecm" in preflight(perms)[0]          # the pool's own entry says no


def test_the_names_given_are_the_ones_checked():
    perms = {"/pool/labpool": ALLOC, "/storage/fast": {"Datastore.AllocateSpace": 1}, "/vms/9000": {"VM.Clone": 1}}
    assert preflight(perms, pool_id="labpool", datastore="fast", template_vmid=9000) == []
    assert len(preflight(perms)) == 3                                   # the defaults are not these


def test_no_template_means_no_clone_check():
    assert preflight({"/pool/ecm": ALLOC, "/storage/tank": {"Datastore.AllocateSpace": 1}}, template_vmid=None) == []


# ---- reading a pool's members --------------------------------------------------------------------------

def client(handler):
    return proxmox.ProxmoxClient("https://pve.test:8006", "u@pve!t", "secret-value-123",
                                 transport=httpx.MockTransport(handler))


def test_the_members_of_a_pool_are_its_vm_ids():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"data": {"poolid": "ecm", "members": [
            {"vmid": 500, "type": "qemu"}, {"vmid": 501}, {"id": "storage/pve1/tank", "storage": "tank"}]}})

    assert client(handler).pool_member_ids("ecm") == {500, 501}             # storages have no vmid and are skipped
    assert seen == ["/api2/json/pools/ecm"]


@pytest.mark.parametrize("data", [{}, {"members": []}, [], None])
def test_a_pool_without_members_gives_an_empty_set(data):
    assert client(lambda r: httpx.Response(200, json={"data": data})).pool_member_ids("ecm") == set()


@pytest.mark.parametrize("pool_id", ["a/b", "../x", "", "-lead", "x" * 65, "two words", "a?b=c"])
def test_the_client_refuses_a_pool_id_that_is_not_one_before_making_any_request(pool_id):
    def handler(request):
        raise AssertionError("no request should be made")

    with pytest.raises(DiscoveryError, match="not a valid pool id"):
        client(handler).pool_member_ids(pool_id)
