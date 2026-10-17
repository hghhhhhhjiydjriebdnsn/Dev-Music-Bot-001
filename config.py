"""
Music Player, Telegram Voice Chat Bot
Copyright (c) 2026-present DevXGhost <https://t.me/DevXGhost>

Licensed under the GNU Affero General Public License v3.0
See LICENSE file for details.
"""

import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("config")


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        log.warning(f"Invalid int for {key}, using default {default}")
        return default


class Config:
    def __init__(self) -> None:
        # ===== REQUIRED: Telegram API credentials =====
        self.API_ID: int = _env_int("API_ID", 0)
        self.API_HASH: str = (os.environ.get("API_HASH") or "").strip()
        self.SESSION: str = (os.environ.get("SESSION") or "").strip()
        self.BOT_TOKEN: str = (os.environ.get("BOT_TOKEN") or "").strip()

        # ===== Owner / Admins =====
        self.OWNER_ID: int = _env_int("OWNER_ID", 0)
        self.SUDOERS: list = [
            int(x) for x in os.environ.get("SUDOERS", "").split() if x.isdigit()
        ]
        if self.OWNER_ID and self.OWNER_ID not in self.SUDOERS:
            self.SUDOERS.append(self.OWNER_ID)

        # ===== Logs / Support =====
        self.LOG_CHANNEL: int = _env_int("LOG_CHANNEL", 0)
        self.SUPPORT_CHANNEL: str = os.environ.get("SUPPORT_CHANNEL", "").strip()
        self.SUPPORT_GROUP: str = os.environ.get("SUPPORT_GROUP", "").strip()

        # ===== Playback =====
        self.QUALITY: str = os.environ.get("QUALITY", "high").lower()
        self.STREAM_MODE: str = (
            "video"
            if os.environ.get("STREAM_MODE", "audio").lower() == "video"
            else "audio"
        )
        self.ADMINS_ONLY: bool = _env_bool("ADMINS_ONLY", False)
        self.DURATION_LIMIT: int = _env_int("DURATION_LIMIT", 3600)
        self.QUEUE_LIMIT: int = _env_int("QUEUE_LIMIT", 20)

        # ===== Commands =====
        raw_prefix = os.environ.get("PREFIX", "!").strip()
        self.PREFIXES: list = list(raw_prefix) if raw_prefix else ["!"]
        self.LANGUAGE: str = os.environ.get("LANGUAGE", "en").lower()

        # ===== Spotify =====
        self.SPOTIFY_CLIENT_ID: str = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
        self.SPOTIFY_CLIENT_SECRET: str = (os.environ.get("SPOTIFY_CLIENT_SECRET") or "").strip()
        self.SPOTIFY: bool = bool(self.SPOTIFY_CLIENT_ID and self.SPOTIFY_CLIENT_SECRET)

        # ===== Database =====
        self.DATABASE_URL: str = (os.environ.get("DATABASE_URL") or "").strip()
        self.MONGO_URI: str = (os.environ.get("MONGO_URI") or "").strip()

        # ===== Bot metadata =====
        self.BOT_USERNAME: str = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
        self.START_IMG_URL: str = os.environ.get("START_IMG_URL", "").strip()

        # ===== Upstream =====
        self.UPSTREAM_REPO: str = os.environ.get("UPSTREAM_REPO", "").strip()
        self.UPSTREAM_BRANCH: str = os.environ.get("UPSTREAM_BRANCH", "main").strip()

        # ===== Validation =====
        missing = []
        if not self.API_ID:
            missing.append("API_ID")
        if not self.API_HASH:
            missing.append("API_HASH")
        if not self.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not self.SESSION:
            missing.append("SESSION")

        if missing:
            log.critical(f"Missing required config values: {', '.join(missing)}")
            log.critical("Please set them in your .env file.")
            sys.exit(1)

        if not self.OWNER_ID:
            log.warning("OWNER_ID not set — SUDO commands may be unusable.")
        if not self.LOG_CHANNEL:
            log.warning("LOG_CHANNEL not set — errors won't be logged to a channel.")
        if self.STREAM_MODE == "video":
            log.info("STREAM_MODE=video enabled — note: video VC streaming requires more CPU.")
        if self.SPOTIFY:
            log.info("Spotify credentials detected — Spotify support enabled.")
        else:
            log.info("Spotify credentials missing — Spotify support disabled.")


config = Config()