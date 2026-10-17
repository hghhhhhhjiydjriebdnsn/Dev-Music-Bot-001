"""
Music Player, Telegram Voice Chat Bot
© 2026 DevXGhost | https://t.me/DevXGhost

Licensed under the GNU Affero General Public License v3.0
"""

import sys
import os


def _prompt_int(prompt: str) -> int:
    """Prompt for an integer with retry."""
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("❌ Invalid input. Please enter a number.")


def main() -> None:
    print("=" * 60)
    print("  Pyrogram Session String Generator")
    print("  © 2026 DevXGhost | https://t.me/DevXGhost")
    print("=" * 60)
    print()
    print("Get your API_ID and API_HASH from:")
    print("  → https://my.telegram.org → API Development Tools")
    print()

    api_id = _prompt_int("API ID: ")
    api_hash = input("API HASH: ").strip()

    if not api_hash or len(api_hash) != 32:
        print("❌ API_HASH looks invalid (expected 32 characters).")
        sys.exit(1)

    try:
        from pyrogram import Client
    except ImportError:
        print("❌ Pyrogram not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    print()
    print("📱 You will be asked for your phone number, then a code sent")
    print("   by Telegram. If you have 2FA enabled, you'll also need your")
    print("   password.")
    print()

    try:
        app = Client(
            "session_gen",
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True,
        )
        with app:
            session_string = app.export_session_string()
    except Exception as e:
        print(f"\n❌ Failed to generate session: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  ✅ SESSION STRING GENERATED")
    print("=" * 60)
    print()
    print(session_string)
    print()
    print("=" * 60)
    print("Copy the string above and paste it as SESSION in your .env file.")
    print("⚠️  DO NOT share this string with anyone!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled.")
        sys.exit(1)