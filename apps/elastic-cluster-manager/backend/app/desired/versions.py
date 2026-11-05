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
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

ARTIFACTS_URL = "https://artifacts-api.elastic.co/v1/versions"
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
