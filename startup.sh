#!/usr/bin/env bash
#
# Music Player, Telegram Voice Chat Bot
# © 2026 DevXGhost | https://t.me/DevXGhost
#
# Licensed under the GNU Affero General Public License v3.0
#

set -euo pipefail

# ============================================================
#  CONFIG
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PIP_BIN="${PIP_BIN:-pip3}"

# ============================================================
#  BANNER
# ============================================================
cat << "EOF"

██████╗ ███████╗██╗   ██╗██╗  ██╗ ██████╗ ██╗  ██╗ ██████╗ ███████╗████████╗
██╔══██╗██╔════╝██║   ██║╚██╗██╔╝██╔════╝ ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝
██║  ██║█████╗  ██║   ██║ ╚███╔╝ ██║  ███╗███████║██║   ██║███████╗   ██║   
██║  ██║██╔══╝  ╚██╗ ██╔╝ ██╔██╗ ██║   ██║██╔══██║██║   ██║╚════██║   ██║   
██████╔╝███████╗ ╚████╔╝ ██╔╝ ██╗╚██████╔╝██║  ██║╚██████╔╝███████║   ██║   
╚═════╝ ╚══════╝  ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   

                    Music Player — Voice Chat Bot
                    © 2026 DevXGhost | t.me/DevXGhost

EOF

# ============================================================
#  VALIDATE ENV
# ============================================================
echo ">> Validating environment..."

for var in API_ID API_HASH SESSION BOT_TOKEN; do
    if [ -z "${!var:-}" ] && ! grep -q "^${var}=" .env 2>/dev/null; then
        echo "⚠️  WARNING: $var is not set in environment or .env file"
    fi
done

if [ ! -f ".env" ] && [ -z "${API_ID:-}" ]; then
    echo "❌ ERROR: No .env file found and no environment variables set."
    echo "   Copy sample.env to .env and fill in your credentials."
    exit 1
fi

# ============================================================
#  INSTALL REQUIREMENTS
# ============================================================
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    echo ">> Installing Python dependencies..."
    "$PIP_BIN" install --no-cache-dir -r requirements.txt
else
    echo ">> Skipping dependency install (SKIP_INSTALL=1)"
fi

# ============================================================
#  VERIFY YT-DLP
# ============================================================
if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "⚠️  yt-dlp not found in PATH — installing..."
    "$PIP_BIN" install --no-cache-dir yt-dlp
fi

# ============================================================
#  VERIFY FFMPEG
# ============================================================
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "⚠️  ffmpeg not found — some features may not work."
    echo "   Install with: apt-get install -y ffmpeg"
fi

# ============================================================
#  CREATE DIRECTORIES
# ============================================================
mkdir -p downloads
echo ">> Working directory: $SCRIPT_DIR"

# ============================================================
#  START BOT
# ============================================================
echo ">> Starting Music Player Userbot..."
exec "$PYTHON_BIN" main.py
