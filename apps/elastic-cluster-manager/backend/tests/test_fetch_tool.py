"""The build-time download helper: nothing unverified ever lands where the image will use it."""
import hashlib
import importlib.util
import io
import urllib.error
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("fetch_tool", Path(__file__).parents[1] / "docker" / "fetch_tool.py")
ft = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ft)

BODY = b"pretend this is a provider" * 1000
GOOD = hashlib.sha256(BODY).hexdigest()
URL = "https://releases.example.org/tool.zip"


class Response(io.BytesIO):
    def __init__(self, body, url=URL):
        super().__init__(body)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def serving(*outcomes):
    """An opener that yields each outcome in turn: bytes are served, exceptions are raised."""
    queue = list(outcomes)
    calls = []

    def opener(url, timeout=None):
        calls.append(url)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return Response(outcome)

    opener.calls = calls
    return opener


def http_error(code):
    return urllib.error.HTTPError(URL, code, "x", {}, None)


def fetch(tmp_path, opener, sha=GOOD, **kw):
    dest = tmp_path / "out" / "tool.zip"
    ft.fetch(URL, sha, dest, opener=opener, sleep=lambda s: None, **kw)
    return dest


def leftovers(tmp_path):
    return sorted(p.name for p in (tmp_path / "out").iterdir()) if (tmp_path / "out").exists() else []


def test_a_matching_download_is_kept(tmp_path):
    dest = fetch(tmp_path, serving(BODY))
    assert dest.read_bytes() == BODY and leftovers(tmp_path) == ["tool.zip"]


def test_a_wrong_checksum_leaves_nothing_behind_and_is_not_retried(tmp_path):
    opener = serving(BODY, BODY)
    with pytest.raises(ft.ChecksumMismatch, match="expected " + "0" * 64):
        fetch(tmp_path, opener, sha="0" * 64)
    assert len(opener.calls) == 1 and leftovers(tmp_path) == []


def test_a_tampered_body_is_refused_even_if_the_first_bytes_look_right(tmp_path):
    with pytest.raises(ft.ChecksumMismatch):
        fetch(tmp_path, serving(BODY + b"x"))
    assert leftovers(tmp_path) == []


@pytest.mark.parametrize("failure", [http_error(504), http_error(503), http_error(429),
                                     urllib.error.URLError("connection reset"), TimeoutError()])
def test_a_transient_failure_is_retried(tmp_path, failure):
    opener = serving(failure, failure, BODY)
    dest = fetch(tmp_path, opener)
    assert dest.read_bytes() == BODY and len(opener.calls) == 3


def test_retries_stop_after_the_attempt_limit(tmp_path):
    opener = serving(*[http_error(504)] * 3)
    with pytest.raises(ft.FetchError, match="after 3 attempts"):
        fetch(tmp_path, opener, attempts=3)
    assert len(opener.calls) == 3 and leftovers(tmp_path) == []


def test_the_delay_between_attempts_grows(tmp_path):
    waits = []
    with pytest.raises(ft.FetchError):
        ft.fetch(URL, GOOD, tmp_path / "t", opener=serving(*[http_error(504)] * 3), attempts=3, delay=2,
                 sleep=waits.append)
    assert waits == [2, 4]


@pytest.mark.parametrize("code", [403, 404])
def test_a_client_error_is_not_retried(tmp_path, code):
    opener = serving(http_error(code), BODY)
    with pytest.raises(ft.FetchError, match="download failed"):
        fetch(tmp_path, opener)
    assert len(opener.calls) == 1


@pytest.mark.parametrize("url", ["http://releases.example.org/tool.zip", "file:///etc/passwd",
                                 "ftp://example.org/tool.zip"])
def test_only_https_is_accepted(tmp_path, url):
    with pytest.raises(ft.FetchError, match="https"):
        ft.fetch(url, GOOD, tmp_path / "t", opener=serving(BODY), sleep=lambda s: None)


def test_a_redirect_away_from_https_is_refused(tmp_path):
    def opener(url, timeout=None):
        return Response(BODY, url="http://elsewhere.example.org/tool.zip")
    with pytest.raises(ft.FetchError, match="redirected away from https"):
        ft.fetch(URL, GOOD, tmp_path / "t", opener=opener, sleep=lambda s: None)
    assert not (tmp_path / "t").exists()


@pytest.mark.parametrize("sha", ["", "abc", "g" * 64, "A" * 63])
def test_a_malformed_expected_checksum_is_refused_before_any_download(tmp_path, sha):
    opener = serving(BODY)
    with pytest.raises(ft.FetchError, match="64 hexadecimal"):
        fetch(tmp_path, opener, sha=sha)
    assert opener.calls == []


def test_an_uppercase_checksum_matches(tmp_path):
    assert fetch(tmp_path, serving(BODY), sha=GOOD.upper()).read_bytes() == BODY


def test_an_oversized_body_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "MAX_BYTES", 100)
    with pytest.raises(ft.FetchError, match="larger than 100"):
        fetch(tmp_path, serving(BODY))
    assert leftovers(tmp_path) == []


# ---- extracting one file --------------------------------------------------------------------------------

def make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def test_unzip_member_writes_only_the_named_file_with_the_mode(tmp_path):
    archive = tmp_path / "a.zip"
    make_zip(archive, {"terraform": b"#!binary", "LICENSE.txt": b"text"})
    ft.unzip_member(archive, "terraform", tmp_path / "bin" / "terraform", 0o755)
    out = tmp_path / "bin" / "terraform"
    assert out.read_bytes() == b"#!binary" and out.stat().st_mode & 0o777 == 0o755
    assert sorted(p.name for p in (tmp_path / "bin").iterdir()) == ["terraform"]


def test_unzip_member_never_trusts_a_path_inside_the_archive(tmp_path):
    archive = tmp_path / "a.zip"
    make_zip(archive, {"../../escape": b"x", "terraform": b"ok"})
    ft.unzip_member(archive, "terraform", tmp_path / "bin" / "terraform")
    assert not (tmp_path.parent / "escape").exists() and not (tmp_path / "escape").exists()


def test_unzip_member_reports_a_missing_member(tmp_path):
    archive = tmp_path / "a.zip"
    make_zip(archive, {"other": b"x"})
    with pytest.raises(ft.FetchError, match="terraform is not in"):
        ft.unzip_member(archive, "terraform", tmp_path / "t")
    assert not (tmp_path / "t").exists()


def test_the_command_line_reports_failure_with_a_nonzero_exit(tmp_path, capsys):
    assert ft.main(["fetch_tool.py", "fetch", "http://x/y", GOOD, str(tmp_path / "t")]) == 1
    assert "https" in capsys.readouterr().err
    assert ft.main(["fetch_tool.py"]) == 2
