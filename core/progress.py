"""Live "now playing" progress line.

The player card carries a line like ``1:12 ━━━●────── 3:45``. A small
background task per chat edits the card every few seconds so the dot moves and
the elapsed time stays current. Pause/resume freeze and continue the clock.
The task stops by itself when the song is no longer the chat's current song.
"""

import asyncio
import logging
import time

log = logging.getLogger("ogmusic")

INTERVAL = 8          # seconds between edits (stays well inside Telegram limits)
BAR_WIDTH = 12
MAX_FAILURES = 3      # stop after this many failed edits in a row (message deleted etc.)

_TRACKERS = {}


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def bar_line(elapsed, total, paused=False):
    """HTML for the progress line. total == 0 means unknown length (live/radio)."""
    if total and total > 0:
        elapsed = min(max(0, elapsed), total)
        pos = min(BAR_WIDTH - 1, int(elapsed / total * (BAR_WIDTH - 1)))
        bar = "━" * pos + "●" + "─" * (BAR_WIDTH - 1 - pos)
        text = f"{fmt_time(elapsed)} {bar} {fmt_time(total)}"
    else:
        text = f"{fmt_time(elapsed)} ●{'─' * (BAR_WIDTH - 1)} live"
    line = f"<code>{text}</code>"
    if paused:
        line += " · <i>ᴘᴀᴜsᴇᴅ</i>"
    return line


class _Tracker:
    def __init__(self, chat_id, song, message, is_photo, render, total, started):
        self.chat_id = chat_id
        self.song = song
        self.message = message
        self.is_photo = is_photo
        self.render = render          # callable(progress_line_html) -> full caption html
        self.total = total
        self.started = started
        self.paused_at = None
        self.paused_total = 0.0
        self.wake = asyncio.Event()
        self.last = None
        self.failures = 0
        self.task = None

    def elapsed(self):
        now = self.paused_at if self.paused_at is not None else time.monotonic()
        return now - self.started - self.paused_total

    async def _edit(self, caption):
        from config import config
        if config.BOT_TOKEN:
            from core.premium import _api, _bot_html, _plain_html, build_keyboard, decorate_html
            from core.ui import _keyboard_controls
            markup = _keyboard_controls(self.chat_id)
            method, key = ("editMessageCaption", "caption") if self.is_photo else ("editMessageText", "text")
            rich = decorate_html(caption)
            for body, icons in ((rich, True), (_plain_html(rich), False)):
                payload = {"chat_id": self.chat_id, "message_id": self.message.id,
                           key: _bot_html(body), "parse_mode": "HTML",
                           "reply_markup": build_keyboard(markup, icons)}
                if not self.is_photo:
                    payload["link_preview_options"] = {"is_disabled": True}
                if await _api(method, payload) is not None:   # {} == "not modified" == fine
                    return True
            return False
        from pyrogram import enums
        try:
            if self.is_photo:
                await self.message.edit_caption(caption, parse_mode=enums.ParseMode.HTML)
            else:
                await self.message.edit_text(caption, parse_mode=enums.ParseMode.HTML,
                                             disable_web_page_preview=True)
            return True
        except Exception:
            return False

    async def run(self):
        from core.groups import get_group
        try:
            while True:
                try:
                    await asyncio.wait_for(self.wake.wait(), INTERVAL)
                except asyncio.TimeoutError:
                    pass
                self.wake.clear()
                if _TRACKERS.get(self.chat_id) is not self:
                    return
                group = get_group(self.chat_id)
                if group.get("now_playing") is not self.song or not group.get("is_playing"):
                    return
                elapsed = self.elapsed()
                if self.total and elapsed > self.total + 20:
                    return  # stream-ended handler will start the next track or clean up
                line = bar_line(elapsed, self.total, self.paused_at is not None)
                if line == self.last:
                    continue
                if await self._edit(self.render(line)):
                    self.last = line
                    self.failures = 0
                else:
                    self.failures += 1
                    if self.failures >= MAX_FAILURES:
                        return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("progress updater stopped (%s)", type(exc).__name__)
        finally:
            if _TRACKERS.get(self.chat_id) is self:
                _TRACKERS.pop(self.chat_id, None)


def begin(chat_id, song, message, is_photo, render, total, started=None):
    """Start (or restart) live progress for the chat's current player card."""
    stop(chat_id)
    tracker = _Tracker(chat_id, song, message, is_photo, render, total,
                       started if started is not None else time.monotonic())
    tracker.last = bar_line(0, total)
    _TRACKERS[chat_id] = tracker
    tracker.task = asyncio.ensure_future(tracker.run())
    return tracker


def stop(chat_id):
    tracker = _TRACKERS.pop(chat_id, None)
    if tracker and tracker.task and not tracker.task.done():
        tracker.task.cancel()


def pause(chat_id):
    tracker = _TRACKERS.get(chat_id)
    if tracker and tracker.paused_at is None:
        tracker.paused_at = time.monotonic()
        tracker.wake.set()          # show "paused" right away


def resume(chat_id):
    tracker = _TRACKERS.get(chat_id)
    if tracker and tracker.paused_at is not None:
        tracker.paused_total += time.monotonic() - tracker.paused_at
        tracker.paused_at = None
        tracker.wake.set()
