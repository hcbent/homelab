"""Build-time helper for the worker image: download a file and keep it only if its SHA-256 matches.

Standard library only, so it runs in a plain python image before anything else is installed.

    fetch_tool.py fetch URL SHA256 DEST
    fetch_tool.py unzip-member ZIP MEMBER DEST MODE

Properties, each covered by tests/test_fetch_tool.py:
  * HTTPS only, so a redirect or a typo cannot downgrade the transfer to plain HTTP
  * the bytes are hashed while they are written to a temporary file next to DEST, and renamed into place
    only when the hash matches. A mismatch leaves nothing at DEST and fails the build.
  * a transient failure (connection error, HTTP 5xx or 429) is retried with a growing delay, because release
    hosts do return 504s (Milestone 0). A wrong checksum, an HTTP 4xx or an oversized body is not retried.
  * a body larger than the cap is refused, so a bad URL cannot fill the build disk
  * unzip-member extracts one named file by reading its bytes, never by trusting a path inside the archive
"""
import hashlib
import http.client
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

MAX_BYTES = 200 * 1024 * 1024  # the largest artifact here (the provider) is about 30 MB
CHUNK = 1 << 20


class FetchError(Exception):
    """The download could not be completed or verified. The message says why."""


class ChecksumMismatch(FetchError):
    pass


def _transient(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException))


def fetch(url: str, sha256: str, dest: str | Path, *, attempts: int = 5, delay: float = 2.0,
          timeout: float = 60.0, opener: Callable = urllib.request.urlopen,
          sleep: Callable[[float], None] = time.sleep) -> str:
    """Download `url` to `dest` if and only if it hashes to `sha256`. Returns the hash."""
    expected = sha256.strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise FetchError("the expected checksum must be 64 hexadecimal characters")
    if urlparse(url).scheme != "https":
        raise FetchError(f"refusing to download over anything but https: {url}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out, opener(url, timeout=timeout) as resp:
                if urlparse(resp.geturl()).scheme != "https":
                    raise FetchError("the download was redirected away from https")
                digest, size = hashlib.sha256(), 0
                while chunk := resp.read(CHUNK):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError(f"the download is larger than {MAX_BYTES} bytes; refusing it")
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != expected:
                raise ChecksumMismatch(
                    f"checksum mismatch for {url}: expected {expected}, got {digest.hexdigest()}")
            tmp.replace(dest)
            return expected
        except FetchError:  # includes ChecksumMismatch: never retried
            tmp.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            if not _transient(exc):
                raise FetchError(f"download failed: {exc}") from exc
            last = exc
            if attempt < attempts:
                print(f"attempt {attempt}/{attempts} failed ({exc}); retrying", file=sys.stderr)
                sleep(delay * attempt)
    raise FetchError(f"download failed after {attempts} attempts: {last}")


def unzip_member(archive: str | Path, member: str, dest: str | Path, mode: int = 0o755) -> None:
    """Write one named file out of a zip to `dest`. The name inside the archive is only a lookup key."""
    with zipfile.ZipFile(archive) as z:
        try:
            data = z.read(member)
        except KeyError as exc:
            raise FetchError(f"{member} is not in {archive}") from exc
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.chmod(mode)


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 5 and argv[1] == "fetch":
            fetch(argv[2], argv[3], argv[4])
            print(f"verified {argv[4]} ({argv[3]})")
        elif len(argv) == 6 and argv[1] == "unzip-member":
            unzip_member(argv[2], argv[3], argv[4], int(argv[5], 8))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
