# MAHI MUSIC

A premium-style Telegram voice-chat music bot, built on the uploaded MusicPlayer project. Existing commands and voice-chat playback are retained; song-name search now uses your three supplied APIs with automatic fallback.

## What changed

OG branding, a dark violet/cyan now-playing cover, search-result buttons, song downloads, and inline playback controls. Pause, resume, skip, stop, repeat, shuffle, queue, mute/unmute, audio/video mode, languages, queue import/export, Telegram media, radio/live URLs, YouTube links/playlists and optional Spotify metadata support remain available.

The premium interface is a visual/feature upgrade, not a paid subscription or a way to unlock Telegram Premium. Audio-only API songs remain audio even when a group is in video mode.

## Quick setup

Use Linux with **Python 3.11**, FFmpeg, and a persistent worker process. Python 3.12 is also checked in the supplied validation environment. No external database server is required. Queues and transient playback state reset on restart; panel-managed access/loop preferences and welcome settings use local SQLite storage.

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp sample.env .env
# Fill .env with your own values before starting.
python main.py
```

Set `API_ID` and `API_HASH` from [Telegram's developer page](https://my.telegram.org/apps), `SESSION` for a dedicated assistant **user account**, and preferably `BOT_TOKEN` from @BotFather. Generate your assistant session locally with `python genStr.py`; treat the resulting string like a password. `BOT_TOKEN` is optional for legacy userbot mode, but recommended for the full bot UI and colored buttons.

Add the bot and assistant to your supergroup. Grant the bot message-management permissions if automatic message cleanup is wanted. Grant the assistant permission to join/speak; making it an admin with voice-chat management permission also allows automatic voice-chat creation when supported. Start a group voice chat, then try `/play Kamar me dagi`. A bot account alone cannot provide the assistant's voice-chat session.

`SUDOERS` contains only your trusted Telegram user IDs, separated by spaces. `ADMINS_ONLY=true` restricts song requests; playback controls remain admin/sudo-only. Prefixes default to `/ !`. Never commit `.env` or session files.

## Docker

```bash
docker build -t og-music-bot .
docker run -d --name og-music-bot --restart unless-stopped --env-file .env og-music-bot
```

The container runs this updated source, not a fresh upstream clone. It runs as an unprivileged user. `.dockerignore` excludes `.env` and session files; pass credentials only at runtime. If another instance is using the same assistant session, stop it first.

## Commands

| Command | Action |
|---|---|
| `/start`, `/help`, `/premium` | Home, command list, feature showcase |
| `/search song name` | Browse matching songs with actions |
| `/play song name` | API-backed voice-chat stream or enqueue |
| `/song song name`, `/download song name` | Download/send the audio file |
| `/play` replying to audio/video | Play Telegram media |
| `/play YouTube-URL` | Original explicit-link extraction |
| `/radio URL`, `/stream URL` | Radio/live stream |
| `/playlist URL` | Original YouTube/Spotify playlist import |
| `/pause`, `/resume`, `/skip` | Playback controls |
| `/join` | Explains join support; use `/play` for automatic voice-chat join |
| `/mute`, `/unmute` | Stream volume state |
| `/queue`, `/shuffle`, `/loop` | Queue/repeat controls |
| `/mode` | Original audio/video switch |
| `/admins` | Toggle admin-only song requests |
| `/lang code`, `/lang list` | Set/list retained translations |
| `/export`, `/import` | Export queue / import a replied JSON file |
| `/stop`, `/leave` | Leave voice chat and clear queue |
| `/ping`, `/repo` | Diagnostics / upstream license attribution |
| `/restart`, `/update` | Restart this local build; does not fetch/overwrite source |

The original short aliases are retained. New UI text is English; the existing translated command responses remain available.

## Group admin panel and welcomes

Use `/admin` or `/panel` in a group for admin-only settings. `/manage` while replying to a member opens member controls. `/ban`, `/unban`, `/kick`, `/muteuser` and `/unmuteuser` accept a replied member or Telegram user ID. Destructive actions require confirmation; protected admin/owner/self targets cannot be moderated. The bot must itself have Telegram's required administrator rights. Admin/member panels and ban/kick confirmation buttons require bot mode with `BOT_TOKEN`; destructive actions are not performed if a confirmation keyboard is unavailable.

`/welcome on` or `/welcome off` controls new-member greetings. `/setwelcome Welcome {mention} to {chat}!` sets a safe welcome template; `{name}` is also supported. Welcome/moderation configuration is stored under `DATA_DIR` (default `data/`). Music queues and transient playback state still reset on restart; the admin panel saves its access and loop toggles. Keep the data directory on a persistent volume for durable welcome settings.

An optional force-channel membership gate is configured with `FORCE_CHANNEL=@yourchannel` (or a numeric channel ID) and `FORCE_CHANNEL_URL=https://t.me/yourchannel` (or your own invite link). The bot must be able to inspect membership, normally by being an admin in that channel. Song/search/download requests require membership when this is enabled. `/start`, `/help` and stop/leave controls remain accessible. The bot **never silently joins a channel on behalf of the assistant or a user**. Leave `FORCE_CHANNEL` blank to disable the gate.

## API behavior and downloads

1. [Jiosaavan API](https://jiosaavan-seven.vercel.app/song/?query=Chandani)
2. [Song Downloader API](https://song-downloader-three.vercel.app/search?song=Kamar+me+dagi)
3. [Suryansh API](https://suryansh-music-search-download-api.vercel.app/search?song=Sari)

Requests use encoded parameters, timeouts/retries, a bounded short-lived cache, and fallback when an endpoint errors or has no usable tracks. These are third-party services with no uptime, catalog, licensing or schema guarantee. Restricted/DRM-marked results are skipped rather than decrypted or bypassed. In the supplied live check, the first endpoint returned metadata but all returned tracks were restriction-marked; fallback provided playable results.

Downloads are capped at 50 MiB, use public-address/redirect validation, and clean up temporary files. The supplied media is **AAC in an MP4 container**, sent as `.m4a`; it is not falsely renamed to MP3. Use only music you have permission to stream/download. Search availability does not establish redistribution rights. Explicit legacy links/playlist extraction still depend on their external services and may need newer yt-dlp or cookies; no cookies are bundled.

## Colors and emoji

The supplied catalog is integrated as **363 unique emoji-to-document-ID mappings** in `core/premium_emoji.json`, with the supplied later mappings overriding duplicates. The non-emoji `??` placeholder is intentionally not substituted. `PREMIUM_EMOJIS=true` enables the catalog for HTML UI messages, media captions and matching button icons; `false` keeps ordinary emoji. Code blocks, link attributes and existing emoji entities are not modified. Custom-emoji rejection triggers a plain-emoji retry; colored buttons are retried without custom icons if necessary.

Standard Unicode emoji work without a paid Telegram account. The bot attempts Telegram's supported blue/green/red button styles through Bot API `editMessageReplyMarkup`, with a standard keyboard fallback. This requires `BOT_TOKEN`, Bot API availability, and a compatible Telegram client; arbitrary custom button colors are not supported. Custom emoji require Telegram eligibility; optional `CUSTOM_EMOJI_ID` overrides the per-button catalog icon (Premium bot owner or additional purchased usernames). See [Telegram's official button specification](https://core.telegram.org/bots/api/types/inlinekeyboardbutton.md).

## Security changes

Embedded credential-like values and backup files from the upload were removed, not copied into the deliverable. Rotate any source credentials that may have been shared. The inherited hard-coded third-party sudo account and forced channel-join behavior were removed. Only configured sudoers and actual group admins may control playback. Configuration fails clearly when required values are missing; error replies do not publish tracebacks or tokens.

## Validation

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ogmusic.probe "Kamar me dagi"
```

See `VALIDATION.md` for checks actually performed and the Telegram smoke-test checklist. No real Telegram session or source credential was used during development, so live group voice-chat joining, Telegram file upload, colored buttons, and playback controls still require an account-backed deployment test. Do not interpret local tests as a live Telegram playback guarantee.

## License and attribution

Derived from [Asm Safone's MusicPlayer](https://github.com/AsmSafone/MusicPlayer). Original attribution and the **AGPL-3.0-or-later** license are retained. If you run a modified network service, comply with AGPL source-sharing requirements. Telegram profile name, avatar and username must be updated separately through @BotFather; source branding does not rename an existing Telegram account.
