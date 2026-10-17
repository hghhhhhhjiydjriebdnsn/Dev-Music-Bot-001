"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import os
import json
import html
import asyncio
import logging
from shutil import which
from datetime import timedelta
from typing import Dict, Tuple, Union, Optional

import aiohttp
from pyrogram.types import User, Message

log = logging.getLogger("song")

# ============================================================
#  CONSTANTS
# ============================================================
DEFAULT_THUMB = "https://telegra.ph/file/820cac7cb7b1a025542e2.jpg"
YT_DLP_TIMEOUT = 30  # seconds
URL_CHECK_TIMEOUT = 10  # seconds
MAX_RETRIES = 5

# Whitelisted keys when constructing from dict (import/export)
_ALLOWED_KEYS = {
    "title", "duration", "thumb", "remote", "source",
    "headers", "parsed", "requested_by",
}


class Song:
    """
    Represents a song to be streamed.

    Two construction modes:
      - Song("https://youtu.be/...", message) → call `await parse()` first
      - Song({"title": ..., "source": ...}, message) → ready to stream
    """

    def __init__(self, link: Union[str, dict], request_msg: Message) -> None:
        self.request_msg: Message = request_msg
        self.requested_by: Optional[User] = getattr(request_msg, "from_user", None)
        self._retries: int = 0

        if isinstance(link, str):
            # Unparsed — must call parse() before streaming
            self.title: Optional[str] = None
            self.duration: Optional[str] = None
            self.thumb: Optional[str] = None
            self.remote: Optional[str] = None
            self.source: str = link
            self.headers: Optional[dict] = None
            self.parsed: bool = False

        elif isinstance(link, dict):
            # Pre-parsed — trusted dict from export/import or internal
            self.parsed = True
            self.duration = "N/A"
            self.headers = None
            self.thumb = DEFAULT_THUMB
            self.title = "Unknown"
            self.remote = None
            self.source = ""
            for key, value in link.items():
                if key in _ALLOWED_KEYS:
                    setattr(self, key, value)
        else:
            raise TypeError(f"Song() expects str or dict, got {type(link).__name__}")

    # --------------------------------------------------------
    #  PARSE
    # --------------------------------------------------------
    async def parse(self) -> Tuple[bool, str]:
        """
        Resolve the source via yt-dlp and validate remote URL + thumbnail.
        Returns (True, "PARSED") on success, (False, reason) on failure.
        """
        if self.parsed:
            return (True, "ALREADY_PARSED")

        if not which("yt-dlp"):
            log.error("yt-dlp binary not found in PATH")
            return (False, "YT_DLP_NOT_INSTALLED")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                video = await self._extract_via_ytdlp()
            except asyncio.TimeoutError:
                log.warning(f"yt-dlp timeout (attempt {attempt}/{MAX_RETRIES})")
                continue
            except Exception as e:
                log.warning(f"yt-dlp error (attempt {attempt}/{MAX_RETRIES}): {e}")
                continue

            if not video:
                continue

            remote_url = video.get("url")
            thumbnail = video.get("thumbnail") or DEFAULT_THUMB
            headers = video.get("http_headers") or {}

            if not remote_url:
                log.warning(f"No remote URL in yt-dlp output (attempt {attempt})")
                continue

            # Validate both URLs concurrently
            remote_ok, thumb_ok = await asyncio.gather(
                self.check_remote_url(remote_url, headers),
                self.check_remote_url(thumbnail, headers),
            )

            if remote_ok:
                self.title = self._escape(video.get("title") or "Unknown")
                self.duration = self._format_duration(video.get("duration"))
                self.thumb = thumbnail
                self.remote = remote_url
                self.headers = headers
                self.parsed = True
                log.info(f"Parsed: {self.title} ({self.duration})")
                return (True, "PARSED")

            log.warning(f"URL check failed (attempt {attempt}/{MAX_RETRIES})")

        return (False, "MAX_RETRY_LIMIT_REACHED")

    async def _extract_via_ytdlp(self) -> Optional[dict]:
        """Run yt-dlp as a subprocess and return the parsed JSON."""
        cmd = [
            "yt-dlp",
            "--print-json",
            "--skip-download",
            "--no-warnings",
            "-f", "bestaudio/best",
            self.source,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            out, err = await asyncio.wait_for(
                process.communicate(), timeout=YT_DLP_TIMEOUT
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            raise

        if process.returncode != 0:
            log.warning(f"yt-dlp exit {process.returncode}: {err.decode(errors='ignore')[:200]}")
            return None

        try:
            return json.loads(out.decode(errors="ignore"))
        except json.JSONDecodeError as e:
            log.warning(f"yt-dlp JSON decode failed: {e}")
            return None

    # --------------------------------------------------------
    #  URL VALIDATION
    # --------------------------------------------------------
    @staticmethod
    async def check_remote_url(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = URL_CHECK_TIMEOUT,
    ) -> bool:
        """Quick HTTP HEAD/GET check that the URL is alive."""
        if not url:
            return False

        try:
            timeout_cfg = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
                # Try HEAD first (cheap)
                try:
                    async with session.head(
                        url, headers=headers, allow_redirects=True
                    ) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    pass

                # Fallback to GET (streamed — we don't download body)
                try:
                    async with session.get(
                        url, headers=headers, allow_redirects=True
                    ) as resp:
                        return resp.status == 200
                except Exception:
                    return False
        except Exception as e:
            log.debug(f"URL check failed for {url[:80]}: {e}")
            return False

    # --------------------------------------------------------
    #  HELPERS
    # --------------------------------------------------------
    @staticmethod
    def _format_duration(seconds: Optional[Union[int, float]]) -> str:
        """Format duration; handle None / 0 (live streams)."""
        try:
            secs = int(seconds) if seconds else 0
        except (TypeError, ValueError):
            return "N/A"
        if secs <= 0:
            return "Live / N/A"
        return str(timedelta(seconds=secs))

    @staticmethod
    def _escape(title: str) -> str:
        """Escape HTML and Markdown special chars for safe rendering."""
        if not title:
            return "Unknown"
        # HTML escape first
        title = html.escape(title, quote=False)
        # Markdown V1 escape (for legacy send_message calls)
        for ch in ("*", "_", "`", "~"):
            title = title.replace(ch, f"\\{ch}")
        return title

    # --------------------------------------------------------
    #  SERIALIZATION
    # --------------------------------------------------------
    def to_dict(self) -> Dict[str, Optional[str]]:
        """Serialize for export/import."""
        return {
            "title": self.title,
            "source": self.source,
            "duration": self.duration,
            "thumb": self.thumb,
            "remote": self.remote,
            "headers": self.headers,
            "parsed": self.parsed,
        }

    # --------------------------------------------------------
    #  DEBUG
    # --------------------------------------------------------
    def __repr__(self) -> str:
        return (
            f"<Song title={self.title!r} source={self.source[:60]!r} "
            f"duration={self.duration!r} parsed={self.parsed}>"
        )