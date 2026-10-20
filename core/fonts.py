"""Unicode text styles for the PIHU MUSIC interface.

Pure string helpers: letters are mapped to styled Unicode lookalikes, everything
else (digits, punctuation, emoji, existing styled glyphs) passes through.
Never apply these to command names, URLs or HTML tags.
"""

_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = _LOWER.upper()
_SMALLCAPS = dict(zip(_LOWER, "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ"))


def _block(upper_start, lower_start):
    table = {}
    for i, ch in enumerate(_UPPER):
        table[ch] = chr(upper_start + i)
    for i, ch in enumerate(_LOWER):
        table[ch] = chr(lower_start + i)
    return table


_BOLD = _block(0x1D5D4, 0x1D5EE)        # 𝗔𝗮  sans-serif bold
_ITALIC = _block(0x1D608, 0x1D622)      # 𝘈𝘢  sans-serif italic
_BOLD_ITALIC = _block(0x1D63C, 0x1D656)  # 𝘼𝙖  sans-serif bold italic
_MONO = _block(0x1D670, 0x1D68A)        # 𝙰𝚊  monospace
_BOLD_DIGITS = {str(d): chr(0x1D7EC + d) for d in range(10)}  # 𝟬..𝟵


def _apply(text, table):
    return "".join(table.get(ch, ch) for ch in str(text))


def sc(text):
    """ꜱᴍᴀʟʟ ᴄᴀᴘs (upper-case letters become normal capitals mapped to small caps too)."""
    return "".join(_SMALLCAPS.get(ch.lower(), ch) if ch.isascii() and ch.isalpha() else ch for ch in str(text))


def bold(text):
    return _apply(text, {**_BOLD, **_BOLD_DIGITS})


def italic(text):
    return _apply(text, _ITALIC)


def bold_italic(text):
    return _apply(text, _BOLD_ITALIC)


def mono(text):
    return _apply(text, _MONO)
