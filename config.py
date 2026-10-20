"""PIHU MUSIC configuration. Never put credentials in this file.
Derived from MusicPlayer, copyright Asm Safone, AGPL-3.0-or-later.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    def __init__(self):
        raw_id = os.getenv("API_ID", "").strip()
        self.API_ID = int(raw_id) if raw_id.isdigit() else 0
        self.API_HASH = os.getenv("API_HASH", "").strip()
        self.SESSION = os.getenv("SESSION", "").strip()
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip() or None
        self.SUDOERS = [int(uid) for uid in os.getenv("SUDOERS", "").split() if uid.isdigit()]
        self.SPOTIFY = False
        self.SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
        self.SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.QUALITY = os.getenv("QUALITY", "high").lower()
        if self.QUALITY not in {"low", "medium", "high"}:
            self.QUALITY = "high"
        self.PREFIXES = os.getenv("PREFIX", "/ !").split() or ["/"]
        self.LANGUAGE = os.getenv("LANGUAGE", "en").lower()
        self.STREAM_MODE = "video" if os.getenv("STREAM_MODE", "audio").lower() == "video" else "audio"
        self.ADMINS_ONLY = env_bool("ADMINS_ONLY")
        self.BOT_NAME = "PIHU MUSIC"
        self.BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
        self.OWNER_USERNAME = os.getenv("OWNER_USERNAME", "").strip().lstrip("@")
        self.SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()

    def validate(self):
        missing = [name for name in ("API_ID", "API_HASH", "SESSION") if not getattr(self, name)]
        if missing:
            raise SystemExit("Missing required environment settings: " + ", ".join(missing) + ". Copy sample.env to .env and fill your own credentials.")


config = Config()
