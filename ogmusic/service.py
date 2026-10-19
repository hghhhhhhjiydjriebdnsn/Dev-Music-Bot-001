"""Async search and bounded file-download service for three public music APIs."""
from __future__ import annotations

import asyncio
import json
import html
import os
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .models import Track, duration_seconds, normalize_artists, normalize_image
from .security import PublicResolver, UnsafeURLError, validate_public_url

PROVIDERS = ("jiosaavan", "song_downloader", "suryansh")
PROVIDER_URLS = {
    "jiosaavan": "https://jiosaavan-seven.vercel.app/song/",
    "song_downloader": "https://song-downloader-three.vercel.app/search",
    "suryansh": "https://suryansh-music-search-download-api.vercel.app/search",
}


class MusicService:
    """Search public provider APIs, normalize results, and download AAC audio."""

    def __init__(
        self,
        *,
        timeout: float = 8.0,
        retries: int = 1,
        cache_ttl: float = 60.0,
        cache_size: int = 128,
        max_limit: int = 25,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.timeout = max(0.1, min(float(timeout), 30.0))
        self.retries = max(0, min(int(retries), 2))
        self.cache_ttl = max(0.0, min(float(cache_ttl), 3600.0))
        self.cache_size = max(0, min(int(cache_size), 2048))
        self.max_limit = max(1, min(int(max_limit), 50))
        self._session = session
        self._owns_session = session is None
        self._cache: OrderedDict[tuple[str, str, int], tuple[float, tuple[Track, ...]]] = OrderedDict()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(resolver=PublicResolver(), limit=12, ttl_dns_cache=30)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.timeout, connect=min(self.timeout, 5.0)),
                raise_for_status=False,
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._owns_session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def __aenter__(self) -> "MusicService":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _cached(self, key: tuple[str, str, int]) -> list[Track] | None:
        item = self._cache.get(key)
        if item is None:
            return None
        expires, results = item
        if expires <= time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return list(results)

    def _remember(self, key: tuple[str, str, int], results: list[Track]) -> None:
        if not self.cache_size or not self.cache_ttl:
            return
        self._cache[key] = (time.monotonic() + self.cache_ttl, tuple(results[: self.max_limit]))
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    async def search(self, query: str, limit: int = 5, provider: str | None = None) -> list[Track]:
        query = str(query or "").strip()
        if not query or len(query) > 300:
            return []
        limit = max(1, min(int(limit), self.max_limit))
        preferred = provider.lower().strip() if provider else None
        if preferred not in PROVIDERS and preferred is not None:
            raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}")
        key = (query.casefold(), preferred or "", limit)
        cached = self._cached(key)
        if cached is not None:
            return cached[:limit]
        order = ([preferred] if preferred else []) + [name for name in PROVIDERS if name != preferred]
        for name in order:
            try:
                payload = await self._request_provider(name, query)
                tracks = self._normalize(name, query, payload)
                if tracks:
                    result = tracks[:limit]
                    self._remember(key, result)
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, json.JSONDecodeError):
                continue
        self._remember(key, [])
        return []

    async def _request_provider(self, provider: str, query: str) -> Any:
        endpoint = PROVIDER_URLS[provider]
        url = endpoint
        # Use params separately so aiohttp performs safe query encoding.
        await validate_public_url(endpoint)
        session = await self._get_session()
        params = {"query" if provider == "jiosaavan" else "song": query}
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout), allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise aiohttp.ClientError("redirect without Location")
                        # Provider API redirects are handled only after public DNS validation.
                        redirected = urljoin(str(response.url), location)
                        await validate_public_url(redirected)
                        async with session.get(redirected, timeout=aiohttp.ClientTimeout(total=self.timeout), allow_redirects=False) as redirected_response:
                            if redirected_response.status != 200:
                                raise aiohttp.ClientError(f"provider HTTP {redirected_response.status}")
                            return await redirected_response.json(content_type=None)
                    if response.status != 200:
                        raise aiohttp.ClientError(f"provider HTTP {response.status}")
                    return await response.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    await asyncio.sleep(min(0.1 * (attempt + 1), 0.25))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _records(provider: str, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("results", "data", "songs", "tracks", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested in ("results", "songs", "tracks", "data"):
                    if isinstance(value.get(nested), list):
                        return [item for item in value[nested] if isinstance(item, dict)]
        # Some versions wrap a single record or put a song object directly at root.
        if any(key in payload for key in ("song", "title", "name", "media_url", "download_url")):
            value = payload.get("song")
            return [value] if isinstance(value, dict) else [payload]
        return []

    @staticmethod
    def _restricted(record: dict[str, Any]) -> bool:
        if str(record.get("disabled", "")).strip().lower() in {"1", "true", "yes"}:
            return True
        drm = record.get("is_drm")
        if drm is True or str(drm).strip().lower() in {"1", "true", "yes"}:
            return True
        rights = record.get("rights")
        if isinstance(rights, dict):
            reason = str(rights.get("reason", "")).lower()
            if any(marker in reason for marker in ("pro only", "premium only", "restricted", "drm")):
                return True
        return False

    @classmethod
    def _normalize(cls, provider: str, query: str, payload: Any) -> list[Track]:
        tracks: list[Track] = []
        source = Track.api_query_url(provider, query)
        for record in cls._records(provider, payload):
            if cls._restricted(record):
                continue
            title = html.unescape(str(record.get("title") or record.get("song") or record.get("name") or "")).strip()
            artists = normalize_artists(
                record.get("artists") or record.get("primary_artists") or record.get("artist")
            )
            stream = record.get("media_url") or record.get("download_url") or record.get("stream_url") or record.get("url")
            if isinstance(stream, dict):
                stream = stream.get("url") or stream.get("link")
            if isinstance(stream, list):
                stream = next((item.get("url") if isinstance(item, dict) else item for item in stream if item), None)
            stream = str(stream or "").strip()
            if not title or not stream or not stream.startswith(("https://", "http://")):
                continue
            tracks.append(Track(
                title=title,
                artists=artists,
                duration=duration_seconds(record.get("duration") or record.get("duration_seconds")),
                thumbnail=normalize_image(record.get("image") or record.get("thumbnail") or record.get("thumb")),
                stream_url=stream,
                source_url=source,
                provider=provider,
            ))
        return tracks

    async def download_audio(
        self,
        track: Track,
        directory: str | os.PathLike[str],
        max_bytes: int = 50 * 1024 * 1024,
    ) -> Path:
        """Download a track as an actual AAC/MP4 container with bounded streaming.

        The .m4a extension describes the MP4/AAC source; this never renames it to
        MP3. Redirects are followed manually and revalidated at every hop.
        """
        if not isinstance(track, Track):
            raise TypeError("track must be a Track")
        max_bytes = int(max_bytes)
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        current = await validate_public_url(track.stream_url)
        session = await self._get_session()
        temp_path: str | None = None
        try:
            for redirect_count in range(6):
                response = await session.get(
                    current,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=False,
                )
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    response.release()
                    if not location or redirect_count >= 5:
                        raise aiohttp.ClientError("invalid or excessive download redirects")
                    current = await validate_public_url(urljoin(current, location))
                    continue
                if response.status != 200:
                    response.release()
                    raise aiohttp.ClientError(f"download HTTP {response.status}")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise ValueError("download exceeds max_bytes")
                    except ValueError as exc:
                        response.release()
                        if str(exc) == "download exceeds max_bytes":
                            raise
                fd, temp_path = tempfile.mkstemp(prefix=".ogmusic-", suffix=".part", dir=destination)
                total = 0
                try:
                    with os.fdopen(fd, "wb") as output:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise ValueError("download exceeds max_bytes")
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                finally:
                    response.release()
                if total == 0:
                    raise ValueError("empty audio response")
                filename = f"{__import__('uuid').uuid4().hex}.m4a"
                final_path = destination / filename
                os.replace(temp_path, final_path)
                temp_path = None
                return final_path
            raise aiohttp.ClientError("excessive download redirects")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
