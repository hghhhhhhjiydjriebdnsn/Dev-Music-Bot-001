"""Standalone async music search/download provider package."""
from .models import Track
from .service import MusicService

music_service = MusicService()
service = music_service

__all__ = ["MusicService", "Track", "music_service", "service"]
