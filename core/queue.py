"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import random
import asyncio
import html
import logging
from typing import Optional

log = logging.getLogger("queue")


class Queue(asyncio.Queue):
    """asyncio.Queue with list-like and shuffle helpers."""

    def __init__(self, maxsize: int = 0) -> None:
        super().__init__(maxsize=maxsize)

    # --------------------------------------------------------
    #  MUTATION HELPERS
    # --------------------------------------------------------
    def clear(self) -> None:
        """Remove all items, resetting internal state safely."""
        while not self.empty():
            try:
                self.get_nowait()
                self.task_done()
            except asyncio.QueueEmpty:
                break

    def shuffle(self) -> "Queue":
        """Shuffle the queue in place (Fisher-Yates)."""
        items = list(self._queue)
        random.shuffle(items)
        self.clear()
        for item in items:
            self.put_nowait(item)
        return self

    def to_list(self) -> list:
        """Return a snapshot list of items (safer than list(queue))."""
        return list(self._queue)

    # --------------------------------------------------------
    #  SYNC ITERATION (for export, display, etc.)
    # --------------------------------------------------------
    def __iter__(self):
        return iter(self.to_list())

    def __len__(self) -> int:
        return self.qsize()

    def __getitem__(self, index):
        return self._queue[index]

    # --------------------------------------------------------
    #  STRING REPRESENTATION
    # --------------------------------------------------------
    def __str__(self) -> str:
        items = self.to_list()
        if not items:
            return "Queue is empty."

        lines: list[str] = []
        for i, item in enumerate(items[:10], start=1):
            title = html.escape(getattr(item, "title", None) or "Unknown")
            source = getattr(item, "source", None) or ""
            if source:
                lines.append(f"<b>{i}.</b> <a href=\"{html.escape(source)}\">{title}</a>")
            else:
                lines.append(f"<b>{i}.</b> {title}")

            requested_by = getattr(item, "requested_by", None)
            if requested_by and getattr(requested_by, "mention", None):
                lines.append(f"   ↳ {requested_by.mention}")
            else:
                sender_chat = getattr(getattr(item, "request_msg", None), "sender_chat", None)
                if sender_chat and getattr(sender_chat, "title", None):
                    lines.append(f"   ↳ {sender_chat.title}")

        if len(items) > 10:
            lines.append(f"\n<i>…and {len(items) - 10} more</i>")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<Queue size={len(self)}>"