"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import os
import re
import math
import time
import random
import asyncio
import logging
from typing import List, Tuple, Optional, AsyncIterator

import aiohttp
import aiofiles
import yt_dlp
from PIL import Image, ImageDraw, ImageFont
from pyrogram import enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup

from config import config
from core.song import Song
from core.groups import get_group

log = logging.getLogger("funcs")

# ============================================================
#  SPOTIFY (optional)
# ============================================================
sp = None
if config.SPOTIFY and config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET:
    try:
        from spotipy import Spotify
        from spotipy.oauth2 import SpotifyClientCredentials

        sp = Spotify(
            client_credentials_manager=SpotifyClientCredentials(
                config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET
            )
        )
        log.info("Spotify client initialized.")
    except Exception as e:
        log.warning(f"Spotify init failed: {e}. Spotify disabled.")
        config.SPOTIFY = False
        sp = None
else:
    if config.SPOTIFY:
        log.warning("SPOTIFY enabled but credentials missing — disabling.")
        config.SPOTIFY = False

# ============================================================
#  THEMES (for generate_cover)
# ============================================================
THEMES = ["blue", "black", "red", "green", "grey", "orange", "pink", "yellow"]

# ============================================================
#  YT-DLP SEARCH ENGINE (replaces youtube-search-python)
# ============================================================
_search_opts = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,
    "default_search": "ytsearch1",
    "noplaylist": True,
    "skip_download": True,
    "nocheckcertificate": True,
    "geo_bypass": True,
    "source_address": "0.0.0.0",
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _yt_search(query: str) -> Optional[dict]:
    """Search YouTube via yt-dlp. Returns first video info or None."""
    try:
        with yt_dlp.YoutubeDL(_search_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if not info:
                return None
            # For ytsearch1, info is the video dict directly
            if "entries" in info:
                entries = list(info["entries"] or [])
                return entries[0] if entries else None
            return info
    except Exception as e:
        log.warning(f"yt-dlp search failed for '{query}': {e}")
        return None


# ============================================================
#  SEARCH
# ============================================================
async def search(message: Message) -> Optional[Song]:
    """Extract a Song from a message or reply."""
    query = ""
    reply = message.reply_to_message

    # --- Reply with media ---
    if reply:
        if reply.text:
            query = reply.text.strip()
        elif reply.media:
            media = reply.audio or reply.video or reply.document
            if not media:
                return None
            lel = await message.reply_text("`Trying To Download...`")
            try:
                file = await reply.download(
                    progress=progress_bar,
                    progress_args=("Downloading...", lel, time.time()),
                )
            except Exception as e:
                log.exception("Reply media download failed")
                await lel.edit_text(f"⚠️ Download failed: `{e}`")
                return None
            await lel.delete()
            # reply.link may be None in PM — fall back to file path
            source = reply.link or file
            return Song(
                {
                    "title": media.file_name or "N/A",
                    "source": source,
                    "remote": file,
                },
                message,
            )
    else:
        query = extract_args(message.text or "")

    if not query:
        return None

    # --- YouTube URL ---
    is_yt_url, url = check_yt_url(query)
    if is_yt_url:
        return Song(url, message)

    # --- Spotify track ---
    if config.SPOTIFY and sp and "open.spotify.com/track" in query:
        try:
            track_id = query.split("open.spotify.com/track/")[1].split("?")[0]
            track = sp.track(track_id)
            artists = ", ".join(a["name"] for a in track["artists"])
            query = f"{artists} - {track['name']}"
        except Exception as e:
            log.warning(f"Spotify lookup failed: {e}")
            return None

    # --- Search via yt-dlp ---
    video = _yt_search(f"ytsearch1:{query}")
    if video and video.get("webpage_url"):
        return Song(video["webpage_url"], message)

    return None


# ============================================================
#  YOUTUBE URL CHECK
# ============================================================
def check_yt_url(text: str) -> Tuple[bool, Optional[str]]:
    pattern = re.compile(
        r"^((?:https?:)?//)?((?:www|m)\.)?((?:youtube\.com|youtu\.be))"
        r"(/(?:[\w\-]+\?v=|embed/|v/)?)([\w\-]+)([a-zA-Z0-9\-_]+)?$"
    )
    matches = re.findall(pattern, text)
    if not matches:
        return False, None
    return True, "".join(list(matches[0]))


# ============================================================
#  ARG EXTRACTION
# ============================================================
def extract_args(text: str) -> str:
    if not text or " " not in text:
        return ""
    return text.split(" ", 1)[1].strip()


# ============================================================
#  PROGRESS BAR
# ============================================================
async def progress_bar(current, total, ud_type, msg, start):
    now = time.time()
    if total == 0:
        return
    if round((now - start) % 3) != 0 and current != total:
        return
    speed = current / max(now - start, 1e-3)
    percentage = current * 100 / total
    time_to_complete = round((total - current) / speed) * 1000
    time_to_complete = TimeFormatter(time_to_complete)

    filled = math.floor(percentage / 10)
    bar = "█" * filled + "░" * (10 - filled)

    current_message = (
        f"**{ud_type}** `{round(percentage, 2)}%`\n"
        f"`[{bar}]`\n"
        f"**Done**: `{humanbytes(current)}` | **Total**: `{humanbytes(total)}`\n"
        f"**Speed**: `{humanbytes(speed)}/s` | **ETA**: `{time_to_complete}`"
    )
    if msg:
        try:
            await msg.edit(text=current_message)
        except Exception:
            pass


# ============================================================
#  HUMAN READABLE BYTES
# ============================================================
def humanbytes(size: int) -> str:
    if not size:
        return ""
    power = 2 ** 10
    n = 0
    units = {0: " ", 1: "K", 2: "M", 3: "G", 4: "T"}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {units[n]}B"


# ============================================================
#  DELETE MESSAGES
# ============================================================
async def delete_messages(messages: List[Message]):
    await asyncio.sleep(config.AUTO_DELETE_DELAY if hasattr(config, "AUTO_DELETE_DELAY") else 10)
    for msg in messages:
        if msg and msg.chat.type == enums.ChatType.SUPERGROUP:
            try:
                await msg.delete()
            except Exception:
                pass


# ============================================================
#  TIME FORMATTER
# ============================================================
def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")
    if milliseconds:
        parts.append(f"{milliseconds}ms")
    return " ".join(parts) or "0s"


# ============================================================
#  IMAGE RESIZE
# ============================================================
def change_image_size(max_width, max_height, image):
    width_ratio = max_width / image.size[0]
    height_ratio = max_height / image.size[1]
    new_width = int(width_ratio * image.size[0])
    new_height = int(height_ratio * image.size[1])
    return image.resize((new_width, new_height))


# ============================================================
#  GENERATE COVER (thumbnail)
# ============================================================
async def generate_cover(title: str, ctitle: str, chatid: int, thumbnail: Optional[str]) -> Optional[str]:
    """
    Generate a thumbnail image for the playing song.
    Returns the file path to the final PNG, or None on failure.
    """
    final_path = f"final{chatid}.png"
    thumb_path = f"thumb{chatid}.png"
    temp_path = f"temp{chatid}.png"

    try:
        # --- Download thumbnail ---
        if not thumbnail:
            raise ValueError("No thumbnail URL provided")

        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    raise ValueError(f"Thumbnail HTTP {resp.status}")
                async with aiofiles.open(thumb_path, mode="wb") as f:
                    await f.write(await resp.read())

        # --- Compose ---
        theme = random.choice(THEMES)
        theme_path = f"theme/{theme}.PNG"
        if not os.path.exists(theme_path):
            theme_path = "theme/logo.PNG"
        if not os.path.exists(theme_path):
            raise ValueError("No theme image available")

        ctitle = await special_to_normal(ctitle or "Music")

        image1 = Image.open(thumb_path)
        image2 = Image.open(theme_path)
        image3 = change_image_size(1280, 720, image1)
        image4 = change_image_size(1280, 720, image2)
        image5 = image3.convert("RGBA")
        image6 = image4.convert("RGBA")
        Image.alpha_composite(image5, image6).save(temp_path)
        img = Image.open(temp_path)

        draw = ImageDraw.Draw(img)

        # Font with fallback
        font_path = "theme/font.ttf"
        try:
            font = ImageFont.truetype(font_path, 85)
            font2 = ImageFont.truetype(font_path, 60)
        except (OSError, IOError):
            log.warning("theme/font.ttf missing — using default font")
            font = ImageFont.load_default()
            font2 = ImageFont.load_default()

        draw.text(
            (20, 45),
            f"Playing on: {ctitle[:14]}...",
            fill="white",
            stroke_width=1,
            stroke_fill="white",
            font=font2,
        )
        draw.text(
            (25, 595),
            f"{title[:27]}...",
            fill="white",
            stroke_width=2,
            stroke_fill="white",
            font=font,
        )
        img.save(final_path)
        return final_path

    except Exception as e:
        log.exception(f"generate_cover failed: {e}")
        # Fallback to logo if available
        if os.path.exists("theme/logo.PNG"):
            return "theme/logo.PNG"
        return None

    finally:
        # Cleanup temp files
        for path in (thumb_path, temp_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


# ============================================================
#  UNICODE SMALL CAPS
# ============================================================
_SMALL_CAPS_MAP = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ғ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "s", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
    "A": "ᴀ", "B": "ʙ", "C": "ᴄ", "D": "ᴅ", "E": "ᴇ", "F": "ғ", "G": "ɢ",
    "H": "ʜ", "I": "ɪ", "J": "ᴊ", "K": "ᴋ", "L": "ʟ", "M": "ᴍ", "N": "ɴ",
    "O": "ᴏ", "P": "ᴘ", "Q": "ǫ", "R": "ʀ", "S": "s", "T": "ᴛ", "U": "ᴜ",
    "V": "ᴠ", "W": "ᴡ", "X": "x", "Y": "ʏ", "Z": "ᴢ",
}


def small_caps(text: str) -> str:
    """Convert ASCII letters to Unicode Small Caps."""
    if not text:
        return ""
    return "".join(_SMALL_CAPS_MAP.get(ch, ch) for ch in text)


# ============================================================
#  PREMIUM EMOJI WRAPPER
# ============================================================
def premium_emoji(fallback: str, emoji_id: Optional[str] = None) -> str:
    """
    Wrap an emoji in a <tg-emoji> tag for Premium emoji.
    Falls back to plain Unicode if no ID is provided.
    """
    if not emoji_id:
        return fallback
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# ============================================================
#  COLORED BUTTON HELPER
# ============================================================
def colored_button(text: str, callback_data: str = None, url: str = None,
                   style: str = "primary", icon_emoji_id: Optional[str] = None):
    """
    Build an InlineKeyboardButton with color style (Bot API 9.4+).
    PyrogramMod 2.x may or may not support `style` — we pass it
    as extra kwargs; if unsupported, Pyrogram will ignore or error.
    """
    kwargs = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if style:
        kwargs["style"] = style  # primary / success / danger
    if icon_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_emoji_id
    return InlineKeyboardButton(**kwargs)


# ============================================================
#  MOJIBAKE FIX (kept for backwards compatibility)
# ============================================================
async def special_to_normal(ctitle: str) -> str:
    """
    Normalize stylized Unicode (bold, italic, monospace) into ASCII.
    Previous implementation had broken Cyrillic mojibake — replaced
    with proper codepoint ranges.
    """
    if not ctitle:
        return ""
    result = []
    for ch in ctitle:
        cp = ord(ch)
        # Mathematical Bold: A-Z, a-z
        if 0x1D400 <= cp <= 0x1D419 or 0x1D41A <= cp <= 0x1D433:
            result.append(chr(cp - 0x1D400 + ord('A') if cp < 0x1D41A else cp - 0x1D41A + ord('a')))
        # Mathematical Italic
        elif 0x1D434 <= cp <= 0x1D44D or 0x1D44E <= cp <= 0x1D467:
            result.append(chr(cp - 0x1D434 + ord('A') if cp < 0x1D44E else cp - 0x1D44E + ord('a')))
        # Mathematical Bold Italic
        elif 0x1D468 <= cp <= 0x1D481 or 0x1D482 <= cp <= 0x1D49B:
            result.append(chr(cp - 0x1D468 + ord('A') if cp < 0x1D482 else cp - 0x1D482 + ord('a')))
        # Mathematical Sans-Serif
        elif 0x1D5A0 <= cp <= 0x1D5B9 or 0x1D5BA <= cp <= 0x1D5D3:
            result.append(chr(cp - 0x1D5A0 + ord('A') if cp < 0x1D5BA else cp - 0x1D5BA + ord('a')))
        # Mathematical Sans-Serif Bold
        elif 0x1D5D4 <= cp <= 0x1D5ED or 0x1D5EE <= cp <= 0x1D607:
            result.append(chr(cp - 0x1D5D4 + ord('A') if cp < 0x1D5EE else cp - 0x1D5EE + ord('a')))
        # Mathematical Sans-Serif Italic
        elif 0x1D608 <= cp <= 0x1D621 or 0x1D622 <= cp <= 0x1D63B:
            result.append(chr(cp - 0x1D608 + ord('A') if cp < 0x1D622 else cp - 0x1D622 + ord('a')))
        # Mathematical Monospace
        elif 0x1D670 <= cp <= 0x1D689 or 0x1D68A <= cp <= 0x1D6A3:
            result.append(chr(cp - 0x1D670 + ord('A') if cp < 0x1D68A else cp - 0x1D68A + ord('a')))
        # Fullwidth
        elif 0xFF21 <= cp <= 0xFF3A or 0xFF41 <= cp <= 0xFF5A:
            result.append(chr(cp - 0xFF21 + ord('A') if cp < 0xFF41 else cp - 0xFF41 + ord('a')))
        # Mathematical Bold Digits
        elif 0x1D7CE <= cp <= 0x1D7D7:
            result.append(chr(cp - 0x1D7CE + ord('0')))
        else:
            result.append(ch)
    return "".join(result)


# ============================================================
#  YOUTUBE PLAYLIST
# ============================================================
async def get_youtube_playlist(pl_url: str, message: Message) -> AsyncIterator[Song]:
    ydl_opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "ignoreerrors": True,
        "noplaylist": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(pl_url, download=False)
    except Exception as e:
        log.exception(f"YouTube playlist extraction failed: {e}")
        return

    if not info or "entries" not in info:
        return

    for entry in info.get("entries") or []:
        if not entry:
            continue
        # Build full URL from ID if needed
        url = entry.get("url") or entry.get("webpage_url")
        if not url and entry.get("id"):
            url = f"https://www.youtube.com/watch?v={entry['id']}"
        if not url:
            continue
        song = Song(url, message)
        song.title = entry.get("title") or "Unknown Title"
        yield song


# ============================================================
#  SPOTIFY PLAYLIST
# ============================================================
async def get_spotify_playlist(pl_url: str, message: Message) -> AsyncIterator[Song]:
    if not sp:
        return

    try:
        pl_id = re.split(r"[^a-zA-Z0-9]", pl_url.split("spotify.com/playlist/")[1])[0]
    except (IndexError, AttributeError):
        return

    offset = 0
    max_pages = 50  # safety limit
    pages = 0
    while pages < max_pages:
        try:
            resp = sp.playlist_items(
                pl_id,
                fields="items.track.name,items.track.artists.name",
                offset=offset,
                additional_types=("track",),
            )
        except Exception as e:
            log.warning(f"Spotify page fetch failed: {e}")
            break

        items = resp.get("items") or []
        if not items:
            break

        for item in items:
            track = item.get("track")
            if not track:
                continue
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            song_name = f"{artists} - {track['name']}"
            video = _yt_search(f"ytsearch1:{song_name}")
            if video and video.get("webpage_url"):
                song = Song(video["webpage_url"], message)
                song.title = video.get("title") or song_name
                yield song

        offset += len(items)
        pages += 1