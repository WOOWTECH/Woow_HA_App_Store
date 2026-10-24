"""Anonymous HTTPS checks for published PaaS hostnames.

Only PaaS-returned hostnames enter this module. DNS answers are validated and
pinned for the actual connection; redirects are never followed. The result is
an observation, not proof that a particular person can sign in.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import aiohttp

HOSTNAME = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$", re.I)


class PrivateAddressError(ValueError):
    pass


class PublicOnlyResolver(aiohttp.abc.AbstractResolver):
    def __init__(self) -> None:
        self._pinned: dict[tuple[str, int], list[dict]] = {}

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict]:
        if (host, port) in self._pinned:
            return self._pinned[(host, port)]
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
        results = []
        for address_family, _, _, _, sockaddr in addresses:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise PrivateAddressError("DNS points to a private or reserved address")
            results.append({
                "hostname": host, "host": str(ip), "port": port,
                "family": address_family, "proto": 0, "flags": 0,
            })
        if not results:
            raise OSError("No DNS addresses")
        self._pinned[(host, port)] = results
        return results

    async def close(self) -> None:
        return None


def classify_response(http_status: int, location: str, hostname: str, server: str) -> str:
    """Describe an anonymous response; do not treat it as policy proof."""
    target = urlparse(location)
    redirect_host = (target.hostname or "").lower()
    same_origin = (
        (not target.netloc and not target.scheme)
        or (target.scheme == "https" and redirect_host == hostname.lower())
    )
    team_login = (
        target.scheme == "https"
        and redirect_host.endswith(".cloudflareaccess.com")
        and target.path.rstrip("/").lower()
        == f"/cdn-cgi/access/login/{hostname}".lower()
    )
    if (
        http_status in (301, 302, 303, 307, 308)
        and server.lower() == "cloudflare"
        and ((same_origin and target.path.startswith("/cdn-cgi/access/")) or team_login)
    ):
        return "login_required"
    if http_status == 200:
        return "public_response"
    if http_status == 403:
        return "blocked_or_protected"
    if http_status >= 500:
        return "origin_error"
    return "undetermined"


async def probe(hostname: str) -> dict:
    if not isinstance(hostname, str) or not HOSTNAME.fullmatch(hostname) or hostname.endswith(".local"):
        return {"hostname": hostname, "status": "blocked_private_address"}
    try:
        # aiohttp retains the original hostname for TLS SNI and Host while the
        # custom resolver pins the vetted IP for the TCP connection.
        resolver = PublicOnlyResolver()
        await resolver.resolve(hostname, 443)
        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
        async with aiohttp.ClientSession(connector=connector, trust_env=False, timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(f"https://{hostname}/", allow_redirects=False) as response:
                status = classify_response(
                    response.status, response.headers.get("Location", ""),
                    hostname, response.headers.get("Server", ""),
                )
                return {"hostname": hostname, "status": status, "http_status": response.status}
    except PrivateAddressError:
        return {"hostname": hostname, "status": "blocked_private_address"}
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return {"hostname": hostname, "status": "unreachable"}
