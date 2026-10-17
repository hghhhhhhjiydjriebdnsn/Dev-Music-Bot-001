"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import logging
from pyrogram import enums
from pyrogram.types import Message

from config import config

log = logging.getLogger("admins")


async def is_sudo(message: Message) -> bool:
    """Return True if the sender is in SUDOERS or is the OWNER."""
    user = message.from_user
    if not user:
        return False
    if user.id == config.OWNER_ID:
        return True
    return user.id in config.SUDOERS


async def is_admin(message: Message) -> bool:
    """Return True if the sender is an admin of the chat or a sudo user."""
    # Anonymous admin (posting as the group)
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True

    user = message.from_user
    if not user:
        return False

    # Owner/sudo always have admin privileges
    if user.id == config.OWNER_ID or user.id in config.SUDOERS:
        return True

    try:
        member = await message.chat.get_member(user.id)
        return member.status in (
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
        )
    except Exception as e:
        log.debug(f"is_admin check failed for {user.id} in {message.chat.id}: {e}")
        return False