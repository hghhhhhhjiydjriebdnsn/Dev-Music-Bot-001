"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import logging
from typing import Any, Dict, List, Union

from pyrogram.types import Message
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.phone import EditGroupCallTitle

from config import config
from core.queue import Queue

log = logging.getLogger("groups")

# ============================================================
#  GLOBAL STATE
# ============================================================
GROUPS: Dict[int, Dict[str, Any]] = {}


# ============================================================
#  GROUP STATE HELPERS
# ============================================================
def all_groups() -> List[int]:
    """Return a snapshot list of all chat_ids the bot is tracking."""
    return list(GROUPS.keys())


def set_default(chat_id: int) -> None:
    """Initialize default state for a chat (idempotent)."""
    GROUPS[chat_id] = {
        "is_playing": False,
        "now_playing": None,
        "stream_mode": config.STREAM_MODE,
        "admins_only": config.ADMINS_ONLY,
        "loop": False,
        "lang": config.LANGUAGE,
        "queue": Queue(maxsize=config.QUEUE_LIMIT or 20),
    }
    log.debug(f"Initialized group state for {chat_id}")


def get_group(chat_id: int) -> Dict[str, Any]:
    """Return group state, creating defaults if missing."""
    if chat_id not in GROUPS:
        set_default(chat_id)
    return GROUPS[chat_id]


def set_group(chat_id: int, **kwargs) -> None:
    """Update group state keys (auto-initializes if missing)."""
    if chat_id not in GROUPS:
        set_default(chat_id)
    for key, value in kwargs.items():
        GROUPS[chat_id][key] = value


# ============================================================
#  VC TITLE
# ============================================================
async def set_title(
    message_or_chat_id: Union[Message, int],
    title: str,
    **kw,
) -> None:
    """Set the voice chat title. Silently fails if the bot lacks permissions."""
    if isinstance(message_or_chat_id, Message):
        client = getattr(message_or_chat_id, "_client", None)
        chat_id = message_or_chat_id.chat.id
    elif isinstance(message_or_chat_id, int):
        client = kw.get("client")
        chat_id = message_or_chat_id
    else:
        log.warning(f"set_title: unsupported type {type(message_or_chat_id)}")
        return

    if client is None:
        log.warning("set_title: no client provided")
        return

    try:
        peer = await client.resolve_peer(chat_id)
        chat = await client.invoke(GetFullChannel(channel=peer))
        if not chat.full_chat.call:
            log.debug(f"set_title: no active call in {chat_id}")
            return
        await client.invoke(
            EditGroupCallTitle(call=chat.full_chat.call, title=title or "")
        )
    except Exception as e:
        log.debug(f"set_title failed for {chat_id}: {e}")


# ============================================================
#  QUEUE HELPERS
# ============================================================
def get_queue(chat_id: int) -> Queue:
    return get_group(chat_id)["queue"]


def clear_queue(chat_id: int) -> None:
    """Clear the queue for a chat (safe if chat is not tracked)."""
    if chat_id in GROUPS:
        GROUPS[chat_id]["queue"].clear()


def shuffle_queue(chat_id: int) -> Queue:
    """Shuffle the queue in place and return it."""
    return get_queue(chat_id).shuffle()