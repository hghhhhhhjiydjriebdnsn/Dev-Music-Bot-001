"""Tests for the provider-only music package; no Telegram/core imports."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ogmusic import MusicService, Track
from ogmusic.security import UnsafeURLError, validate_public_url


class ProviderNormalizationTests(unittest.TestCase):
    def test_jiosaavan_schema_and_restricted_tracks(self):
        payload = [
            {
                "song": "Open Song", "primary_artists": "Artist A, Artist B",
                "duration": "203", "image": [{"link": "https://img.example/a"}],
                "media_url": "https://cdn.example/open.mp4",
            },
            {
                "song": "Locked Song", "is_drm": 1, "disabled": True,
                "rights": {"reason": "Pro Only"}, "media_url": "https://cdn.example/locked.mp4",
            },
        ]
        tracks = MusicService._normalize("jiosaavan", "Chandani", payload)
        self.assertEqual(len(tracks), 1)
        track = tracks[0]
        self.assertEqual((track.title, track.artists, track.duration), ("Open Song", "Artist A, Artist B", 203))
        self.assertEqual(track.source_url, "https://jiosaavan-seven.vercel.app/song/?query=Chandani")
        self.assertEqual(track.to_song_dict(), {
            "title": "Open Song", "duration": "3:23", "thumb": "https://img.example/a",
            "source": track.source_url, "remote": track.stream_url, "parsed": True,
            "provider": "jiosaavan", "artists": "Artist A, Artist B", "audio_only": True,
        })
        self.assertEqual(Track.from_dict(track.to_dict()), track)

    def test_downloader_envelope_and_tolerant_fields(self):
        payload = {"success": True, "results": [{
            "title": "Dance", "artists": ["A", {"name": "B"}], "album": "Album",
            "duration": "3:17", "download_url": "https://aac.saavncdn.com/audio_320.mp4",
        }]}
        tracks = MusicService._normalize("suryansh", "Sari", payload)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].duration, 197)
        self.assertEqual(tracks[0].artists, "A, B")
        self.assertEqual(tracks[0].source_url, "https://suryansh-music-search-download-api.vercel.app/search?song=Sari")
        self.assertIsNone(tracks[0].thumbnail)

    def test_schema_variants_and_invalid_records_are_skipped(self):
        payload = {"data": {"results": [
            {"name": "Nested", "artist": {"name": "Solo"}, "duration": "01:02:03", "url": "https://x.example/a"},
            {"title": "No URL"},
            {"title": "Bad URL", "download_url": "file:///etc/passwd"},
        ]}}
        tracks = MusicService._normalize("song_downloader", "Q", payload)
        self.assertEqual(len(tracks), 1)
        self.assertEqual((tracks[0].duration, tracks[0].artists), (3723, "Solo"))


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_and_result_limit(self):
        service = MusicService(cache_size=0)
        calls = []

        async def provider(name, query):
            calls.append(name)
            if name == "jiosaavan":
                raise OSError("offline")
            return {"success": True, "results": [
                {"title": f"Song {n}", "duration": "2:00", "download_url": f"https://cdn.example/{n}.mp4"}
                for n in range(4)
            ]}

        service._request_provider = provider
        found = await service.search("q", limit=2)
        self.assertEqual(calls, ["jiosaavan", "song_downloader"])
        self.assertEqual(len(found), 2)
        self.assertTrue(all(track.provider == "song_downloader" for track in found))

    async def test_cache_has_hard_entry_and_result_bounds(self):
        service = MusicService(cache_ttl=60, cache_size=1, max_limit=2)
        calls = []

        async def provider(name, query):
            calls.append(query)
            return [{"title": query, "media_url": "https://cdn.example/a.mp4"}]

        service._request_provider = provider
        self.assertEqual(len(await service.search("a", limit=20)), 1)
        self.assertEqual(len(await service.search("a", limit=20)), 1)
        self.assertEqual(calls, ["a"])
        await service.search("b")
        self.assertLessEqual(len(service._cache), 1)
        self.assertEqual(service.max_limit, 2)

    async def test_preferred_provider_is_first_but_fallback_remains(self):
        service = MusicService(cache_size=0)
        calls = []

        async def provider(name, query):
            calls.append(name)
            if name == "suryansh":
                return []
            return [{"title": "Fallback", "media_url": "https://cdn.example/a.mp4"}]

        service._request_provider = provider
        result = await service.search("q", provider="suryansh")
        self.assertEqual(calls[:2], ["suryansh", "jiosaavan"])
        self.assertEqual(result[0].provider, "jiosaavan")


class SSRFTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_private_and_non_https_are_rejected(self):
        for url in ("https://127.0.0.1/a", "https://[::1]/", "http://example.com"):
            with self.subTest(url=url), self.assertRaises(UnsafeURLError):
                await validate_public_url(url)

    async def test_hostname_that_resolves_private_is_rejected(self):
        class PrivateLoop:
            async def getaddrinfo(self, *args, **kwargs):
                return [(2, 1, 6, "", ("192.168.1.9", 443))]

        with patch("ogmusic.security.asyncio.get_running_loop", return_value=PrivateLoop()):
            with self.assertRaises(UnsafeURLError):
                await validate_public_url("https://attacker.example/file")


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    class Content:
        def __init__(self, chunks):
            self.chunks = chunks

        async def iter_chunked(self, _size):
            for chunk in self.chunks:
                yield chunk

    class Response:
        def __init__(self, chunks, headers=None, status=200):
            self.status = status
            self.headers = headers or {}
            self.content = DownloadTests.Content(chunks)
            self.released = False

        def release(self):
            self.released = True

    class Session:
        closed = False

        def __init__(self, response):
            self.response = response
            self.calls = []

        async def get(self, url, **kwargs):
            self.calls.append(url)
            return self.response

    @staticmethod
    def track(url="https://cdn.example/audio.mp4"):
        return Track("Song", "Artist", 100, None, url, "https://api.example/search?q=x", "test")

    async def test_download_streams_atomic_m4a(self):
        response = self.Response([b"ftyp", b"AAC data"])
        service = MusicService(session=self.Session(response))
        with tempfile.TemporaryDirectory() as directory, patch("ogmusic.service.validate_public_url", new=AsyncMock(side_effect=lambda url: url)):
            path = await service.download_audio(self.track(), directory, max_bytes=100)
            self.assertEqual(path.suffix, ".m4a")
            self.assertEqual(path.read_bytes(), b"ftypAAC data")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    async def test_oversize_download_leaves_no_partial_file(self):
        response = self.Response([b"1234", b"5678"])
        service = MusicService(session=self.Session(response))
        with tempfile.TemporaryDirectory() as directory, patch("ogmusic.service.validate_public_url", new=AsyncMock(side_effect=lambda url: url)):
            with self.assertRaises(ValueError):
                await service.download_audio(self.track(), directory, max_bytes=5)
            self.assertEqual(list(Path(directory).iterdir()), [])

    async def test_private_redirect_is_rejected_and_no_partial_written(self):
        response = self.Response([], headers={"Location": "http://127.0.0.1/secret"}, status=302)
        service = MusicService(session=self.Session(response))
        async def validate(url):
            if "127.0.0.1" in url:
                raise UnsafeURLError("private address")
            return url
        with tempfile.TemporaryDirectory() as directory, patch("ogmusic.service.validate_public_url", new=AsyncMock(side_effect=validate)):
            with self.assertRaises(UnsafeURLError):
                await service.download_audio(self.track(), directory)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
