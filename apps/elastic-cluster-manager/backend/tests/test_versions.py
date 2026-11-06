import gzip

import httpx
import pytest

from app.desired.versions import (
    ArtifactsApiCatalog,
    CatalogError,
    InstallableCatalog,
    StaticCatalog,
    Version,
    available_versions,
    check_target_version,
    check_upgrade,
    latest_minor,
    latest_patch,
    parse_apt_index,
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


# ---- only releases the machines can install --------------------------------------------------------------

def _apt_index(*versions: str, other: str = "elasticsearch-oss") -> bytes:
    """A Packages.gz shaped like Elastic's: one block per package version, blank line between."""
    blocks = [f"Package: elasticsearch\nVersion: {v}\nArchitecture: amd64\nDescription: Search\n and more\n"
              for v in versions]
    blocks.append(f"Package: {other}\nVersion: 9.9.9\nArchitecture: amd64\n")
    return gzip.compress("\n".join(blocks).encode())


def _apt_client(indexes: dict[int, bytes | int], seen: list[str] | None = None) -> httpx.Client:
    """An index per major (bytes), or a status code for a failing one."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        major = int(str(request.url).split("/packages/")[1].split(".")[0])
        got = indexes.get(major, 404)
        return httpx.Response(got) if isinstance(got, int) else httpx.Response(200, content=got)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_apt_index_keeps_only_the_elasticsearch_package():
    got = parse_apt_index(gzip.decompress(_apt_index("9.5.5", "9.5.6")).decode())
    assert sorted(str(v) for v in got) == ["9.5.5", "9.5.6"]      # elasticsearch-oss 9.9.9 is not counted


def test_a_release_the_apt_repository_lacks_is_left_out_and_named_when_chosen():
    seen: list[str] = []
    cat = InstallableCatalog(CATALOG, client=_apt_client(
        {9: _apt_index("9.4.8", "9.5.5", "9.5.6"), 8: _apt_index("8.19.22", "8.19.23", "8.19.24")}, seen))
    assert available_versions(cat)[:3] == ["9.5.6", "9.5.5", "9.4.8"]       # 9.6.0 is published but not packaged
    problem = check_target_version("9.6.0", cat)
    assert len(problem) == 1 and "apt repository does not carry" in problem[0] and "not a published" not in problem[0]
    assert check_target_version("9.5.6", cat) == []
    assert "not a published" in check_target_version("9.9.9", cat)[0]        # unknown stays the old message
    assert len(seen) == 2                                                    # one index per major, then cached


def test_the_apt_indexes_are_cached_and_a_stale_copy_survives_a_failed_refresh():
    now = [0.0]
    answers = {9: _apt_index("9.5.6", "9.6.0"), 8: _apt_index("8.19.24")}
    seen: list[str] = []
    cat = InstallableCatalog(CATALOG, client=_apt_client(answers, seen), ttl_seconds=100, clock=lambda: now[0])
    assert "9.6.0" in available_versions(cat)
    available_versions(cat)
    assert len(seen) == 2
    now[0] = 500.0
    answers[9] = 503
    answers[8] = 503
    assert "9.6.0" in available_versions(cat) and "9.5.5" not in available_versions(cat)   # stale index still used
    assert len(seen) == 4                                                                   # and it did try again
    available_versions(cat)
    assert len(seen) == 4                                                                   # but not on every call
    now[0] = 600.0
    available_versions(cat)
    assert len(seen) == 6                                                                   # it looks again after a minute


def test_an_unreadable_apt_index_with_nothing_cached_lets_that_major_through():
    cat = InstallableCatalog(CATALOG, client=_apt_client({9: 503, 8: _apt_index("8.19.24")}))
    got = available_versions(cat)
    assert "9.6.0" in got and "9.4.8" in got                      # 9.x unfiltered, as before the filter existed
    assert "8.19.22" not in got and "8.19.24" in got              # 8.x was readable, so it is filtered


def test_an_index_that_is_not_gzip_or_lists_nothing_counts_as_unreadable():
    cat = InstallableCatalog(CATALOG, client=_apt_client({9: b"<html>not gzip</html>", 8: gzip.compress(b"")}))
    assert available_versions(cat) == available_versions(CATALOG)


def test_majors_before_8_are_never_filtered_and_not_fetched():
    seen: list[str] = []
    cat = InstallableCatalog(StaticCatalog(["7.17.0", "8.19.24"]), client=_apt_client({8: _apt_index("8.19.24")}, seen))
    assert available_versions(cat) == ["8.19.24", "7.17.0"] and len(seen) == 1
