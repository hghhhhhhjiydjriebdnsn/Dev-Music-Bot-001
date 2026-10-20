"""Public URL validation that rejects private DNS answers and unsafe redirects."""
from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlsplit

import aiohttp


class UnsafeURLError(ValueError):
    """A URL is not a safe public HTTP(S) destination."""


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


async def validate_public_url(url: str, *, require_https: bool = True) -> str:
    """Validate URL syntax and every resolved address before making a request.

    The request connector also applies this test to its actual DNS answer, closing
    the validation/use gap caused by DNS rebinding.
    """
    if not isinstance(url, str) or len(url) > 4096:
        raise UnsafeURLError("invalid URL")
    parsed = urlsplit(url)
    allowed = {"https"} if require_https else {"http", "https"}
    if parsed.scheme.lower() not in allowed or not parsed.hostname:
        raise UnsafeURLError("URL must use an allowed scheme and have a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL credentials are not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("invalid URL port") from exc
    hostname = parsed.hostname.rstrip(".")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise UnsafeURLError("non-public IP address")
        return url
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            hostname, port, type=__import__("socket").SOCK_STREAM
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise UnsafeURLError("hostname could not be safely resolved") from exc
    addresses = {item[4][0] for item in infos}
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise UnsafeURLError("hostname resolves to a non-public address")
    return url


class PublicResolver(aiohttp.abc.AbstractResolver):
    """aiohttp resolver that rejects any DNS answer outside globally routable IPs."""

    def __init__(self) -> None:
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0):
        answers = await self._resolver.resolve(host, port, family)
        if not answers or any(not _public_ip(answer["host"]) for answer in answers):
            raise OSError("DNS resolution included a non-public address")
        return answers

    async def close(self) -> None:
        await self._resolver.close()
