"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import os
import asyncio
import logging
from config import config
from core.song import Song
from pyrogram import Client
from yt_dlp import YoutubeDL
from pytgcalls import PyTgCalls
from core.funcs import generate_cover
from core.groups import get_group, set_title
from pytgcalls.types.stream import MediaStream
from pyrogram.raw.types import InputPeerChannel
from pytgcalls.types import AudioQuality, VideoQuality
from pyrogram.raw.functions.phone import CreateGroupCall
from pytgcalls.exceptions import NoActiveGroupCall

log = logging.getLogger("stream")

# ============================================================
#  PLAYING MESSAGE CACHE
#  chat_id -> Message (playing message)
# ============================================================
safone: dict = {}

# ============================================================
#  YT-DLP CONFIG
# ============================================================
ydl_opts = {
    "quiet": True,
    "no_warnings": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "noplaylist": True,
    "extract_flat": False,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",  # Force IPv4
    "format": "bestaudio/best",
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ============================================================
#  PYROGRAM USERBOT (joins VC)
# ============================================================
app = Client(
    "MusicPlayerUB",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.SESSION,
    in_memory=True,
)

ytdl = YoutubeDL(ydl_opts)

# ============================================================
#  PYTGCALLS
# ============================================================
pytgcalls = PyTgCalls(app)


# ============================================================
#  STREAM STARTER
# ============================================================
async def start_stream(song: Song, lang: dict, _retry: int = 0) -> None:
    """Start streaming a song in the song's chat."""
    chat = song.request_msg.chat

    # Cleanup previous playing message
    if safone.get(chat.id) is not None:
        try:
            await safone[chat.id].delete()
        except Exception:
            pass

    # Validate remote URL
    if not song.remote:
        log.error(f"No remote URL for song: {song.title}")
        try:
            await song.request_msg.reply_text(
                lang.get("notFound", "❌ Could not stream this track.")
            )
        except Exception:
            pass
        return

    infomsg = await song.request_msg.reply_text(
        lang.get("downloading", "⏳ Downloading...")
    )

    try:
        await pytgcalls.play(chat.id, get_quality(song))
    except NoActiveGroupCall:
        # Try to create a group call, then retry once
        try:
            peer = await app.resolve_peer(chat.id)
            await app.invoke(
                CreateGroupCall(
                    peer=InputPeerChannel(
                        channel_id=peer.channel_id,
                        access_hash=peer.access_hash,
                    ),
                    random_id=app.rnd_id(),
                )
            )
        except Exception as e:
            log.exception("Failed to create group call")
            await infomsg.edit_text(
                lang.get("notActive", "❌ Could not join the voice chat.")
            )
            return

        await infomsg.delete()
        if _retry >= 1:
            log.error("Group call creation retry failed.")
            return
        return await start_stream(song, lang, _retry=_retry + 1)
    except Exception as e:
        log.exception("Stream play failed")
        await infomsg.edit_text(f"⚠️ Stream error: `{e}`")
        return

    # Set VC title
    await set_title(chat.id, song.title, client=app)

    # Generate cover image
    thumb = await generate_cover(
        song.title,
        chat.title or "Music",
        chat.id,
        song.thumb,
    )

    # Fallback to logo if cover generation failed
    if not thumb or not os.path.exists(str(thumb)):
        thumb = "theme/logo.PNG"
        if not os.path.exists(thumb):
            thumb = None

    # Build playing message
    caption = _build_playing_caption(song, lang)
    buttons = _build_playing_buttons()

    try:
        if thumb:
            safone[chat.id] = await song.request_msg.reply_photo(
                photo=thumb,
                caption=caption,
                reply_markup=buttons,
            )
        else:
            safone[chat.id] = await song.request_msg.reply_text(
                caption,
                reply_markup=buttons,
                disable_web_page_preview=True,
            )
    except Exception:
        log.exception("Failed to send playing message")
        # Last-resort: plain text
        safone[chat.id] = await song.request_msg.reply_text(caption)

    # Cleanup temp cover
    if thumb and os.path.exists(thumb) and thumb != "theme/logo.PNG":
        try:
            os.remove(thumb)
        except OSError:
            pass

    try:
        await infomsg.delete()
    except Exception:
        pass


# ============================================================
#  PLAYING MESSAGE BUILDER
#  (Small caps + Premium emoji + Colored buttons)
# ============================================================
def _small_caps(text: str) -> str:
    """Convert ASCII letters to Unicode Small Caps."""
    return text.translate(str.maketrans(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ",
    ))


def _build_playing_caption(song: Song, lang: dict) -> str:
    """Build a nicely formatted playing caption with premium emoji."""
    # ---- Premium Emoji IDs ----
    # TODO: Replace these with your own Premium emoji IDs.
    # Format: <tg-emoji emoji-id="ID">🎵</tg-emoji>
    # As long as you don't have IDs, we use plain Unicode emoji.
    EMOJI_MUSIC = "🎵"
    EMOJI_DURATION = "⏱"
    EMOJI_USER = "👤"
    EMOJI_SOURCE = "🔗"

    title = _small_caps(song.title or "Unknown")
    source = song.source or "N/A"
    duration = song.duration or "N/A"

    requested_by = (
        song.requested_by.mention
        if song.requested_by
        else (song.request_msg.sender_chat.title if song.request_msg.sender_chat else "Unknown")
    )

    # Build caption — using HTML entities that Pyrogram supports
    caption = (
        f"{EMOJI_MUSIC} <b>{title}</b>\n\n"
        f"{EMOJI_DURATION} <b>Duration:</b> <code>{duration}</code>\n"
        f"{EMOJI_SOURCE} <b>Source:</b> <a href=\"{source}\">Link</a>\n"
        f"{EMOJI_USER} <b>Requested by:</b> {requested_by}\n"
    )
    return caption


def _build_playing_buttons():
    """Build colored inline buttons with premium emoji icons."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    # ---- Premium Emoji IDs for buttons ----
    # TODO: Replace icon_custom_emoji_id with your Premium emoji IDs.
    # For now, plain text labels are used.
    def btn(text: str, data: str, style: str = None):
        kwargs = {"text": text, "callback_data": data}
        if style:
            # Pyrogram 2.x doesn't support `style` natively.
            # PyrogramMod may support it — we try to pass it and fall back.
            kwargs["style"] = style
        return InlineKeyboardButton(**kwargs)

    row1 = [
        btn("⏸ ᴘᴀᴜsᴇ", "pause", "primary"),
        btn("⏭ sᴋɪᴘ", "skip", "success"),
    ]
    row2 = [
        btn("⏹ sᴛᴏᴘ", "stop", "danger"),
        btn("🔁 ʟᴏᴏᴘ", "loop", "primary"),
    ]
    return InlineKeyboardMarkup([row1, row2])


# ============================================================
#  STREAM QUALITY
# ============================================================
def get_quality(song: Song) -> MediaStream:
    """Build a MediaStream object based on group + config settings."""
    group = get_group(song.request_msg.chat.id)
    quality = (config.QUALITY or "high").lower()

    audio_map = {
        "low": AudioQuality.LOW,
        "medium": AudioQuality.MEDIUM,
        "high": AudioQuality.HIGH,
    }
    video_map = {
        "low": VideoQuality.SD_480p,
        "medium": VideoQuality.HD_720p,
        "high": VideoQuality.HD_720p,  # 1080p not recommended for VC
    }

    if quality not in audio_map:
        log.warning(f"Invalid quality '{quality}', defaulting to high.")
        quality = "high"

    audio = audio_map[quality]

    if group["stream_mode"] == "video":
        return MediaStream(
            song.remote,
            audio,
            video_map[quality],
            headers=song.headers or None,
        )
    else:
        return MediaStream(
            song.remote,
            audio,
            video_flags=MediaStream.Flags.IGNORE,
            headers=song.headers or None,
        )