"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import time
import logging
from datetime import datetime
from traceback import format_exc
from typing import Union, Callable

from pyrogram import Client, enums
from pyrogram.types import Message
from pytgcalls import PyTgCalls
from pytgcalls.types import Update

from config import config
from lang import load
from core.groups import get_group, all_groups, set_default

log = logging.getLogger("decorators")


# ============================================================
#  REGISTER — ensure group state exists before handler runs
# ============================================================
def register(func: Callable) -> Callable:
    async def decorator(client: Client, message: Message, *args):
        if message.chat.id not in all_groups():
            set_default(message.chat.id)
        return await func(client, message, *args)

    return decorator


# ============================================================
#  LANGUAGE — inject `lang` dict based on chat's language
# ============================================================
def language(func: Callable) -> Callable:
    async def decorator(client, obj: Union[Message, int, Update], *args):
        chat_id = None
        if isinstance(obj, int):
            chat_id = obj
        elif isinstance(obj, Message):
            chat_id = obj.chat.id
        elif isinstance(obj, Update):
            chat_id = obj.chat_id

        try:
            group_lang = get_group(chat_id)["lang"] if chat_id else config.LANGUAGE
        except Exception:
            group_lang = config.LANGUAGE

        lang = load(group_lang)
        return await func(client, obj, lang, *args)

    return decorator


# ============================================================
#  ONLY ADMINS — allow group admins + sudoers + anonymous admins
# ============================================================
_ADMIN_CACHE: dict = {}  # chat_id -> (timestamp, set_of_user_ids)
_ADMIN_CACHE_TTL = 300  # 5 minutes


async def _fetch_admin_ids(chat) -> set:
    """Fetch admin user IDs, cached for ADMIN_CACHE_TTL."""
    chat_id = chat.id
    now = time.time()

    cached = _ADMIN_CACHE.get(chat_id)
    if cached and (now - cached[0]) < _ADMIN_CACHE_TTL:
        return cached[1]

    admins: set = set()
    try:
        async for member in chat.get_members(
            filter=enums.ChatMembersFilter.ADMINISTRATORS
        ):
            if member.user:
                admins.add(member.user.id)
    except Exception as e:
        log.debug(f"Failed to fetch admins for {chat_id}: {e}")

    _ADMIN_CACHE[chat_id] = (now, admins)
    return admins


def only_admins(func: Callable) -> Callable:
    async def decorator(client: Client, message: Message, *args):
        # Anonymous admin (posting as the group itself)
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return await func(client, message, *args)

        user = message.from_user
        if not user:
            return  # No user context

        # Sudo users (owner included)
        if user.id in config.SUDOERS:
            return await func(client, message, *args)

        # Group admins (cached)
        admin_ids = await _fetch_admin_ids(message.chat)
        if user.id in admin_ids:
            return await func(client, message, *args)

        # Not an admin — silently return (or notify)
        log.debug(f"User {user.id} denied admin-only command in {message.chat.id}")
        return

    return decorator


# ============================================================
#  HANDLE ERROR — log exceptions + send crash log to owner/log channel
# ============================================================
def _extract_chat_id(obj: Union[int, Message, Update]) -> Union[int, None]:
    if isinstance(obj, int):
        return obj
    if isinstance(obj, Message):
        return obj.chat.id if obj.chat else None
    if isinstance(obj, Update):
        return getattr(obj, "chat_id", None)
    return None


def _get_pyro_client(client) -> Union[Client, None]:
    """Extract the underlying Pyrogram Client from any wrapper."""
    if isinstance(client, Client):
        return client
    if isinstance(client, PyTgCalls):
        # PyTgCalls 2.x internal
        try:
            return client._app._bind_client._app
        except AttributeError:
            return None
    return None


def handle_error(func: Callable) -> Callable:
    async def decorator(client, obj, *args):
        try:
            return await func(client, obj, *args)
        except Exception:
            log.exception(f"Unhandled error in {func.__name__}")
            await _send_error_report(client, obj, func.__name__)

    return decorator


async def _send_error_report(client, obj, func_name: str) -> None:
    """Best-effort error report. Must never raise."""
    try:
        pyro_client = _get_pyro_client(client)
        if pyro_client is None:
            return

        chat_id = _extract_chat_id(obj)
        error_id = int(time.time())
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tb = format_exc()[-3500:]  # cap length

        # Get chat info (safe)
        chat_title = "N/A"
        chat_link = ""
        if chat_id:
            try:
                chat = await pyro_client.get_chat(chat_id)
                chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "N/A")
                # Build a link only if supergroup/channel
                username = getattr(chat, "username", None)
                if username:
                    chat_link = f"https://t.me/{username}"
            except Exception:
                pass

        report = (
            "-------- CRASH LOG --------\n"
            f"<b>ID:</b> <code>{error_id}</code>\n"
            f"<b>Function:</b> <code>{func_name}</code>\n"
            f"<b>Chat:</b> <code>{chat_id}</code> ({chat_title})\n"
            f"<b>Date:</b> <code>{date}</code>\n"
            f"<b>Traceback:</b>\n<code>{tb}</code>\n"
            "-------- END --------"
        )

        # Try to notify the chat first
        try:
            lang = load(get_group(chat_id)["lang"] if chat_id else config.LANGUAGE)
            await pyro_client.send_message(
                chat_id, lang.get("errorMessage", "⚠️ An error occurred.")
            )
        except Exception:
            pass

        # Send report to owner, log channel, or first sudo
        targets = []
        if config.OWNER_ID:
            targets.append(config.OWNER_ID)
        if config.LOG_CHANNEL:
            targets.append(config.LOG_CHANNEL)
        if not targets and config.SUDOERS:
            targets.append(config.SUDOERS[0])

        for target in targets:
            try:
                await pyro_client.send_message(
                    target,
                    report,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.error(f"Failed to send crash report to {target}: {e}")

    except Exception:
        # Absolute last resort — never let the error handler raise
        log.exception("Crash report failed")