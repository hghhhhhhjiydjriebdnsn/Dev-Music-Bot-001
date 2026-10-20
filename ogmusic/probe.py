"""Optional credential-free provider health probe: ``python -m ogmusic.probe``."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from .service import PROVIDERS, MusicService


async def run(query: str) -> list[dict[str, object]]:
    service = MusicService(timeout=6.0, retries=0, cache_size=0)
    results: list[dict[str, object]] = []
    try:
        for provider in PROVIDERS:
            started = time.monotonic()
            item: dict[str, object] = {"provider": provider}
            try:
                payload = await service._request_provider(provider, query)
                tracks = service._normalize(provider, query, payload)
                item.update(ok=True, results=len(tracks), elapsed_ms=round((time.monotonic() - started) * 1000))
            except Exception as exc:  # Report a compact diagnostic; never credentials or response bodies.
                item.update(ok=False, error=type(exc).__name__, elapsed_ms=round((time.monotonic() - started) * 1000))
            results.append(item)
    finally:
        await service.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe public music search APIs")
    parser.add_argument("query", nargs="?", default="Chandani")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.query)), separators=(",", ":")))


if __name__ == "__main__":
    main()
