"""Stable integration exports for PIHU MUSIC."""
from .security import UnsafeURLError, validate_public_url
from .service import PROVIDERS, MusicService
from .models import Track
from . import service

async def download_audio(track, directory, max_bytes=50 * 1024 * 1024):
    return await service.download_audio(track, directory, max_bytes=max_bytes)

__all__ = ["service", "Track", "download_audio", "MusicService", "PROVIDERS", "UnsafeURLError", "validate_public_url"]
