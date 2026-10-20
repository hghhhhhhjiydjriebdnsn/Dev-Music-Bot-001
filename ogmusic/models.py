"""Provider-neutral music result models and normalization helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable
from urllib.parse import urlencode


def duration_seconds(value: Any) -> int:
    """Convert common provider duration forms to non-negative whole seconds."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    try:
        parts = [int(part) for part in text.split(":")]
    except (TypeError, ValueError):
        return 0
    if not 2 <= len(parts) <= 3 or any(part < 0 for part in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def format_duration(seconds: Any) -> str:
    seconds = duration_seconds(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "").strip()
    return str(value).strip()


def normalize_artists(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        value = value.get("primary_artists") or value.get("artists") or value.get("artist") or value.get("name")
        if isinstance(value, str):
            return value.strip()
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return ", ".join(text for item in value if (text := _text(item)))
    return _text(value)


def normalize_image(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[-1] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("link")
    result = _text(value)
    return result or None


@dataclass(frozen=True, slots=True)
class Track:
    title: str
    artists: str
    duration: int
    thumbnail: str | None
    stream_url: str
    source_url: str
    provider: str

    def to_song_dict(self) -> dict[str, Any]:
        """Return the compatibility shape used by the existing song UI."""
        return {
            "title": self.title,
            "duration": format_duration(self.duration),
            "thumb": self.thumbnail,
            "source": self.source_url,
            "remote": self.stream_url,
            "parsed": True,
            "provider": self.provider,
            "artists": self.artists,
            "audio_only": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Track":
        if not isinstance(value, dict):
            raise TypeError("Track.from_dict expects a dictionary")
        return cls(
            title=_text(value.get("title")),
            artists=normalize_artists(value.get("artists")),
            duration=duration_seconds(value.get("duration")),
            thumbnail=normalize_image(value.get("thumbnail", value.get("thumb"))),
            stream_url=_text(value.get("stream_url", value.get("remote"))),
            source_url=_text(value.get("source_url", value.get("source"))),
            provider=_text(value.get("provider")),
        )

    @staticmethod
    def api_query_url(provider: str, query: str) -> str:
        """Construct stable source/API URLs without retaining transient search state."""
        if provider == "jiosaavan":
            return "https://jiosaavan-seven.vercel.app/song/?" + urlencode({"query": query})
        if provider in {"song_downloader", "suryansh"}:
            base = {
                "song_downloader": "https://song-downloader-three.vercel.app/search",
                "suryansh": "https://suryansh-music-search-download-api.vercel.app/search",
            }[provider]
            return base + "?" + urlencode({"song": query})
        raise ValueError(f"Unknown music provider: {provider}")
