"""Public-only HTTP transport, with the checked DNS address pinned to the socket.

No environment proxy, credentials, automatic redirects or DNS re-resolution.
Callers must bound the decoded response and close it in all paths.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

import requests
import urllib3


def _public_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Deny transition/translation ranges conservatively. A public IPv6
        # wrapper must not encode a loopback/private IPv4 destination.
        if address.ipv4_mapped is not None:
            return address.ipv4_mapped.is_global
        if (address.sixtofour is not None or address.teredo is not None
                or address in ipaddress.ip_network("64:ff9b::/96")
                or address in ipaddress.ip_network("64:ff9b:1::/48")):
            return False
    return True


def resolve_public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A public HTTP(S) URL is required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are forbidden")
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not _public_address(addr) for addr in addresses):
        raise ValueError("Local/private URLs are not allowed")
    return parsed, host, port, addresses


class _PinnedResponse(requests.Response):
    def close(self):
        try:
            super().close()
        finally:
            self._pool.close()


def public_get(url, *, headers=None, timeout=(3.05, 10), **kwargs):
    parsed, host, port, addresses = resolve_public_url(url)
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            addresses[0], port, server_hostname=host, assert_hostname=host,
            cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where(),
        )
    else:
        pool = urllib3.HTTPConnectionPool(addresses[0], port)
    authority = f"[{host}]" if ":" in host else host
    if port != (443 if parsed.scheme == "https" else 80):
        authority += f":{port}"
    request_headers = {"Accept-Encoding": "identity", **(headers or {}), "Host": authority}
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    limit = urllib3.Timeout(connect=timeout[0], read=timeout[1]) if isinstance(timeout, tuple) else timeout
    try:
        raw = pool.urlopen("GET", target, headers=request_headers, timeout=limit,
                           redirect=False, retries=False, preload_content=False)
    except Exception:
        pool.close()
        raise
    response = _PinnedResponse()
    response._pool = pool
    response.status_code = raw.status
    response.headers = requests.structures.CaseInsensitiveDict(raw.headers)
    response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    response.url = url
    response.raw = raw
    return response


def bounded_text(response, limit=2 * 1024 * 1024):
    try:
        parts, downloaded = [], 0
        for chunk in response.iter_content(chunk_size=16384):
            parts.append(chunk[:limit - downloaded])
            downloaded += len(parts[-1])
            if downloaded >= limit:
                break
        return b"".join(parts).decode(response.encoding or "utf-8", errors="replace")
    finally:
        response.close()
