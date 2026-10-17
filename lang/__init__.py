"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import os
import json
import logging
from typing import Dict, Any

log = logging.getLogger("lang")

# ============================================================
#  LANGUAGE FILE LOADER (cached)
# ============================================================
_LANG_DIR = os.path.join(os.path.dirname(__file__))
_DEFAULT_LANG = "en"
_CACHE: Dict[str, Dict[str, Any]] = {}


def _validate_lang_code(lang: str) -> str:
    """Ensure the lang code has no path traversal and exists."""
    if not lang or not isinstance(lang, str):
        return _DEFAULT_LANG
    # Only allow alphanumeric (prevents ../../ traversal)
    clean = "".join(c for c in lang.lower() if c.isalnum())
    if not clean:
        return _DEFAULT_LANG
    if not os.path.exists(os.path.join(_LANG_DIR, f"{clean}.json")):
        log.warning(f"Language '{clean}' not found, falling back to {_DEFAULT_LANG}")
        return _DEFAULT_LANG
    return clean


def _load_file(lang_code: str) -> Dict[str, Any]:
    """Read and parse a language file. Never raises."""
    path = os.path.join(_LANG_DIR, f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"Language file not found: {path}")
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {path}: {e}")
    except Exception as e:
        log.exception(f"Failed to load language {lang_code}: {e}")
    return {}


def load(lang: str) -> Dict[str, Any]:
    """
    Load and cache a language dictionary.
    Falls back to English, then to an empty dict.
    """
    code = _validate_lang_code(lang)

    if code in _CACHE:
        return _CACHE[code]

    data = _load_file(code)

    # Fallback to English if the loaded file is empty
    if not data and code != _DEFAULT_LANG:
        data = _load_file(_DEFAULT_LANG)

    _CACHE[code] = data
    return data


def clear_cache() -> None:
    """Clear the language cache (useful during development)."""
    _CACHE.clear()
    log.info("Language cache cleared.")


def available_languages() -> list:
    """Return a list of all available language codes."""
    try:
        return sorted(
            f.replace(".json", "")
            for f in os.listdir(_LANG_DIR)
            if f.endswith(".json")
        )
    except OSError:
        return []