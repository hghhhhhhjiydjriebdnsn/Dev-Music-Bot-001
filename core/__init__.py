"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

# ============================================================
#  CORE EXPORTS
#  Central import hub for the rest of the project.
#
#  Usage:
#      from core import app, pytgcalls, get_group, ...
#
#  NOTE: Keep imports ordered alphabetically within each group.
#        Avoid circular imports — submodules should import from
#        other submodules directly, NOT from `core`.
# ============================================================

# --- Song ----------------------------------------------------
from core.song import Song

# --- Admins --------------------------------------------------
from core.admins import is_sudo, is_admin

# --- Stream (Pyrogram + PyTgCalls setup) ---------------------
from core.stream import (
    app,
    ytdl,
    safone,
    pytgcalls,
    start_stream,
)

# --- Groups (state + queue management) -----------------------
from core.groups import (
    all_groups,
    clear_queue,
    get_group,
    get_queue,
    set_default,
    set_group,
    set_title,
    shuffle_queue,
)

# --- Funcs (utilities: search, formats, etc.) ----------------
from core.funcs import (
    check_yt_url,
    delete_messages,
    extract_args,
    generate_cover,
    get_spotify_playlist,
    get_youtube_playlist,
    search,
)

# ============================================================
#  NEW HELPERS (to be implemented in core/funcs.py)
# ============================================================
# These will be added as we refactor `core/funcs.py`.
# They are listed here so the rest of the codebase can
# import them from `core` once available.
#
# from core.funcs import (
#     small_caps,           # Convert text to Small Caps Unicode
#     send_rich_message,    # Send Bot API 10.1+ Rich Message
#     rich_button_row,      # Build <tg-button-row> HTML
#     premium_emoji,        # <tg-emoji> wrapper for Premium emoji
# )
# ============================================================

__all__ = [
    # Song
    "Song",
    # Admins
    "is_sudo",
    "is_admin",
    # Stream
    "app",
    "ytdl",
    "safone",
    "pytgcalls",
    "start_stream",
    # Groups
    "all_groups",
    "clear_queue",
    "get_group",
    "get_queue",
    "set_default",
    "set_group",
    "set_title",
    "shuffle_queue",
    # Funcs
    "check_yt_url",
    "delete_messages",
    "extract_args",
    "generate_cover",
    "get_spotify_playlist",
    "get_youtube_playlist",
    "search",
]