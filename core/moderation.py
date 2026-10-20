"""Safe, modest Telegram group administration and welcome controls.

Register with ``register_moderation(client)`` before the public UI handlers.
Moderation and welcome settings are stored in a local SQLite database; music
queues remain owned by ``core.groups`` and are intentionally not persisted.
"""
from __future__ import annotations

import asyncio
import html
import os
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

_DB_LOCK = threading.RLock()
_PENDING_TTL = 180
_PENDING_LIMIT = 300
_PENDING = OrderedDict()
_HYDRATED = set()
_ACTIONS = {"ban", "kick", "unban", "muteuser", "unmuteuser"}


def _db_path():
    return Path(os.environ.get("DATA_DIR", "data")).expanduser() / "moderation.sqlite3"


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS moderation_settings (
        chat_id INTEGER PRIMARY KEY,
        admins_only INTEGER NOT NULL DEFAULT 0,
        loop_enabled INTEGER NOT NULL DEFAULT 0,
        welcome_enabled INTEGER NOT NULL DEFAULT 0,
        welcome_text TEXT NOT NULL DEFAULT 'Welcome {mention} to {chat}!'
    )""")
    return conn


def get_settings(chat_id):
    """Return a copy of persistent settings for a group."""
    with _DB_LOCK, _connect() as conn:
        from config import config
        conn.execute("INSERT OR IGNORE INTO moderation_settings(chat_id, admins_only) VALUES (?, ?)", (int(chat_id), int(bool(config.ADMINS_ONLY))))
        row = conn.execute("SELECT admins_only, loop_enabled, welcome_enabled, welcome_text FROM moderation_settings WHERE chat_id=?", (int(chat_id),)).fetchone()
    settings = {"admins_only": bool(row[0]), "loop": bool(row[1]), "welcome_enabled": bool(row[2]), "welcome_text": row[3]}
    # Restore panel-controlled playback preferences once per process/chat.
    with _DB_LOCK:
        if int(chat_id) not in _HYDRATED:
            try:
                from core.groups import set_group
                set_group(int(chat_id), admins_only=settings["admins_only"], loop=settings["loop"])
                _HYDRATED.add(int(chat_id))
            except Exception:
                pass
    return settings


def update_settings(chat_id, **values):
    allowed = {"admins_only", "loop", "welcome_enabled", "welcome_text"}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError("Unsupported settings: " + ", ".join(sorted(unknown)))
    settings = get_settings(chat_id)
    settings.update(values)
    with _DB_LOCK, _connect() as conn:
        conn.execute("""INSERT INTO moderation_settings(chat_id, admins_only, loop_enabled, welcome_enabled, welcome_text)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET admins_only=excluded.admins_only,
            loop_enabled=excluded.loop_enabled, welcome_enabled=excluded.welcome_enabled, welcome_text=excluded.welcome_text""",
            (int(chat_id), int(settings["admins_only"]), int(settings["loop"]), int(settings["welcome_enabled"]), settings["welcome_text"]))
    # Reflect persisted playback toggles into the existing in-memory group state.
    try:
        from core.groups import set_group
        set_group(int(chat_id), admins_only=settings["admins_only"], loop=settings["loop"])
    except Exception:
        pass
    return settings


def _is_group(message):
    chat = getattr(message, "chat", None)
    typ = getattr(chat, "type", None)
    return getattr(typ, "value", typ) in ("group", "supergroup") or getattr(chat, "type", None) in ("group", "supergroup")


async def _is_admin_or_sudo(client, chat_id, user):
    if not user:
        return False
    from config import config
    if user.id in getattr(config, "SUDOERS", ()):
        return True
    try:
        member = await client.get_chat_member(chat_id, user.id)
        status = getattr(member, "status", None)
        value = getattr(status, "value", status)
        return value in ("owner", "administrator", "creator")
    except Exception:
        return False


def _parse_force_channel():
    value = os.environ.get("FORCE_CHANNEL", "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value if value.startswith("@") else "@" + value


async def _force_member(client, user_id):
    channel = _parse_force_channel()
    if channel is None:
        return True
    try:
        member = await client.get_chat_member(channel, user_id)
        status = getattr(member, "status", None)
        value = getattr(status, "value", status)
        if value in ("member", "administrator", "owner", "creator"):
            return True
        if value == "restricted":
            return bool(getattr(member, "is_member", False))
        return False
    except Exception:
        # Fail closed: unknown membership is not treated as a subscription.
        return False


def _force_url():
    url = os.environ.get("FORCE_CHANNEL_URL", "").strip()
    if url.startswith(("https://", "http://")):
        return url
    channel = _parse_force_channel()
    if isinstance(channel, str) and channel.startswith("@"):
        return "https://t.me/" + channel[1:]
    return ""


def _token(payload):
    now = time.monotonic()
    for key, item in list(_PENDING.items()):
        if item["expires"] <= now:
            _PENDING.pop(key, None)
    value = secrets.token_urlsafe(7)
    _PENDING[value] = {**payload, "expires": now + _PENDING_TTL}
    while len(_PENDING) > _PENDING_LIMIT:
        _PENDING.popitem(last=False)
    return value


def _target_from(message, argument):
    reply = getattr(message, "reply_to_message", None)
    if reply and getattr(reply, "from_user", None):
        user = reply.from_user
        return int(user.id), (getattr(user, "first_name", None) or str(user.id))
    raw = (argument or "").strip().split()[0] if (argument or "").strip() else ""
    if raw.startswith("@"):
        return None, None
    try:
        return int(raw), raw
    except (TypeError, ValueError):
        return None, None


async def _protected_target(client, chat_id, target_id):
    """True when target is self, bot, or a current group admin/owner."""
    try:
        me = await client.get_me()
        if int(target_id) == int(me.id):
            return True
    except Exception:
        return True  # Can't establish bot identity safely; refuse destructive actions.
    try:
        member = await client.get_chat_member(chat_id, target_id)
        status = getattr(member, "status", None)
        value = getattr(status, "value", status)
        return value in ("owner", "creator", "administrator")
    except Exception:
        # If Telegram cannot verify status, refuse rather than risk touching an admin.
        return True


async def _bot_can_restrict(client, chat_id):
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
        status = getattr(member, "status", None)
        value = getattr(status, "value", status)
        if value not in ("owner", "creator", "administrator"):
            return False
        if value in ("owner", "creator"):
            return True
        return bool(getattr(member, "privileges", None) and getattr(member.privileges, "can_restrict_members", False))
    except Exception:
        return False


def _command_arg(message):
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _panel_markup(chat_id, settings):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎚 Admins only: {'ON' if settings['admins_only'] else 'OFF'}", callback_data=f"ogm:t:admins_only:{chat_id}")],
        [InlineKeyboardButton(f"🔁 Loop: {'ON' if settings['loop'] else 'OFF'}", callback_data=f"ogm:t:loop:{chat_id}")],
        [InlineKeyboardButton(f"👋 Welcome: {'ON' if settings['welcome_enabled'] else 'OFF'}", callback_data=f"ogm:t:welcome_enabled:{chat_id}")],
    ])


def _manage_markup(token):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛔ Ban", callback_data=f"ogm:m:ban:{token}"), InlineKeyboardButton("👢 Kick", callback_data=f"ogm:m:kick:{token}")],
        [InlineKeyboardButton("🔇 Mute", callback_data=f"ogm:m:muteuser:{token}"), InlineKeyboardButton("🔊 Unmute", callback_data=f"ogm:m:unmuteuser:{token}")],
        [InlineKeyboardButton("♻️ Unban", callback_data=f"ogm:m:unban:{token}")],
    ])


async def _reply(message, text, **kwargs):
    """Try the project's premium-aware sender; keep a plain Pyrogram fallback."""
    try:
        from core.premium import send_text
        return await send_text(message, text, **kwargs)
    except (ImportError, AttributeError, TypeError):
        return await message.reply_text(text, **kwargs)


def register_moderation(client):
    """Register moderation handlers. Call before ``core.ui.register_ui``."""
    from pyrogram import enums, filters
    from pyrogram.handlers import CallbackQueryHandler, MessageHandler
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from config import config

    async def style_buttons(message, markup):
        if not getattr(config, "BOT_TOKEN", None) or not message or not markup:
            return
        try:
            from core.ui import apply_button_style
            await apply_button_style(message, markup)
        except Exception:
            pass

    async def gate(_, message):
        if not message.from_user:
            return
        if _is_group(message):
            get_settings(message.chat.id)
        text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
        parsed = getattr(message, "command", None)
        cmd = str(parsed[0]).split("@", 1)[0].lower() if parsed else (text.split(maxsplit=1)[0].split("@", 1)[0].lstrip("/!.").lower() if text else "")
        if cmd not in {"play", "p", "search", "song", "download"}:
            return
        if await _force_member(client, message.from_user.id):
            return
        url = _force_url()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Join channel", url=url)]]) if url else None
        warning = "Join the configured channel before using music search or playback commands."
        if not getattr(config, "BOT_TOKEN", None) and _force_url():
            warning += "\nJoin: " + _force_url()
        await _reply(message, warning, reply_markup=keyboard if getattr(config, "BOT_TOKEN", None) else None)
        raise _stop_handler()

    # Pyrogram StopPropagation has different locations across versions. A local
    # exception avoids catching any unrelated errors and the public guard below
    # converts it to the framework exception.
    class _GateRejected(Exception):
        pass

    async def force_gate(_, message):
        try:
            await gate(_, message)
        except _GateRejected:
            from pyrogram import StopPropagation
            raise StopPropagation

    async def force_callback(_, query):
        data = getattr(query, "data", "") or ""
        if not (data.startswith("ogs:") or data.startswith("ogc:d:")):
            return
        if getattr(query, "message", None) and _is_group(query.message):
            get_settings(query.message.chat.id)
        user = getattr(query, "from_user", None)
        if user and await _force_member(client, user.id):
            return
        await query.answer("Join the configured channel to use music buttons.", show_alert=True)
        from pyrogram import StopPropagation
        raise StopPropagation

    async def admin_check(message):
        if not _is_group(message):
            await _reply(message, "This command is available in groups only.")
            return False
        if not await _is_admin_or_sudo(client, message.chat.id, message.from_user):
            await _reply(message, "Group administrators or configured sudo users only.")
            return False
        return True

    async def show_panel(message):
        settings = get_settings(message.chat.id)
        text = ("<b>Group control panel</b>\nToggle playback access, loop, and welcome settings below.\n"
                "Welcome text: use <code>/setwelcome text</code>; toggle with <code>/welcome on|off</code>.")
        keyboard = _panel_markup(message.chat.id, settings)
        if not getattr(config, "BOT_TOKEN", None):
            await _reply(message, text + "\n\nUserbot mode: inline keyboards may not work; use /welcome and /setwelcome commands.", parse_mode=enums.ParseMode.HTML)
            return
        try:
            sent = await _reply(message, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
            await style_buttons(sent, keyboard)
        except Exception:
            fallback = text + ("\n\nUserbot mode: inline keyboards may not work; use /welcome and /setwelcome commands." if not getattr(config, "BOT_TOKEN", None) else "")
            await _reply(message, fallback)

    async def panel(_, message):
        if await admin_check(message):
            await show_panel(message)

    async def welcome_toggle(_, message):
        if not await admin_check(message):
            return
        arg = _command_arg(message).lower()
        if arg not in ("on", "off"):
            await _reply(message, "Usage: /welcome on|off")
            return
        settings = update_settings(message.chat.id, welcome_enabled=(arg == "on"))
        await _reply(message, "Welcome messages enabled." if settings["welcome_enabled"] else "Welcome messages disabled.")

    async def setwelcome(_, message):
        if not await admin_check(message):
            return
        text = _command_arg(message)
        if not text:
            await _reply(message, "Usage: /setwelcome text (placeholders: {mention}, {name}, {chat})")
            return
        if len(text) > 1000:
            await _reply(message, "Welcome text is limited to 1000 characters.")
            return
        update_settings(message.chat.id, welcome_text=text)
        await _reply(message, "Welcome message saved. Enable it with /welcome on.")

    async def welcome_new_members(_, message):
        if not _is_group(message):
            return
        settings = get_settings(message.chat.id)
        if not settings["welcome_enabled"]:
            return
        new_members = getattr(message, "new_chat_members", None) or []
        for user in new_members:
            if getattr(user, "is_bot", False):
                continue
            name = html.escape(getattr(user, "first_name", None) or str(user.id), quote=True)
            mention = f'<a href="tg://user?id={int(user.id)}">{name}</a>'
            text = html.escape(settings["welcome_text"], quote=True)
            text = text.replace("{mention}", mention).replace("{name}", name).replace("{chat}", html.escape(getattr(message.chat, "title", None) or "this group", quote=True))
            try:
                await _reply(message, text, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            except Exception:
                # A welcome is non-critical; malformed templates never fail an update.
                continue

    async def manage(_, message):
        if not await admin_check(message):
            return
        target = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        if not target:
            await _reply(message, "Reply to a group member with /manage to open their action panel.")
            return
        if int(target.id) == int(message.from_user.id) or await _protected_target(client, message.chat.id, target.id):
            await _reply(message, "Protected accounts (admins, the owner, the bot, and yourself) cannot be actioned.")
            return
        token = _token({"chat": int(message.chat.id), "requester": int(message.from_user.id), "target": int(target.id), "expires": time.monotonic() + _PENDING_TTL})
        if not getattr(config, "BOT_TOKEN", None):
            _PENDING.pop(token, None)
            await _reply(message, "Userbot mode: inline keyboards may not work. Use /ban, /kick, /unban, /muteuser, or /unmuteuser by replying to the member.")
            return
        try:
            keyboard = _manage_markup(token)
            sent = await _reply(message, f"Choose an action for {html.escape(getattr(target, 'first_name', None) or str(target.id))}:", reply_markup=keyboard)
            await style_buttons(sent, keyboard)
        except Exception:
            await _reply(message, "Userbot mode: inline buttons may not work. Use /ban, /kick, /unban, /muteuser, or /unmuteuser by replying to the member.")

    async def member_command(_, message):
        if not await admin_check(message):
            return
        cmd = (getattr(message, "command", None) or [""])[0]
        cmd = cmd.split("@", 1)[0].lower()
        target_id, label = _target_from(message, _command_arg(message))
        if target_id is None:
            await _reply(message, f"Usage: /{cmd} by replying to a member or providing a numeric user ID.")
            return
        if target_id == int(message.from_user.id) or await _protected_target(client, message.chat.id, target_id):
            await _reply(message, "Protected accounts (admins, the owner, the bot, and yourself) cannot be actioned.")
            return
        if cmd in ("ban", "kick"):
            token = _token({"chat": int(message.chat.id), "requester": int(message.from_user.id), "target": int(target_id), "action": cmd, "expires": time.monotonic() + _PENDING_TTL})
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm", callback_data=f"ogm:c:{token}"), InlineKeyboardButton("Cancel", callback_data=f"ogm:x:{token}")]])
            if not getattr(config, "BOT_TOKEN", None):
                _PENDING.pop(token, None)
                await _reply(message, "This action needs an inline keyboard confirmation; userbot mode may not support it. No action was taken.")
                return
            try:
                await _reply(message, f"Confirm {cmd} for user {html.escape(str(label or target_id))}? This request expires in 3 minutes.", reply_markup=buttons)
            except Exception:
                _PENDING.pop(token, None)
                await _reply(message, "This action needs an inline keyboard; userbot mode may not support confirmation. No action was taken.")
            return
        await _execute_action(message, cmd, target_id)

    async def _execute_action(message, action, target_id):
        chat_id = message.chat.id
        if action not in _ACTIONS:
            await _reply(message, "Unknown moderation action.")
            return
        if target_id == int(message.from_user.id) or await _protected_target(client, chat_id, target_id):
            await _reply(message, "Protected accounts (admins, the owner, the bot, and yourself) cannot be actioned.")
            return
        if not await _bot_can_restrict(client, chat_id):
            await _reply(message, "I need administrator permission to restrict members in this group.")
            return
        try:
            if action == "ban":
                await client.ban_chat_member(chat_id, target_id)
            elif action == "kick":
                await client.ban_chat_member(chat_id, target_id)
                await client.unban_chat_member(chat_id, target_id)
            elif action == "unban":
                member = await client.get_chat_member(chat_id, target_id)
                status = getattr(member, "status", None)
                value = getattr(status, "value", status)
                if value != "banned":
                    await _reply(message, f"User {target_id} is not banned; no change made.")
                    return
                await client.unban_chat_member(chat_id, target_id)
            elif action == "muteuser":
                await client.restrict_chat_member(chat_id, target_id, permissions=__import__("pyrogram").types.ChatPermissions(can_send_messages=False))
            elif action == "unmuteuser":
                await client.restrict_chat_member(chat_id, target_id, permissions=__import__("pyrogram").types.ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
            await _reply(message, f"{action.capitalize()} completed for user {target_id}.")
        except Exception:
            await _reply(message, "Telegram rejected that action. Check the target's status and ensure I have the required administrator rights.")

    async def moderation_callback(_, query):
        data = getattr(query, "data", "") or ""
        if not data.startswith("ogm:"):
            return
        parts = data.split(":")
        user = getattr(query, "from_user", None)
        if len(parts) == 4 and parts[1] == "t":
            _, _, setting, chat_raw = parts
            try:
                chat_id = int(chat_raw)
            except ValueError:
                await query.answer("Invalid panel.", show_alert=True)
                return
            if not query.message or not getattr(query.message, "chat", None) or int(query.message.chat.id) != chat_id:
                await query.answer("This panel belongs to another group.", show_alert=True)
                return
            if not user or not await _is_admin_or_sudo(client, chat_id, user):
                await query.answer("Only this group's administrators can change settings.", show_alert=True)
                return
            if setting not in ("admins_only", "loop", "welcome_enabled"):
                await query.answer("Unknown setting.", show_alert=True)
                return
            current = get_settings(chat_id)
            new_value = not current[setting]
            update_settings(chat_id, **{setting: new_value})
            try:
                markup = _panel_markup(chat_id, get_settings(chat_id))
                await query.message.edit_reply_markup(reply_markup=markup)
                await style_buttons(query.message, markup)
            except Exception:
                pass
            await query.answer("Setting updated.")
            return
        # Callback management actions are bound to the original requester and chat.
        if len(parts) == 3 and parts[1] in ("c", "x"):
            token = parts[2]
            item = _PENDING.get(token)
            if not item or item.get("expires", 0) <= time.monotonic():
                await query.answer("This confirmation expired. Start again.", show_alert=True)
                return
            if not user or int(user.id) != item["requester"] or not query.message or int(query.message.chat.id) != item["chat"]:
                await query.answer("This confirmation belongs to another admin or group.", show_alert=True)
                return
            if not await _is_admin_or_sudo(client, item["chat"], user):
                await query.answer("You are no longer authorized to manage this group.", show_alert=True)
                return
            _PENDING.pop(token, None)
            if parts[1] == "x":
                await query.answer("Cancelled.")
                return
            await query.answer("Working…")
            proxy = type("CallbackMessage", (), {"chat": query.message.chat, "from_user": user, "reply_text": query.message.reply_text})()
            await _execute_action(proxy, item["action"], item["target"])
            return
        if len(parts) == 4 and parts[1] == "m":
            action, token = parts[2], parts[3]
            item = _PENDING.get(token)
            if action not in _ACTIONS or not item or item.get("expires", 0) <= time.monotonic():
                await query.answer("This panel expired. Run /manage again.", show_alert=True)
                return
            if not user or int(user.id) != item["requester"] or not query.message or int(query.message.chat.id) != item["chat"]:
                await query.answer("This panel belongs to another admin or group.", show_alert=True)
                return
            if not await _is_admin_or_sudo(client, item["chat"], user):
                await query.answer("You are no longer authorized to manage this group.", show_alert=True)
                return
            if action in ("ban", "kick"):
                item["action"] = action
                confirm_token = _token(item)
                # Leave the original manage panel token invalid to prevent replay.
                _PENDING.pop(token, None)
                buttons = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"ogm:c:{confirm_token}"), InlineKeyboardButton("✖ Cancel", callback_data=f"ogm:x:{confirm_token}")]])
                try:
                    await query.message.edit_text(f"Confirm {action} for user {item['target']}? This request expires in 3 minutes.", reply_markup=buttons)
                    await style_buttons(query.message, buttons)
                except Exception:
                    pass
                await query.answer("Confirmation required.")
            else:
                await query.answer("Working…")
                proxy = type("CallbackMessage", (), {"chat": query.message.chat, "from_user": user, "reply_text": query.message.reply_text})()
                _PENDING.pop(token, None)
                await _execute_action(proxy, action, item["target"])
            return
        await query.answer("Invalid panel action.", show_alert=True)

    def _stop_handler():
        raise _GateRejected()

    for name, handler in (("panel", panel), ("admin", panel), ("welcome", welcome_toggle), ("setwelcome", setwelcome), ("manage", manage)):
        client.add_handler(MessageHandler(handler, filters.command(name, config.PREFIXES) & ~filters.bot), group=-10)
    for name in _ACTIONS:
        client.add_handler(MessageHandler(member_command, filters.command(name, config.PREFIXES) & ~filters.bot), group=-10)
    client.add_handler(MessageHandler(welcome_new_members, filters.new_chat_members), group=-10)

    # A -20 gate runs ahead of the main music/UI group (normally group 0).
    # Returning StopPropagation rejects only gated requests, never controls.
    client.add_handler(MessageHandler(force_gate, filters.command(["play", "p", "search", "song", "download"], config.PREFIXES) & ~filters.bot), group=-20)
    client.add_handler(CallbackQueryHandler(force_callback, filters.regex(r"^(ogs:|ogc:d:)")), group=-20)
    client.add_handler(CallbackQueryHandler(moderation_callback, filters.regex(r"^ogm:")), group=-10)

    return True
