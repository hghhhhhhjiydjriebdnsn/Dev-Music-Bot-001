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

"""PIHU MUSIC's Telegram presentation, searches, and inline controls.

Callbacks deliberately use opaque short-lived tokens rather than accepting
queries or URLs supplied in callback data. Pyrogram/Telegram buttons use the
standard button API; their exact rendering is client-dependent.
"""

import html
import inspect
import os
import tempfile
import time
import secrets
import aiohttp
from collections import OrderedDict

from pyrogram import filters, enums
from core.premium import send_text, send_audio, send_photo, edit_text
from core.fonts import sc, bold, bold_italic
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


_TOKEN_TTL = 15 * 60
_TOKEN_LIMIT = 500
_search_tokens = OrderedDict()


def _h(value):
    return html.escape(str(value or ""), quote=True)


def _cache_track(user_id, chat_id, track):
    now = time.monotonic()
    for key, item in list(_search_tokens.items()):
        if item["expires"] <= now:
            _search_tokens.pop(key, None)
    token = secrets.token_urlsafe(6)
    _search_tokens[token] = {
        "user": user_id,
        "chat": chat_id,
        "track": track,
        "expires": now + _TOKEN_TTL,
        "played": False,
    }
    while len(_search_tokens) > _TOKEN_LIMIT:
        _search_tokens.popitem(last=False)
    return token


def _keyboard_controls(chat_id):
    from core.groups import get_group
    autoplay_on = bool(get_group(chat_id).get("autoplay"))
    rows = [
        # First row, side by side: pause (blue) + resume (green).
        [InlineKeyboardButton("⏸ " + sc("pause"), callback_data=f"ogc:p:{chat_id}"),
         InlineKeyboardButton(sc("resume"), callback_data=f"ogc:r:{chat_id}")],
        [InlineKeyboardButton("⏭ " + sc("skip"), callback_data=f"ogc:s:{chat_id}"),
         InlineKeyboardButton("⏹ " + sc("stop"), callback_data=f"ogc:x:{chat_id}")],
        # ♻️ is an existing catalog emoji: core.premium swaps it for its custom ID.
        [InlineKeyboardButton("♻️ " + sc("autoplay") + " : " + sc("on" if autoplay_on else "off"),
                              callback_data=f"ogc:a:{chat_id}")],
        [InlineKeyboardButton("🔁 " + sc("loop"), callback_data=f"ogc:l:{chat_id}"),
         InlineKeyboardButton("🔀 " + sc("shuffle"), callback_data=f"ogc:h:{chat_id}")],
        [InlineKeyboardButton("📋 " + sc("queue"), callback_data=f"ogc:q:{chat_id}"),
         InlineKeyboardButton("⬇️ " + sc("download"), callback_data=f"ogc:d:{chat_id}")],
    ]
    return InlineKeyboardMarkup(rows)


def _track_keyboard(token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ " + sc("play / add"), callback_data=f"ogs:p:{token}"),
         InlineKeyboardButton("⬇️ " + sc("download"), callback_data=f"ogs:d:{token}")]
    ])


async def apply_button_style(message, markup):
    """Fallback styling for messages that went out as plain keyboards.

    Messages sent through core.premium's Bot API path already carry colours and
    icons from the first moment, so they are skipped here.
    """
    from config import config
    from core.premium import build_keyboard
    token = getattr(config, "BOT_TOKEN", None)
    if not token or not message or not markup:
        return False
    if getattr(message, "_pihu_keyboard_styled", False):
        return True
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for icons in (True, False):
                payload = {"chat_id": message.chat.id, "message_id": message.id,
                           "reply_markup": build_keyboard(markup, icons)}
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        return True
    except Exception:
        # Never log Bot API URLs (which include the bot token).
        return False
    return False


async def _send_text(message, *args, **kwargs):
    # Telegram user accounts cannot attach bot inline keyboards.
    from config import config
    if not config.BOT_TOKEN:
        kwargs.pop("reply_markup", None)
    return await send_text(message, *args, **kwargs)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _provider_api():
    # Loaded lazily to avoid coupling core.ui import to the provider module or
    # creating a core -> ui -> core import cycle during bot startup.
    from ogmusic.providers import service
    return service


async def _is_admin_click(query):
    """Authorize the actual callback clicker, never the message sender."""
    from config import config
    uid = getattr(query.from_user, "id", None)
    if uid is None:
        return False
    if uid in getattr(config, "SUDOERS", set()):
        return True
    chat = query.message.chat
    try:
        member = await chat.get_member(uid)
        status = getattr(member, "status", None)
        return str(getattr(status, "value", status)).lower() in {
            "owner", "administrator", "creator", "chatmemberstatus.owner",
            "chatmemberstatus.administrator",
        }
    except Exception:
        return False


def _track_song(track, message, user):
    from core.song import Song
    song = Song(track.to_song_dict(), message)
    song.requested_by = user
    # Provider tracks are remote audio streams, even if this group's normal
    # stream mode is video.
    song.audio_only = True
    return song


async def _search_tracks(query, provider=None):
    service = _provider_api()
    return await _maybe_await(service.search(query, limit=5, provider=provider))


def register_ui(client):
    """Register public PIHU MUSIC commands and safe callback handlers."""
    from config import config

    @client.on_message(filters.command("start", config.PREFIXES) & ~filters.bot)
    async def start_ui(_, message):
        await _send_start(message)

    @client.on_message(filters.command("help", config.PREFIXES) & ~filters.bot)
    async def help_ui(_, message):
        keyboard = _help_keyboard(message.from_user)
        sent = await _send_text(message, _help_text(), reply_markup=keyboard,
                                parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        await apply_button_style(sent, keyboard)

    @client.on_message(filters.command("premium", config.PREFIXES) & ~filters.bot)
    async def premium_ui(_, message):
        await _send_text(message, _premium_text(), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)

    @client.on_message(filters.command("search", config.PREFIXES) & ~filters.bot)
    async def search_ui(_, message):
        query = _command_query(message.text)
        if not query:
            return await _send_text(message, f"🔎 <b>{sc('send a song name')}</b>\n<blockquote>{sc('example')} : <code>/search Daft Punk One More Time</code></blockquote>", parse_mode=enums.ParseMode.HTML)
        status = await _send_text(message, f"🔎 <b>{sc('searching tracks…')}</b>", parse_mode=enums.ParseMode.HTML)
        try:
            tracks = await _search_tracks(query)
        except Exception as exc:
            await edit_text(status, f"⚠️ <b>{sc('search is temporarily unavailable')}</b>\n<blockquote>{sc('please try again in a moment.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
            return
        if not tracks:
            return await edit_text(status, f"🔎 <b>{sc('no tracks found')}</b>\n<blockquote>{sc('try another title or artist name.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
        rows = []
        for index, track in enumerate(tracks[:5], 1):
            token = _cache_track(message.from_user.id if message.from_user else 0, message.chat.id, track)
            artists_value = getattr(track, "artists", "") or ""
            artists = ", ".join(artists_value) if isinstance(artists_value, (list, tuple)) else str(artists_value)
            title = _h(getattr(track, "title", "Untitled"))
            from ogmusic.models import format_duration
            duration = _h(format_duration(getattr(track, "duration", 0)))
            label = f"🎵 <b>{title}</b>\n<blockquote>"
            if artists:
                label += f"👤 {_h(artists)}\n"
            label += f"⏱ {duration} · #{index}</blockquote>"
            keyboard = _track_keyboard(token)
            sent = await send_text(status, label, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            await apply_button_style(sent, keyboard)
        await status.delete()

    @client.on_message(filters.command(["song", "download"], config.PREFIXES) & ~filters.bot)
    async def download_ui(_, message):
        query = _command_query(message.text)
        if not query:
            return await _send_text(message, f"⬇️ <b>{sc('send a song name')}</b>\n<blockquote>{sc('example')} : <code>/song artist - title</code></blockquote>", parse_mode=enums.ParseMode.HTML)
        status = await _send_text(message, f"🔎 <b>{sc('finding your track…')}</b>", parse_mode=enums.ParseMode.HTML)
        try:
            tracks = await _search_tracks(query)
            if not tracks:
                return await edit_text(status, f"🔎 <b>{sc('no track found for that query')}</b>", parse_mode=enums.ParseMode.HTML)
            track = tracks[0]
            await edit_text(status, f"⬇️ <b>{sc('preparing your audio file…')}</b>", parse_mode=enums.ParseMode.HTML)
            from ogmusic.providers import download_audio
            with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
                path = await _maybe_await(download_audio(track, directory, max_bytes=50 * 1024 * 1024))
                path = os.fspath(path)
                title = _h(getattr(track, "title", "Audio track"))
                await send_audio(message, path, caption=f"🎵 <b>{title}</b>\n<blockquote>{sc('downloaded via')} <b>{sc('pihu music')}</b> ✨</blockquote>", parse_mode=enums.ParseMode.HTML)
            await status.delete()
        except Exception as exc:
            await edit_text(status, f"⚠️ <b>{sc('could not download this audio')}</b>\n<blockquote>{sc('the provider may be unavailable or the file is too large.')}</blockquote>", parse_mode=enums.ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^ogu:"))
    async def menu_callback(_, query):
        await query.answer()
        action = query.data.split(":", 1)[1]
        if action == "premium":
            await send_text(query.message, _premium_text(), parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        elif action == "help":
            keyboard = _help_keyboard(query.from_user)
            sent = await send_text(query.message, _help_text(), reply_markup=keyboard,
                                   parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            await apply_button_style(sent, keyboard)
        elif action == "start":
            await _send_start(query.message, user=query.from_user)
        elif action == "search":
            await send_text(query.message, f"🔎 <b>{sc('search tips')}</b>\n<blockquote>{sc('try')} <code>/search artist - track</code>\n{sc('then tap')} <b>{sc('play / add')}</b> {sc('or')} <b>{sc('download')}</b>.</blockquote>", parse_mode=enums.ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^ogh:"))
    async def help_callback(_, query):
        cat = query.data.split(":", 1)[1]
        role = _role(query.from_user)
        if cat == "close":
            await query.answer()
            try:
                await query.message.delete()
            except Exception:
                pass
            return
        if cat in ("sudo", "owner") and not (role == "owner" or (cat == "sudo" and role == "sudo")):
            return await query.answer("Not available for your account.", show_alert=True)
        await query.answer()
        if cat == "home":
            text, keyboard = _help_text(), _help_keyboard(query.from_user)
        elif cat in _HELP_PAGES:
            text, keyboard = _help_page(cat), _back_keyboard()
        else:
            return
        try:
            sent = await edit_text(query.message, text, reply_markup=keyboard,
                                   parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            await apply_button_style(sent, keyboard)
        except Exception:
            pass

    @client.on_callback_query(filters.regex(r"^ogs:"))
    async def search_callback(_, query):
        # Acknowledge promptly before any API or playback work.
        await query.answer()
        try:
            _, action, token = query.data.split(":", 2)
        except ValueError:
            return
        item = _search_tokens.get(token)
        if (not item or item["expires"] <= time.monotonic()
                or item["user"] != query.from_user.id
                or item["chat"] != query.message.chat.id):
            if item and item["expires"] <= time.monotonic():
                _search_tokens.pop(token, None)
            return await send_text(query.message, f"⏳ <b>{sc('this result expired')}</b>\n<blockquote>{sc('run /search again to get fresh results.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
        if action == "p":
            if item["played"]:
                return await send_text(query.message, f"✅ <b>{sc('already used')}</b>\n<blockquote>{sc('search again for a fresh result.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
            item["played"] = True  # replay invalidation before doing any async work
            try:
                await _enqueue_search_track(query, item)
            except Exception as exc:
                if getattr(exc, "handled", False):
                    return
                await send_text(query.message, f"⚠️ <b>{sc('could not start this track')}</b>\n<blockquote>{sc('check the voice chat and the assistant\'s permissions.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
        elif action == "d":
            await _download_search_track(query, item)

    @client.on_callback_query(filters.regex(r"^ogc:"))
    async def playback_callback(_, query):
        # Ack first; permissions are evaluated against the callback clicker.
        await query.answer()
        try:
            _, action, raw_chat = query.data.split(":", 2)
            chat_id = int(raw_chat)
        except (ValueError, AttributeError):
            return
        if query.message.chat.id != chat_id or not await _is_admin_click(query):
            return await send_text(query.message, f"🚫 <b>{sc('admins only')}</b>\n<blockquote>{sc('only group admins can use these controls.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
        await _run_control(query, action, chat_id)


def _command_query(text):
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _link_buttons():
    from config import config
    rows = []
    row = []
    if config.SUPPORT_URL:
        row.append(InlineKeyboardButton("💬 " + sc("support"), url=config.SUPPORT_URL))
    if config.OWNER_USERNAME:
        row.append(InlineKeyboardButton("👑 " + sc("owner"), url=f"https://t.me/{config.OWNER_USERNAME}"))
    if row:
        rows.append(row)
    return rows


def _group_start_keyboard():
    rows = [[InlineKeyboardButton("📒 " + sc("commands"), callback_data="ogu:help")]]
    rows += _link_buttons()
    return InlineKeyboardMarkup(rows)


def _start_keyboard():
    from config import config
    rows = []
    if config.BOT_USERNAME:
        rows.append([InlineKeyboardButton("➕ " + sc("add me to your group"),
                                          url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=delete_messages+manage_video_chats+invite_users+restrict_members+pin_messages")])
    rows.append([InlineKeyboardButton("📖 " + sc("help & commands"), callback_data="ogu:help"),
                 InlineKeyboardButton("✨ " + sc("features"), callback_data="ogu:premium")])
    rows += _link_buttons()
    return InlineKeyboardMarkup(rows)


def _role(user):
    from config import config
    uid = getattr(user, "id", None)
    if uid in getattr(config, "OWNERS", ()):
        return "owner"
    if uid in config.SUDOERS:
        return "sudo"
    return "user"


def _help_keyboard(user=None):
    role = _role(user)
    rows = [[InlineKeyboardButton("🌍 " + sc("public"), callback_data="ogh:public"),
             InlineKeyboardButton("🛠 " + sc("admins"), callback_data="ogh:admin")]]
    if role in ("sudo", "owner"):
        extra = [InlineKeyboardButton("🛡️ " + sc("sudoers"), callback_data="ogh:sudo")]
        if role == "owner":
            extra.append(InlineKeyboardButton("👑 " + sc("owner"), callback_data="ogh:owner"))
        rows.append(extra)
    rows.append([InlineKeyboardButton("🎵 " + sc("home"), callback_data="ogu:start"),
                 InlineKeyboardButton("✖ " + sc("close"), callback_data="ogh:close")])
    return InlineKeyboardMarkup(rows)


def _back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ " + sc("back"), callback_data="ogh:home"),
                                  InlineKeyboardButton("✖ " + sc("close"), callback_data="ogh:close")]])


def _start_text(name):
    return (
        f"🎵 <b>{sc('pihu music')}</b> ✨\n\n"
        f"<i>{sc('hey')}</i> <b>{_h(name)}</b> 👋\n"
        f"<blockquote><i>{sc('i play high-quality music in your group voice chats — fast, smooth and ad-free.')}</i></blockquote>\n"
        f"<b>{sc('what i can do')}</b>\n"
        f"<blockquote><b>🎧 {sc('stream songs, radio & youtube in vc')}</b>\n"
        f"<b>🔎 {sc('search tracks with instant buttons')}</b>\n"
        f"<b>⬇️ {sc('download songs as audio files')}</b>\n"
        f"<b>📋 {sc('queue, loop, shuffle & live controls')}</b>\n"
        f"<b>🛡️ {sc('admin panel, welcome & moderation')}</b></blockquote>\n"
        f"<i>{sc('add me to your group, start a voice chat and send')}</i> <code>/play song name</code>"
    )


START_IMAGE_URL = os.getenv("START_IMAGE_URL", "").strip()
_start_image_path = None
_LOCAL_START_IMAGES = ("theme/start.png", "theme/start.jpg")


def _prepare_photo(data, path):
    """Telegram rejects huge/odd photos (10 MB, bad ratio). Re-encode to a safe JPEG."""
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    img.thumbnail((1280, 1280))
    img.save(path, "JPEG", quality=88, optimize=True)


async def _start_image():
    """Start picture: the bundled theme/start.png first (always works), then the URL."""
    import asyncio
    import logging
    global _start_image_path
    if _start_image_path and os.path.exists(_start_image_path):
        return _start_image_path
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(tempfile.gettempdir(), "pihu_start_image_v2.jpg")
    for rel in _LOCAL_START_IMAGES:
        local = os.path.join(base, rel)
        if os.path.exists(local):
            try:
                with open(local, "rb") as handle:
                    await asyncio.to_thread(_prepare_photo, handle.read(), path)
                _start_image_path = path
                return path
            except Exception as exc:
                logging.getLogger(__name__).warning("local start image failed: %s", type(exc).__name__)
    if not START_IMAGE_URL:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(START_IMAGE_URL) as response:
                response.raise_for_status()
                data = await response.read()
        await asyncio.to_thread(_prepare_photo, data, path)
        _start_image_path = path
        return path
    except Exception as exc:
        logging.getLogger(__name__).warning("start image download failed: %s", type(exc).__name__)
    return None


async def _send_start(message, user=None):
    user = user or getattr(message, "from_user", None)
    if str(getattr(message.chat.type, "value", message.chat.type)).lower() != "private":
        keyboard = _group_start_keyboard()
        sent = await _send_text(message,
            f"🎵 <b>{sc('pihu music')} {sc('is here!')}</b> ✨\n"
            f"<blockquote><i>{sc('start a voice chat and send')}</i> <code>/play song name</code>\n"
            f"<i>{sc('need the commands? tap')}</i> <b>{sc('commands')}</b>.</blockquote>",
            reply_markup=keyboard, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        await apply_button_style(sent, keyboard)
        return
    name = getattr(user, "first_name", None) or "music fan"
    text = _start_text(name)
    keyboard = _start_keyboard()
    sent = None
    import logging
    for source in (await _start_image(), START_IMAGE_URL):
        if not source:
            continue
        try:
            sent = await send_photo(message, photo=source, caption=text, reply_markup=keyboard,
                                    parse_mode=enums.ParseMode.HTML)
            break
        except Exception as exc:
            logging.getLogger(__name__).warning("start photo failed (%s): %s", type(exc).__name__, exc)
            sent = None
    if sent is None:
        sent = await _send_text(message, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML,
                                disable_web_page_preview=True)
    await apply_button_style(sent, keyboard)


def _cmd(command, hint, desc):
    hint = f" <i>{hint}</i>" if hint else ""
    return f"<code>/{command}</code>{hint} — <b>{sc(desc)}</b>"


def _help_text():
    return (
        f"📖 <b>{sc('pihu music')} — {sc('help menu')}</b>\n\n"
        f"<blockquote><i>{sc('choose a category below to see its commands.')}</i>\n"
        f"<b>🌍 {sc('public')} · 🛠 {sc('admins')}</b></blockquote>\n"
        f"<i>{sc('tip: tap the / button next to the message box to see every command.')}</i>"
    )


_HELP_PAGES = {
    "public": ("🌍", "public commands", "play songs, search, download and check the bot.", [
        ("play", "song / link", "play in the voice chat"),
        ("search", "song", "pick from 5 results"),
        ("song", "song", "get the audio file"),
        ("radio", "url", "play a live stream"),
        ("playlist", "yt link", "queue a whole playlist"),
        ("queue", "", "show what's next"),
        ("assistant", "", "which assistant serves this group"),
        ("ping", "", "check bot speed"),
        ("start", "", "start the bot"),
        ("help", "", "this menu"),
    ]),
    "admin": ("🛠", "admin commands", "playback control and group management.", [
        ("pause", "", "pause playback"), ("resume", "", "resume playback"),
        ("skip", "", "next track"), ("stop", "", "stop & clear queue"),
        ("loop", "", "toggle repeat"), ("shuffle", "", "shuffle the queue"),
        ("mute", "", "mute / unmute"), ("mode", "", "audio / video stream"),
        ("lang", "code", "change language"), ("admins", "", "admin-only mode"),
        ("admin", "", "group settings panel"), ("manage", "", "reply to a member"),
        ("welcome", "on|off", "greet new members"), ("setwelcome", "text", "custom welcome"),
        ("ban", "", "ban · unban · kick · muteuser"),
    ]),
    "sudo": ("🛡️", "sudoer commands", "monitoring tools for trusted users.", [
        ("stats", "", "bot & system statistics"),
        ("active", "", "active voice chats"),
        ("groups", "", "all served groups"),
        ("sudolist", "", "owners & sudoers"),
        ("blacklisted", "", "blocked users & chats"),
    ]),
    "owner": ("👑", "owner commands", "full control of the bot.", [
        ("owner", "", "owner panel"),
        ("broadcast", "text", "message everyone (-users -groups -pin)"),
        ("addsudo", "user", "add a sudoer"), ("delsudo", "user", "remove a sudoer"),
        ("block", "user", "block a user"), ("unblock", "user", "unblock a user"),
        ("blockchat", "id", "block a chat"), ("unblockchat", "id", "unblock a chat"),
        ("maintenance", "on|off", "maintenance mode"), ("logger", "on|off", "event notifications"),
        ("assistants", "", "manage assistants"), ("addassistant", "session", "add a string session"),
        ("rmassistant", "id", "remove an assistant"), ("setassistant", "chat bot", "pin a group to an assistant"),
        ("leavechat", "id", "make the bot leave a chat"),
    ]),
}


def _help_page(cat):
    icon, title, blurb, items = _HELP_PAGES[cat]
    lines = "\n".join(_cmd(c, h, d) for c, h, d in items)
    return (f"{icon} <b>{sc(title)}</b>\n<i>{sc(blurb)}</i>\n\n"
            f"<blockquote expandable>{lines}</blockquote>")


def _premium_text():
    return (
        f"✨ <b>{sc('pihu music')} — {sc('features')}</b>\n\n"
        f"<blockquote><b>🎧 {sc('crystal-clear api streaming')}</b>\n"
        f"<b>🖼 {sc('now-playing cover card')}</b>\n"
        f"<b>🎛 {sc('colourful inline controls')}</b>\n"
        f"<b>⬇️ {sc('one-tap song downloads')}</b>\n"
        f"<b>🛡️ {sc('admin panel, welcome & moderation')}</b>\n"
        f"<b>🌐 {sc('multi-language support')}</b></blockquote>\n"
        f"<i>{sc('free to use · no subscription needed.')}</i>"
    )


async def _enqueue_search_track(query, item):
    from core.groups import get_group, get_queue, set_group
    from core.stream import start_stream
    from core.ui import _track_song
    chat = query.message.chat
    if str(getattr(chat.type, "value", chat.type)).lower() == "private":
        return await send_text(query.message, f"⚠️ <b>{sc('use this in a group chat')}</b>\n<blockquote>{sc('i need a group voice chat to play music.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
    group = get_group(chat.id)
    if group["admins_only"] and not await _is_admin_click(query):
        return await send_text(query.message, f"🚫 <b>{sc('admin-only mode is on')}</b>\n<blockquote>{sc('only group admins can add tracks right now.')}</blockquote>", parse_mode=enums.ParseMode.HTML)
    song = _track_song(item["track"], query.message, query.from_user)
    if not group["is_playing"]:
        # Update state only after startup succeeds; start_stream also rolls back
        # its own state on initial playback errors.
        set_group(chat.id, is_playing=True, now_playing=song)
        try:
            from lang import load
            await start_stream(song, load(group.get("lang", "en")))
        except Exception:
            set_group(chat.id, is_playing=False, now_playing=None)
            raise
        await send_text(query.message, f"▶️ <b>{sc('started')}</b> : <b>{_h(song.title)}</b>", parse_mode=enums.ParseMode.HTML)
    else:
        queue = get_queue(chat.id)
        await queue.put(song)
        await send_text(query.message, f"➕ <b>{sc('added to queue')}</b>\n<blockquote><b>{_h(song.title)}</b>\n{sc('position')} : <code>#{len(queue)}</code></blockquote>", parse_mode=enums.ParseMode.HTML)


async def _download_search_track(query, item):
    import tempfile
    from ogmusic.providers import download_audio
    track = item["track"]
    status = await send_text(query.message, f"⬇️ <b>{sc('preparing audio…')}</b>", parse_mode=enums.ParseMode.HTML)
    try:
        with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
            path = await _maybe_await(download_audio(track, directory, max_bytes=50 * 1024 * 1024))
            await send_audio(query.message, os.fspath(path), caption=f"🎵 <b>{_h(getattr(track, 'title', 'Audio track'))}</b>\n<blockquote>{sc('downloaded via')} <b>{sc('pihu music')}</b> ✨</blockquote>", parse_mode=enums.ParseMode.HTML)
        await status.delete()
    except Exception as exc:
        await edit_text(status, f"⚠️ <b>{sc('could not download this audio')}</b>\n<blockquote>{sc('the provider may be unavailable or the file is too large.')}</blockquote>", parse_mode=enums.ParseMode.HTML)


async def _refresh_controls(query, chat_id):
    """Redraw the player keyboard so the Autoplay ON/OFF label is current."""
    markup = _keyboard_controls(chat_id)
    if await apply_button_style(query.message, markup):
        return
    try:
        await query.message.edit_reply_markup(markup)
    except Exception:
        pass  # e.g. message not modified; the toggle itself already succeeded


async def _run_control(query, action, chat_id):
    from core.stream import start_stream
    from core.assistants import calls_for, app_for
    from core.groups import get_group, get_queue, set_group, clear_queue, set_title
    from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
    from lang import load
    from core import progress
    group = get_group(chat_id)
    lang = load(group.get("lang", "en"))
    try:
        if action == "p":
            await calls_for(chat_id).pause_stream(chat_id)
            progress.pause(chat_id)
            note = f"⏸ <b>{sc('playback paused')}</b>"
        elif action == "r":
            await calls_for(chat_id).resume_stream(chat_id)
            progress.resume(chat_id)
            note = f"▶️ <b>{sc('playback resumed')}</b>"
        elif action == "s":
            if group.get("loop") and group.get("now_playing"):
                await start_stream(group["now_playing"], lang)
            else:
                queue = get_queue(chat_id)
                if not len(queue):
                    set_group(chat_id, is_playing=False, now_playing=None)
                    await set_title(chat_id, "", client=app_for(chat_id))
                    await calls_for(chat_id).leave_call(chat_id)
                    note = f"⏭ <b>{sc('queue empty · left the voice chat')}</b>"
                else:
                    song = await queue.get()
                    if not song.parsed:
                        ok, status = await song.parse()
                        if not ok:
                            raise RuntimeError(status)
                    set_group(chat_id, is_playing=True, now_playing=song)
                    await start_stream(song, lang)
                    note = f"⏭ <b>{sc('now playing')}</b> : <b>{_h(song.title)}</b>"
        elif action == "x":
            set_group(chat_id, is_playing=False, now_playing=None)
            clear_queue(chat_id)
            await calls_for(chat_id).leave_call(chat_id)
            await set_title(chat_id, "", client=app_for(chat_id))
            note = f"⏹ <b>{sc('stopped & queue cleared')}</b>"
        elif action == "l":
            enabled = not bool(group.get("loop"))
            set_group(chat_id, loop=enabled)
            note = f"🔁 <b>{sc('loop enabled' if enabled else 'loop disabled')}</b>"
        elif action == "a":
            enabled = not bool(group.get("autoplay"))
            # Per-chat state only; a fresh history avoids stale repeat-blocking.
            set_group(chat_id, autoplay=enabled, autoplay_history=[])
            await _refresh_controls(query, chat_id)
            note = f"♻️ <b>{sc('autoplay on' if enabled else 'autoplay off')}</b>"
        elif action == "h":
            queue = get_queue(chat_id)
            if len(queue):
                from core.groups import shuffle_queue
                shuffle_queue(chat_id)
                note = f"🔀 <b>{sc('queue shuffled')}</b>"
            else:
                note = f"📋 <b>{sc('the queue is empty')}</b>"
        elif action == "q":
            queue = get_queue(chat_id)
            text = _queue_html(queue) if len(queue) else f"📋 <b>{sc('the queue is empty')}</b>"
            await send_text(query.message, text, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
            return
        elif action == "d":
            current = group.get("now_playing")
            if current is None:
                return await send_text(query.message, f"⬇️ <b>{sc('nothing to download right now')}</b>", parse_mode=enums.ParseMode.HTML)
            if not getattr(current, "provider", None):
                return await send_text(query.message, f"⬇️ <b>{sc('use /song title to download a track')}</b>", parse_mode=enums.ParseMode.HTML)
            from ogmusic.providers import Track
            from ogmusic.models import duration_seconds
            track = Track(title=current.title, artists=getattr(current, "artists", ""),
                          duration=duration_seconds(current.duration), thumbnail=current.thumb,
                          stream_url=current.remote, source_url=current.source,
                          provider=current.provider)
            from ogmusic.providers import download_audio
            with tempfile.TemporaryDirectory(prefix="ogmusic-") as directory:
                path = await _maybe_await(download_audio(
                    track, directory, max_bytes=50 * 1024 * 1024
                ))
                await send_audio(query.message, 
                    os.fspath(path),
                    caption=f"🎵 <b>{_h(track.title)}</b>\n<blockquote>{sc('downloaded via')} <b>{sc('pihu music')}</b> ✨</blockquote>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        else:
            return
        await send_text(query.message, note, parse_mode=enums.ParseMode.HTML)
    except (NoActiveGroupCall, NotInCallError):
        if action == "x":
            await send_text(query.message, f"⏹ <b>{sc('stopped · no active voice chat')}</b>", parse_mode=enums.ParseMode.HTML)
        else:
            await send_text(query.message, f"❌ <b>{sc('nothing is playing right now')}</b>", parse_mode=enums.ParseMode.HTML)
    except Exception as exc:
        await send_text(query.message, f"⚠️ <b>{sc('control failed')}</b>\n<blockquote>{sc('check the voice chat & assistant permissions, then try again.')}</blockquote>", parse_mode=enums.ParseMode.HTML)


def _queue_html(queue):
    lines = []
    for index, song in enumerate(queue, 1):
        if index > 10:
            lines.append(f"… {sc('and')} {len(queue) - 10} {sc('more')}")
            break
        title = _h(getattr(song, "title", "Untitled"))
        source = _h(getattr(song, "source", ""))
        user = getattr(song, "requested_by", None)
        requester = _h(getattr(user, "first_name", "Unknown"))
        lines.append(f'<b>{index}.</b> <a href="{source}">{title}</a> · <i>{requester}</i>')
    return f"📋 <b>{sc('up next')}</b>\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>"
