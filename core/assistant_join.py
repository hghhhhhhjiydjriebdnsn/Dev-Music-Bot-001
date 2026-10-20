"""Make sure the assistant account is inside the group before playing.

Handles three real-world cases:
  1. assistant not in the group      -> bot creates an invite link, assistant joins
  2. group has "approve new members" -> assistant's join request is approved by the bot
  3. assistant is banned in the group -> bot unbans it if it can, otherwise the group
                                         gets a clear "please unban my assistant" message
"""
import asyncio
import html
import logging
import time
from datetime import datetime, timedelta

from core.fonts import sc

log = logging.getLogger("pihu.join")

_OK_TTL = 300  # seconds an "assistant is in the group" answer is trusted
_ok_until = {}


class AssistantUnavailable(Exception):
    """Assistant cannot serve this chat. The chat has ALREADY been told why."""
    handled = True


def forget(chat_id):
    for key in [k for k in _ok_until if k[0] == chat_id]:
        _ok_until.pop(key, None)


def _name(exc):
    return type(exc).__name__


def _label(assistant):
    name = html.escape(str(assistant.name or "Assistant"), quote=True)
    link = f'<a href="tg://user?id={assistant.user_id}">{name}</a>'
    if assistant.username:
        link += f" (@{html.escape(assistant.username)})"
    return link


async def _say(bot, chat_id, text):
    from pyrogram import enums
    try:
        await bot.send_message(chat_id, text, parse_mode=enums.ParseMode.HTML,
                               disable_web_page_preview=True)
    except Exception as exc:
        log.warning("could not notify chat: %s", _name(exc))


async def _status(bot, chat_id, user_id):
    """'member' | 'banned' | 'absent' | 'unknown'"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as exc:
        if _name(exc) in ("UserNotParticipant", "PeerIdInvalid"):
            return "absent"
        return "unknown"
    status = str(getattr(member.status, "name", member.status)).upper()
    if status == "BANNED":
        return "banned"
    if status == "LEFT":
        return "absent"
    if status == "RESTRICTED" and not getattr(member, "is_member", True):
        return "absent"
    return "member"


async def _unban(bot, chat_id, user_id):
    try:
        await bot.unban_chat_member(chat_id, user_id)
        return True
    except Exception as exc:
        log.info("unban failed: %s", _name(exc))
        return False


async def _approve(bot, chat_id, user_id):
    try:
        await bot.approve_chat_join_request(chat_id, user_id)
        return True
    except Exception as exc:
        log.info("approve failed: %s", _name(exc))
        return False


async def _join(bot, chat, assistant):
    """Returns 'ok' | 'banned' | 'request_failed' | 'no_link' | 'failed'."""
    uid, ub = assistant.user_id, assistant.app

    # A join request from an earlier attempt may still be waiting.
    if await _approve(bot, chat.id, uid):
        await asyncio.sleep(1)
        if await _status(bot, chat.id, uid) == "member":
            return "ok"

    targets = []
    try:
        invite = await bot.create_chat_invite_link(
            chat.id, name="assistant", member_limit=1,
            expire_date=datetime.utcnow() + timedelta(minutes=10))
        targets.append(invite.invite_link)
    except Exception as exc:
        log.info("invite link failed: %s", _name(exc))
    if getattr(chat, "username", None):
        targets.append(chat.username)
    if not targets:
        return "no_link"

    result = "failed"
    for target in targets:
        try:
            await ub.join_chat(target)
            return "ok"
        except Exception as exc:
            name = _name(exc)
            if name == "UserAlreadyParticipant":
                return "ok"
            if name == "UserBannedInChannel":
                return "banned"
            if name == "InviteRequestSent":
                # group needs approval -> the bot approves the assistant itself
                for _ in range(3):
                    if await _approve(bot, chat.id, uid):
                        return "ok"
                    await asyncio.sleep(1.5)
                result = "request_failed"
                continue
            if name == "FloodWait":
                result = "failed"
                continue
            log.info("join via %s failed: %s", "link" if "/" in str(target) else "username", name)
    return result


async def ensure_assistant(chat, assistant):
    """Return when the assistant is in `chat`, else tell the chat why and raise."""
    from core import assistants
    bot = assistants.BOT
    if bot is None or assistant is None:  # no separate bot account -> nothing to manage
        return
    key = (chat.id, assistant.user_id)
    if _ok_until.get(key, 0) > time.monotonic():
        return
    who = _label(assistant)

    state = await _status(bot, chat.id, assistant.user_id)
    if state == "member":
        _ok_until[key] = time.monotonic() + _OK_TTL
        return

    outcome = "banned" if state == "banned" else None
    if outcome == "banned" and await _unban(bot, chat.id, assistant.user_id):
        outcome = None  # bot lifted the ban itself
    if outcome is None:
        outcome = await _join(bot, chat, assistant)
        if outcome == "banned":  # ban only showed up on join: try to lift it once
            if await _unban(bot, chat.id, assistant.user_id):
                outcome = await _join(bot, chat, assistant)
    if outcome == "ok":
        _ok_until[key] = time.monotonic() + _OK_TTL
        return

    forget(chat.id)
    if outcome == "banned":
        await _say(bot, chat.id,
                   f"🚫 <b>{sc('my assistant is banned in this group')}</b>\n"
                   f"<blockquote>{who}\n<i>{sc('admins: please unban my assistant, then send /play again.')}</i></blockquote>")
    elif outcome == "request_failed":
        await _say(bot, chat.id,
                   f"⚠️ <b>{sc('assistant join request is pending')}</b>\n"
                   f"<blockquote>{who}\n<i>{sc('this group needs approval. give me the')}</i> <b>{sc('invite users')}</b> "
                   f"<i>{sc('admin right so i can approve it, or approve the assistant manually, then send /play again.')}</i></blockquote>")
    else:
        await _say(bot, chat.id,
                   f"⚠️ <b>{sc('assistant could not join')}</b>\n"
                   f"<blockquote>{who}\n<i>{sc('make me an admin with the')}</i> <b>{sc('invite users')}</b> "
                   f"<i>{sc('permission, or add the assistant manually, then send /play again.')}</i></blockquote>")
    raise AssistantUnavailable(outcome)
