"""Elasticsearch version catalog and upgrade-path rules.

The catalog comes from https://artifacts-api.elastic.co/v1/versions and is cached. Nothing is hardcoded
(DECISIONS: "ES versions come from artifacts-api.elastic.co/v1/versions with a cache").

The API lists only currently published releases and mixes in -SNAPSHOT builds and aliases such as "9.5". Only
plain X.Y.Z releases are kept. A cluster may be running a version that has since dropped off the list, so
upgrade checks never require the CURRENT version to be listed, only the target.

Upgrade rules (ARCHITECTURE section 7):
  * downgrades are refused, and so is "upgrading" to the same version
  * the target must be a published release
  * within a major, any newer release is allowed
  * to the next major, the cluster must already be on the latest published minor of its current major
  * skipping a major is refused
"""
import gzip
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

ARTIFACTS_URL = "https://artifacts-api.elastic.co/v1/versions"
APT_INDEX_URL = "https://artifacts.elastic.co/packages/{major}.x/apt/dists/stable/main/binary-amd64/Packages.gz"
FIRST_PACKAGED_MAJOR = 8   # older majors are not offered for new clusters, so their repositories are not read
_PLAIN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class CatalogError(Exception):
    """The version list could not be fetched and no cached copy exists."""


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> "Version":
        m = _PLAIN.match(text.strip())
        if not m:
            raise ValueError(f"not a plain release version: {text!r}")
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class VersionCatalog(Protocol):
    def releases(self) -> list[Version]: ...


def parse_artifacts_versions(payload: dict) -> list[Version]:
    """Keep plain releases only: drop -SNAPSHOT builds, alpha/beta tags and aliases like '9.5'."""
    out = {Version.parse(v) for v in payload.get("versions", []) if _PLAIN.match(v)}
    return sorted(out)


class StaticCatalog:
    """A fixed list, for tests and for offline use."""

    def __init__(self, versions: list[str]):
        self._versions = sorted({Version.parse(v) for v in versions})

    def releases(self) -> list[Version]:
        return list(self._versions)


@dataclass
class ArtifactsApiCatalog:
    """Fetches the live list and caches it. A failed refresh serves the stale copy instead of failing."""

    client: httpx.Client | None = None
    ttl_seconds: float = 3600.0
    url: str = ARTIFACTS_URL
    clock: Callable[[], float] = time.monotonic
    _cache: list[Version] = field(default_factory=list, init=False)
    _fetched_at: float | None = field(default=None, init=False)

    def releases(self) -> list[Version]:
        now = self.clock()
        fresh = self._fetched_at is not None and now - self._fetched_at < self.ttl_seconds
        if fresh:
            return list(self._cache)
        try:
            client = self.client or httpx.Client(timeout=10.0)
            resp = client.get(self.url)
            resp.raise_for_status()
            versions = parse_artifacts_versions(resp.json())
            if not versions:
                raise CatalogError("the artifacts API returned no plain releases")
        except (httpx.HTTPError, ValueError, CatalogError) as exc:
            if self._cache:
                return list(self._cache)  # stale beats nothing
            raise CatalogError(f"could not fetch the Elasticsearch version list: {exc}") from exc
        self._cache, self._fetched_at = versions, now
        return list(self._cache)


def parse_apt_index(text: str) -> set[Version]:
    """The Elasticsearch versions an apt Packages index carries (package name `elasticsearch` exactly)."""
    found: set[Version] = set()
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and line[0] not in " \t")
        if fields.get("Package") == "elasticsearch" and _PLAIN.match(fields.get("Version", "")):
            found.add(Version.parse(fields["Version"]))
    return found


@dataclass
class InstallableCatalog:
    """The inner catalog narrowed to releases the machines can install.

    The artifacts API lists a release as soon as it is published, but the Elastic apt repository the machines
    install from can lag by days (9.6.0 was listed while the repository ended at 9.5.6, and a create built three
    machines before the install failed). So a release counts only when the repository for its major carries it.
    One index per major is cached; if one cannot be read, a stale copy is used, and with none that major's
    releases pass through unfiltered, so an unreachable index makes a bad pick fail at install as it did before
    rather than blocking every create. Majors before FIRST_PACKAGED_MAJOR are never filtered.
    """

    inner: VersionCatalog
    client: httpx.Client | None = None
    ttl_seconds: float = 900.0
    url: str = APT_INDEX_URL
    clock: Callable[[], float] = time.monotonic
    retry_seconds: float = 60.0
    # per major: when to look again, and the versions last read (None when never read)
    _cache: dict[int, tuple[float, set[Version] | None]] = field(default_factory=dict, init=False)

    def _packaged(self, major: int) -> set[Version] | None:
        now = self.clock()
        cached = self._cache.get(major)
        if cached and now < cached[0]:
            return cached[1]
        try:
            client = self.client or httpx.Client(timeout=10.0, follow_redirects=True)
            resp = client.get(self.url.format(major=major))
            resp.raise_for_status()
            versions = parse_apt_index(gzip.decompress(resp.content).decode("utf-8", "replace"))
            if not versions:
                raise ValueError("the index lists no elasticsearch package")
        except (httpx.HTTPError, ValueError, OSError, EOFError) as exc:
            log.warning("could not read the Elastic %s.x apt index: %s", major, exc)
            stale = cached[1] if cached else None
            self._cache[major] = (now + self.retry_seconds, stale)   # do not wait out a timeout on every call
            return stale
        self._cache[major] = (now + self.ttl_seconds, versions)
        return versions

    def releases(self) -> list[Version]:
        waiting = self.unpackaged()
        return [v for v in self.inner.releases() if v not in waiting]

    def unpackaged(self) -> set[Version]:
        """Published releases whose packages the apt repository does not have yet."""
        out: set[Version] = set()
        released = self.inner.releases()
        for major in {v.major for v in released if v.major >= FIRST_PACKAGED_MAJOR}:
            packaged = self._packaged(major)
            if packaged is not None:
                out |= {v for v in released if v.major == major and v not in packaged}
        return out


def available_versions(catalog: VersionCatalog) -> list[str]:
    """Selectable versions, newest first."""
    return [str(v) for v in sorted(catalog.releases(), reverse=True)]


def latest_minor(catalog: VersionCatalog, major: int) -> int | None:
    minors = [v.minor for v in catalog.releases() if v.major == major]
    return max(minors) if minors else None


def latest_patch(catalog: VersionCatalog, major: int, minor: int) -> Version | None:
    patches = [v for v in catalog.releases() if v.major == major and v.minor == minor]
    return max(patches) if patches else None


def check_target_version(version: str, catalog: VersionCatalog) -> list[str]:
    """Problems with choosing this version for a new cluster. Empty means it is fine."""
    try:
        target = Version.parse(version)
    except ValueError:
        return [f"{version!r} is not a plain release version such as 9.4.3"]
    if target not in catalog.releases():
        waiting = getattr(catalog, "unpackaged", None)
        if waiting is not None and target in waiting():
            return [(f"{version} is published, but the Elastic apt repository does not carry its packages yet, "
                     f"so the machines could not install it; choose an older version or try again later")]
        return [(f"{version} is not a published Elasticsearch release; "
                f"choose one of the available versions")]
    return []


@dataclass
class UpgradeCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # why it is refused
    notes: list[str] = field(default_factory=list)  # advisory, never blocks


def check_upgrade(current: str, target: str, catalog: VersionCatalog) -> UpgradeCheck:
    try:
        cur, tgt = Version.parse(current), Version.parse(target)
    except ValueError as exc:
        return UpgradeCheck(False, [str(exc)])
    if tgt == cur:
        return UpgradeCheck(False, [f"the cluster is already on {current}"])
    if tgt < cur:
        return UpgradeCheck(False, [f"downgrades are not supported ({current} to {target})"])
    if tgt not in catalog.releases():
        return UpgradeCheck(False, [f"{target} is not a published Elasticsearch release"])

    notes: list[str] = []
    if tgt.major == cur.major:
        top = latest_patch(catalog, cur.major, cur.minor)
        if top and cur < top and tgt.minor > cur.minor:
            notes.append(f"{cur.major}.{cur.minor}.{top.patch} is the latest patch of your current "
                         f"minor; updating to it first is recommended")
        return UpgradeCheck(True, [], notes)

    if tgt.major > cur.major + 1:
        return UpgradeCheck(False, [
            (f"cannot skip a major version ({current} to {target}); upgrade to "
            f"{cur.major + 1}.x first")])

    # Exactly one major ahead: the cluster must be on the latest published minor of its major.
    top_minor = latest_minor(catalog, cur.major)
    if top_minor is None:
        return UpgradeCheck(False, [
            (f"no {cur.major}.x releases are published, so the prerequisite minor for the "
            f"{tgt.major}.x upgrade cannot be determined")])
    if cur.minor != top_minor:
        return UpgradeCheck(False, [
            (f"upgrading to {tgt.major}.x requires the latest {cur.major}.x minor "
            f"({cur.major}.{top_minor}); the cluster is on {cur.major}.{cur.minor}. "
            f"Upgrade to {cur.major}.{top_minor} first")])
    top = latest_patch(catalog, cur.major, top_minor)
    if top and cur < top:
        notes.append(f"{top} is the latest {cur.major}.{top_minor} patch; updating to it before the "
                     f"major upgrade is recommended")
    notes.append("run the deprecation API and fix every critical issue before the major upgrade")
    return UpgradeCheck(True, [], notes)
