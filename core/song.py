"""
Music Player, Telegram Voice Chat Bot
Copyright (c) 2021-present Asm Safone <https://github.com/AsmSafone>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>
"""

import json
import asyncio
from shlex import quote
from subprocess import PIPE
from datetime import timedelta
from aiohttp import ClientSession
from pyrogram.types import User, Message
from typing import Dict, Tuple, Union, Optional


class Song:
    def __init__(self, link: Union[str, dict], request_msg: Message) -> None:
        self.title = None
        self.duration = "N/A"
        self.thumb = None
        self.remote = None
        self.source = link if isinstance(link, str) else link.get("source", "")
        self.headers = None
        self.parsed = False
        self._retries = 0
        if isinstance(link, dict):
            # Whitelist fields: imported or remote JSON must not override methods.
            for key in ("title", "duration", "thumb", "remote", "source", "headers", "provider", "artists", "audio_only"):
                if key in link:
                    setattr(self, key, link[key])
            self.parsed = bool(link.get("parsed", True) and self.remote)
        self.request_msg = request_msg
        self.requested_by = request_msg.from_user

    async def parse(self) -> Tuple[bool, str]:
        if self.parsed:
            return True, "ALREADY_PARSED"
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.source)
        api_hosts = {"jiosaavan-seven.vercel.app", "song-downloader-three.vercel.app", "suryansh-music-search-download-api.vercel.app"}
        if parsed.hostname in api_hosts:
            from ogmusic.providers import service
            values = parse_qs(parsed.query)
            query = (values.get("query") or values.get("song") or [self.title or ""])[0]
            tracks = await service.search(query, limit=5)
            if not tracks:
                return False, "API_TRACK_UNAVAILABLE"
            track = next((t for t in tracks if t.title == self.title), tracks[0])
            for key, value in track.to_song_dict().items():
                if key in {"title", "duration", "thumb", "remote", "source", "headers", "provider", "artists", "audio_only", "parsed"}:
                    setattr(self, key, value)
            return True, "PARSED"
        # Preserve explicit YouTube/media URL extraction and legacy playlist items.
        for _ in range(3):
            process = await asyncio.create_subprocess_exec(
                "yt-dlp", "--dump-single-json", "--skip-download", "--no-playlist",
                "--socket-timeout", "15", "-f", "best", "--", self.source,
                stdout=PIPE, stderr=PIPE,
            )
            try:
                out, _ = await asyncio.wait_for(process.communicate(), timeout=60)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                continue
            try:
                video = json.loads(out.decode())
                remote = video.get("url")
                if not remote:
                    continue
                self.title = video.get("title", "Unknown Track")
                self.duration = str(timedelta(seconds=int(video.get("duration") or 0)))
                self.thumb = video.get("thumbnail")
                self.remote = remote
                self.headers = video.get("http_headers")
                self.parsed = True
                return True, "PARSED"
            except (ValueError, TypeError):
                continue
        return False, "TRACK_UNAVAILABLE"

    @staticmethod
    async def check_remote_url(path, headers=None):
        try:
            async with ClientSession() as session:
                async with session.get(path, timeout=5, headers=headers) as response:
                    return response.status in (200, 206)
        except Exception:
            return False

    @staticmethod
    def _escape(title):
        return title

    def to_dict(self):
        # Save a re-resolvable source, never a signed CDN token or local path.
        return {"title": self.title, "source": self.source}
