"""Fetching URLs chosen by strangers (Reddit posts, article pages) safely.

A post can link to anything, including addresses that only make sense from inside
this server: the cloud metadata service (169.254.169.254), the workers' wake
ports, Qdrant, the database. So every fetch here:

  * allows http and https only;
  * resolves the host and refuses any address that is not public (private,
    loopback, link-local, reserved, multicast), on every redirect hop — redirects
    are followed by hand, never by the HTTP client;
  * caps the bytes read and the content type accepted.

ffmpeg is never handed a remote URL (it would follow anything); media is
downloaded here and given to ffmpeg as local files.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

UA = "ContentCorpus/1.0 (+https://content-corpus.strophic.in)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_REDIRECTS = 5
# Wikimedia refuses a browser's user agent from a server (403) and asks for one that
# says who is asking (its User-Agent policy); everyone else gets the browser's.
_HONEST_HOSTS = ("wikimedia.org", "wikipedia.org", "wikidata.org")


def user_agent(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return UA if any(host == h or host.endswith("." + h) for h in _HONEST_HOSTS) else BROWSER_UA


# Swapped by tests (fake hosts resolve to a public test address).
RESOLVE = socket.getaddrinfo


class Blocked(Exception):
    """The URL is not one this server may fetch."""


class TooBig(Exception):
    """The response is larger than allowed."""


class WrongType(Exception):
    """The response is not the kind of content asked for."""


@dataclass
class Fetched:
    url: str              # after redirects
    content_type: str
    content: bytes


def check(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked(f"only http(s) URLs: {url[:80]}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = RESOLVE(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as e:
        raise Blocked(f"cannot resolve {parts.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked(f"{parts.hostname} is not a public address")


def _open(client: httpx.Client, url: str, headers: dict | None):
    """The final (non-redirect) response, streamed; every hop checked first."""
    for _ in range(MAX_REDIRECTS + 1):
        check(url)
        req = client.build_request("GET", url, headers={"User-Agent": UA, **(headers or {})})
        r = client.send(req, stream=True, follow_redirects=False)
        if r.is_redirect and "location" in r.headers:
            nxt = urljoin(url, r.headers["location"])
            r.close()
            url = nxt
            continue
        return url, r
    raise Blocked("too many redirects")


def _type_ok(ctype: str, accept: tuple[str, ...] | None) -> bool:
    return accept is None or any(ctype.startswith(a) for a in accept)


def get(client: httpx.Client, url: str, *, max_bytes: int, accept: tuple[str, ...] | None = None,
        headers: dict | None = None) -> Fetched:
    final, r = _open(client, url, headers)
    try:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if not _type_ok(ctype, accept):
            raise WrongType(f"{ctype or 'no content type'} from {final[:80]}")
        if int(r.headers.get("content-length") or 0) > max_bytes:
            raise TooBig(f"{final[:80]} is larger than {max_bytes} bytes")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > max_bytes:
                raise TooBig(f"{final[:80]} is larger than {max_bytes} bytes")
        return Fetched(final, ctype, bytes(buf))
    finally:
        r.close()


def download(client: httpx.Client, url: str, dest: Path, *, max_bytes: int,
             accept: tuple[str, ...] | None = None, headers: dict | None = None) -> Path:
    """Like get(), streamed to a file (removed again if anything goes wrong)."""
    final, r = _open(client, url, headers)
    try:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if not _type_ok(ctype, accept):
            raise WrongType(f"{ctype or 'no content type'} from {final[:80]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                n += len(chunk)
                if n > max_bytes:
                    raise TooBig(f"{final[:80]} is larger than {max_bytes} bytes")
                f.write(chunk)
        return dest
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        r.close()
