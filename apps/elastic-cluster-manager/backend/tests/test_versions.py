import httpx
import pytest

from app.desired.versions import (
    ArtifactsApiCatalog,
    CatalogError,
    StaticCatalog,
    Version,
    available_versions,
    check_target_version,
    check_upgrade,
    latest_minor,
    latest_patch,
    parse_artifacts_versions,
)

# Same shape as the live artifacts API: plain releases mixed with -SNAPSHOT builds, plus aliases.
API_PAYLOAD = {
    "versions": ["8.19.22", "8.19.23", "8.19.24-SNAPSHOT", "8.19.24", "9.4.8", "9.4.9-SNAPSHOT",
                 "9.5.5", "9.5.6-SNAPSHOT", "9.5.6", "9.6.0-SNAPSHOT", "9.6.0", "9.7.0-SNAPSHOT"],
    "aliases": ["8.19-SNAPSHOT", "8.19", "9.4", "9.5", "9.6"],
    "manifests": {"last-update-time": "x"},
}
CATALOG = StaticCatalog(["8.19.22", "8.19.23", "8.19.24", "9.4.8", "9.5.5", "9.5.6", "9.6.0"])


# ---- parsing and the API client --------------------------------------------------------------

def test_version_parsing_and_ordering():
    assert Version.parse("9.4.3") < Version.parse("9.10.0")      # numeric, not string, comparison
    assert str(Version.parse("8.19.2")) == "8.19.2"
    for bad in ("9.4", "9.4.3-SNAPSHOT", "latest", ""):
        with pytest.raises(ValueError):
            Version.parse(bad)


def test_parser_keeps_plain_releases_only():
    got = [str(v) for v in parse_artifacts_versions(API_PAYLOAD)]
    assert got == ["8.19.22", "8.19.23", "8.19.24", "9.4.8", "9.5.5", "9.5.6", "9.6.0"]


def api_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_catalog_fetches_once_and_caches_within_the_ttl():
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=API_PAYLOAD)

    cat = ArtifactsApiCatalog(client=api_client(handler), ttl_seconds=100, clock=lambda: now[0])
    assert available_versions(cat)[0] == "9.6.0"                 # newest first
    now[0] = 50
    cat.releases()
    assert len(calls) == 1 and calls[0].endswith("/v1/versions")
    now[0] = 150                                                  # past the ttl: refetch
    cat.releases()
    assert len(calls) == 2


def test_a_failed_refresh_serves_the_stale_copy():
    state = {"ok": True}
    now = [0.0]

    def handler(request):
        if state["ok"]:
            return httpx.Response(200, json=API_PAYLOAD)
        return httpx.Response(504)

    cat = ArtifactsApiCatalog(client=api_client(handler), ttl_seconds=10, clock=lambda: now[0])
    first = cat.releases()
    state["ok"] = False
    now[0] = 100
    assert cat.releases() == first


def test_no_cache_and_a_failing_api_raises_a_clear_error():
    cat = ArtifactsApiCatalog(client=api_client(lambda r: httpx.Response(503)))
    with pytest.raises(CatalogError, match="could not fetch"):
        cat.releases()
    only_snapshots = ArtifactsApiCatalog(
        client=api_client(lambda r: httpx.Response(200, json={"versions": ["9.9.9-SNAPSHOT"]})))
    with pytest.raises(CatalogError, match="no plain releases"):
        only_snapshots.releases()


# ---- choosing a version for a new cluster ----------------------------------------------------

def test_target_must_be_a_published_release():
    assert check_target_version("9.5.6", CATALOG) == []
    assert "not a published" in check_target_version("9.4.3", CATALOG)[0]
    assert "not a plain release" in check_target_version("9.5.6-SNAPSHOT", CATALOG)[0]
    assert "not a plain release" in check_target_version("9.5", CATALOG)[0]


def test_latest_helpers():
    assert latest_minor(CATALOG, 8) == 19 and latest_minor(CATALOG, 9) == 6
    assert latest_minor(CATALOG, 7) is None
    assert str(latest_patch(CATALOG, 9, 5)) == "9.5.6"


# ---- upgrade paths ---------------------------------------------------------------------------

def test_downgrades_and_no_ops_are_refused():
    down = check_upgrade("9.6.0", "9.5.6", CATALOG)
    assert not down.ok and "downgrades are not supported" in down.reasons[0]
    same = check_upgrade("9.5.6", "9.5.6", CATALOG)
    assert not same.ok and "already on" in same.reasons[0]


def test_upgrade_target_must_be_published():
    got = check_upgrade("9.4.3", "9.5.99", CATALOG)
    assert not got.ok and "not a published" in got.reasons[0]


def test_within_a_major_any_newer_release_is_allowed():
    # the live cluster runs 9.4.3, which has dropped off the published list: that must not matter
    got = check_upgrade("9.4.3", "9.5.6", CATALOG)
    assert got.ok and got.reasons == []
    assert check_upgrade("8.19.22", "8.19.24", CATALOG).ok


def test_major_upgrade_needs_the_latest_minor_of_the_old_major():
    ok = check_upgrade("8.19.24", "9.4.8", CATALOG)
    assert ok.ok
    assert any("deprecation API" in n for n in ok.notes)
    behind = check_upgrade("8.18.0", "9.4.8", CATALOG)
    assert not behind.ok
    assert "requires the latest 8.x minor (8.19)" in behind.reasons[0]
    assert "Upgrade to 8.19 first" in behind.reasons[0]


def test_major_upgrade_notes_a_patch_behind_the_latest():
    got = check_upgrade("8.19.22", "9.5.6", CATALOG)
    assert got.ok and any("8.19.24 is the latest" in n for n in got.notes)


def test_skipping_a_major_is_refused():
    got = check_upgrade("7.17.5", "9.4.8", StaticCatalog(["7.17.9", "9.4.8"]))
    assert not got.ok and "cannot skip a major version" in got.reasons[0]


def test_unknown_old_major_cannot_be_judged():
    got = check_upgrade("8.19.24", "9.4.8", StaticCatalog(["9.4.8"]))
    assert not got.ok and "no 8.x releases are published" in got.reasons[0]


def test_malformed_versions_are_reported_not_raised():
    got = check_upgrade("latest", "9.5.6", CATALOG)
    assert not got.ok and "not a plain release version" in got.reasons[0]
