"""
Music Player, Telegram Voice Chat Bot
Copyright (c) 2021-present Asm Safone <https://github.com/AsmSafone>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>
"""

import time
from lang import load
from config import config
from core.stream import app
from datetime import datetime
from pytgcalls import PyTgCalls
from traceback import format_exc
from pyrogram import Client, enums
from pyrogram.types import Message
from pytgcalls.types import Update
from typing import Union, Callable
from pyrogram.errors import UserAlreadyParticipant
from core.groups import get_group, all_groups, set_default


def register(func: Callable) -> Callable:
    async def decorator(client: Client, message: Message, *args):
        if message.chat.id not in all_groups():
            set_default(message.chat.id)
        return await func(client, message, *args)

    return decorator


def language(func: Callable) -> Callable:
    async def decorator(client, obj: Union[Message, int, Update], *args):
        try:
            if isinstance(obj, int):
                chat_id = obj
            elif isinstance(obj, Message):
                chat_id = obj.chat.id
            elif isinstance(obj, Update):
                chat_id = obj.chat_id
            group_lang = get_group(chat_id)["lang"]
        except BaseException:
            group_lang = config.LANGUAGE
        lang = load(group_lang)
        return await func(client, obj, lang)

    return decorator


def only_admins(func: Callable) -> Callable:
    async def decorator(client: Client, message: Message, *args):
        if message.from_user and (
            message.from_user.id
            in [
                admin.user.id
                async for admin in message.chat.get_members(
                    filter=enums.ChatMembersFilter.ADMINISTRATORS
                )
            ]
        ):
            return await func(client, message, *args)
        elif message.from_user and message.from_user.id in config.SUDOERS:
            return await func(client, message, *args)
        elif message.sender_chat and message.sender_chat.id == message.chat.id:
            return await func(client, message, *args)

    return decorator


def handle_error(func: Callable) -> Callable:
    """Report a safe error without granting privileges or joining unrelated chats."""
    from functools import wraps
    import logging

    @wraps(func)
    async def decorator(client, obj, *args):
        try:
            return await func(client, obj, *args)
        except Exception as exc:
            if getattr(exc, "handled", False):  # chat was already told (e.g. assistant banned)
                return
            # Do not print exception payloads: upstream URLs can contain credentials.
            logging.getLogger("ogmusic").error("%s failed (%s)", func.__name__, type(exc).__name__)
            if isinstance(obj, Message):
                await obj.reply_text("⚠️ PIHU MUSIC could not complete that request. Check the voice chat, assistant permissions, or try another song.")
    return decorator
