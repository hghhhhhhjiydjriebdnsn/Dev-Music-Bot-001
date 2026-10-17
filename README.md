<h1 align="center">
  <b>⭐️ Music Player ⭐️</b>
</h1>

<h3 align="center">
  A Telegram Voice Chat Music Bot written in Python
  using PyrogramMod & PyTgCalls
</h3>

<p align="center">
  <a href="https://python.org">
    <img src="https://forthebadge.com/images/badges/made-with-python.svg" alt="made-with-python">
  </a>
  <br>
  <img src="https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/Developer-DevXGhost-purple?style=for-the-badge" alt="Developer">
  <br>
  <img src="https://img.shields.io/github/forks/DevXGhost/MusicPlayer?style=for-the-badge" alt="Forks">
  <img src="https://img.shields.io/github/stars/DevXGhost/MusicPlayer?style=for-the-badge" alt="Stars">
  <img src="https://img.shields.io/github/repo-size/DevXGhost/MusicPlayer?style=for-the-badge" alt="Repo Size">
</p>

<p align="center">
  <b>Developed By <a href="https://t.me/DevXGhost">@DevXGhost</a></b>
</p>

---

## ✨ Features

### ⚡️ Fast & Light
Streams audio/video on the fly without downloading full files. Uses
`yt-dlp` for extraction and `ffmpeg` for streaming.

### 👮 Safe and Handy
Restricts sensitive commands to group admins and bot sudoers only.

### 🗑 Clean and Spam-Free
Auto-deletes command messages and old playing messages to keep chats clean.

### 😎 Cool Controls
Supports skip, pause, resume, mute, unmute, loop, shuffle, and mode-switch
(audio/video) at any time.

### 🖼 Cool Thumbnails
Generates a dynamic thumbnail for each playing song using PIL.

### 😉 Streams Whatever You Like
- YouTube videos (any duration)
- YouTube live streams
- YouTube playlists
- Spotify tracks & playlists (optional)
- Direct audio/video files
- Custom radio/m3u8 live streams
- Telegram audio/video file replies

### 📊 Multi-Chat Support
Each group has its own independent queue. Stream different songs in
different chats simultaneously.

### 🗣 Speaks Multiple Languages
Supports 13 languages (Arabic, Bengali, Chinese, German, English, French,
Hindi, Japanese, Dutch, Russian, Telugu, Turkish, and more).

### 🚂 Railway-Ready
Optimized Dockerfile and `railway.toml` for one-click Railway deployment.

---

## 🚀 Deploy on Railway

### 1. Fork this Repository

Click **Fork** at the top right of this GitHub page.

### 2. Create a Railway Project

1. Go to [railway.app](https://railway.app)
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your forked repository
4. Railway auto-detects the `Dockerfile` and builds it

### 3. Add Environment Variables

In Railway Dashboard → your service → **Variables** tab → **RAW Editor**,
paste the following and fill in your values:

```env
API_ID=123456
API_HASH=your_api_hash_here
SESSION=your_pyrogram_session_string
BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_id
SUDOERS=111111111 222222222
LOG_CHANNEL=-1001234567890
PREFIX=!
LANGUAGE=en
QUALITY=high
STREAM_MODE=audio
ADMINS_ONLY=False
QUEUE_LIMIT=20
