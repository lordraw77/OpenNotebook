"""Fetching web pages safely (SSRF protection) and extracting their links for a bounded crawl.

- only http and https, no credentials in the URL;
- every host is resolved and each address checked: loopback, private, link-local (cloud metadata),
  multicast, reserved and unspecified addresses are refused unless WEB_ALLOW_PRIVATE is set;
- the address actually connected to is checked again before the body is read (DNS rebinding);
- redirects are followed manually, each hop re-validated, up to WEB_MAX_REDIRECTS;
- size (WEB_MAX_MB) and time (WEB_TIMEOUT_S) limits; environment proxies are ignored;
- for crawls, robots.txt is respected and only links on the same host are followed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

import httpx

from opennotebook.config import get_settings
from opennotebook.ingestion.parsers import UnsupportedContent

ACCEPTED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown", "application/pdf")


class FetchError(UnsupportedContent):
    """The URL cannot be fetched (policy, HTTP error, unsupported content); not retryable."""


class TransientFetchError(Exception):
    """Network problem worth retrying (timeout, connection reset, HTTP 5xx / 429)."""


@dataclass
class Fetched:
    url: str  # final URL after redirects
    content_type: str
    data: bytes


def normalize_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchError("Only http and https URLs are supported")
    if not parts.hostname:
        raise FetchError("The URL has no host")
    if parts.username or parts.password:
        raise FetchError("URLs with credentials are not allowed")
    netloc = parts.hostname.lower()
    if parts.port and parts.port not in (80, 443):
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def address_allowed(ip: str) -> bool:
    if get_settings().web_allow_private:
        return True
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def check_host(host: str, port: int) -> None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"Host not found: {host}") from exc
    addresses = {info[4][0] for info in infos}
    blocked = [a for a in addresses if not address_allowed(a)]
    if blocked or not addresses:
        raise FetchError(f"Address of {host} is not allowed (private or reserved network)")


async def fetch(url: str, *, accept: tuple[str, ...] = ACCEPTED_TYPES) -> Fetched:
    settings = get_settings()
    limit = settings.web_max_mb * 1024 * 1024
    current = normalize_url(url)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=settings.web_timeout_s,
        trust_env=False,
        headers={"User-Agent": settings.web_user_agent, "Accept": ", ".join(accept) + ";q=0.9, */*;q=0.1"},
    ) as client:
        for _ in range(settings.web_max_redirects + 1):
            parts = urlsplit(current)
            await check_host(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))
            try:
                async with client.stream("GET", current) as resp:
                    stream = resp.extensions.get("network_stream")
                    peer = stream.get_extra_info("server_addr") if stream is not None else None
                    if peer and not address_allowed(str(peer[0])):
                        raise FetchError("Connected address is not allowed (DNS rebinding?)")
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError(f"Redirect without location from {current}")
                        current = normalize_url(urljoin(current, location))
                        continue
                    if resp.status_code == 429 or resp.status_code >= 500:
                        raise TransientFetchError(f"HTTP {resp.status_code} from {current}")
                    if resp.status_code >= 400:
                        raise FetchError(f"HTTP {resp.status_code} from {current}")
                    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if content_type and content_type not in accept:
                        raise FetchError(f"Unsupported content type {content_type}")
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > limit:
                        raise FetchError(f"Page larger than {settings.web_max_mb} MB")
                    body = bytearray()
                    async for block in resp.aiter_bytes():
                        body += block
                        if len(body) > limit:
                            raise FetchError(f"Page larger than {settings.web_max_mb} MB")
                    return Fetched(url=current, content_type=content_type, data=bytes(body))
            except httpx.TimeoutException as exc:
                raise TransientFetchError(f"Timeout fetching {current}") from exc
            except httpx.TransportError as exc:
                raise TransientFetchError(
                    f"Network error fetching {current}: {exc.__class__.__name__}"
                ) from exc
        raise FetchError(f"More than {settings.web_max_redirects} redirects")


def same_host_links(html: str, base_url: str) -> list[str]:
    """Absolute links of the page on the same host, normalized, in document order, without duplicates."""
    import lxml.html

    try:
        tree = lxml.html.fromstring(html)
    except (ValueError, lxml.etree.ParserError):  # type: ignore[attr-defined]
        return []
    host = urlsplit(base_url).hostname
    out: dict[str, None] = {}
    for href in tree.xpath("//a/@href"):
        try:
            url = normalize_url(urljoin(base_url, str(href)))
        except (FetchError, ValueError):
            continue
        if urlsplit(url).hostname == host and url != base_url:
            if not url.lower().endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".zip", ".exe", ".mp4", ".css", ".js")
            ):
                out[url] = None
    return list(out)


async def robots_allows(url: str) -> bool:
    """robots.txt check for crawled pages (the page the user asked for is always fetched)."""
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    parser = urllib.robotparser.RobotFileParser()
    try:
        fetched = await fetch(robots_url, accept=("text/plain",))
    except (FetchError, TransientFetchError):
        return True
    parser.parse(fetched.data.decode("utf-8", "replace").splitlines())
    return parser.can_fetch(get_settings().web_user_agent, url)
