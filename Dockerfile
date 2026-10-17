# ============================================================
#  Music Player, Telegram Voice Chat Bot
#  © 2026 DevXGhost | https://t.me/DevXGhost
# ============================================================

FROM python:3.11-slim-bookworm

# ------------------------------------------------------------
#  ENV
# ------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=UTC \
    SKIP_INSTALL=1

# ------------------------------------------------------------
#  SYSTEM DEPENDENCIES
# ------------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        tzdata \
        procps \
 && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
#  WORKDIR
# ------------------------------------------------------------
WORKDIR /app

# ------------------------------------------------------------
#  PYTHON DEPENDENCIES
# ------------------------------------------------------------
COPY requirements.txt .

RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# ------------------------------------------------------------
#  VERIFY yt-dlp
# ------------------------------------------------------------
RUN yt-dlp --version

# ------------------------------------------------------------
#  COPY PROJECT
# ------------------------------------------------------------
COPY . .

# ------------------------------------------------------------
#  PREPARE STARTUP
# ------------------------------------------------------------
RUN chmod +x startup.sh \
 && mkdir -p downloads

# ------------------------------------------------------------
#  RUN AS ROOT (Railway volumes ke liye zaroori)
#  Agar non-root use karna hai, toh RAILWAY_RUN_UID=0 set karo
# ------------------------------------------------------------
# USER appuser  # ← Railway volumes ke liye comment out

# ------------------------------------------------------------
#  HEALTHCHECK (Railway ise ignore karega, but Docker local ke liye)
# ------------------------------------------------------------
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f "python.*main.py" > /dev/null || exit 1

# ------------------------------------------------------------
#  ENTRYPOINT
# ------------------------------------------------------------
ENTRYPOINT ["/app/startup.sh"]