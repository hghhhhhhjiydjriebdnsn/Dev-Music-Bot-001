# MAHI MUSIC — Validation Notes

## Passed here

- Installed the pinned requirements in a clean Python 3.12 environment. `pip check` found no broken requirements.
- Imported both `core` and `main` with dummy configuration, without connecting to Telegram. Fixed the voice-chat dependency mismatch by using pinned `PyrogramMod==2.4.1` with `py-tgcalls==2.2.10`.
- **38 automated tests passed**: API normalization/fallback/cache bounds, URL/redirect safety, download cleanup/limits, configuration, valid translations, retained command handlers, queue behavior, cover generation, callback authorization/result ownership, HTML rendering, userbot UI fallback, rollback after an initial playback failure, premium emoji fallbacks, SQLite persistence, channel gating, requester-bound moderation confirmations and replay/cross-chat denial.
- All Python source compiled successfully. The retained Telugu translation had invalid JSON escapes; these were repaired.
- All three requested endpoints answered live requests. A normalized probe returned 0 unrestricted results from Jiosaavan and 5 each from Song Downloader and Suryansh for the test query.
- Downloaded a real 8,146,039-byte `.m4a` from the Song Downloader result. FFprobe identified AAC audio, about 197.07 seconds long; FFmpeg decoded the first five seconds successfully.
- Checked the native voice-chat library's shared dependencies; none were missing in this environment.
- Scanned deliverable text for source token/hash patterns. No source credentials or credential-bearing backup files remain.

## Premium emoji checks

The user-supplied catalog contains 363 unique mappings after duplicate overrides. Four additional offline tests passed: safe HTML conversion, native custom-emoji entity parsing, retry with ordinary emoji on Premium rejection, and opt-out/per-button lookup. Existing UI authorization/rendering tests also continued to pass after the integration. `??` remains ordinary punctuation rather than being converted to a custom emoji.

## Not tested live

No real Telegram login was started and no uploaded credential was used. Administration, welcome delivery, restriction rights, and channel-membership checks still need a real-account deployment test. Group joining, automatic voice-chat creation, Telegram audio upload, button color/custom-emoji rendering, and real pause/resume/skip/stop behavior require a deployed assistant and bot. Mocked tests and successful audio decoding are not an end-to-end Telegram guarantee. The Dockerfile is supplied but the container itself was not built here.

The pinned voice-chat library joins automatically when `/play` starts audio. It does not expose a standalone silent-join method; `/join` explains this and directs users to `/play`. No existing automatic join behavior was removed.

## Quick account-backed check

1. Fill `.env` with your own API ID/hash, assistant user session and bot token. Add both accounts to a test supergroup and grant the needed voice-chat permissions.
2. Start a voice chat and send `/play Kamar me dagi`. Confirm the assistant joins, audio is audible, and the OG player appears.
3. Queue a second song. Test pause, resume, skip, loop, shuffle, mute/unmute, queue and stop. Confirm non-admin users cannot operate admin controls.
4. Run `/search Sari`, try Play/Add as the requester, then `/song Kamar me dagi`. Confirm the audio file plays in Telegram.
5. Check export/import, Telegram media replies, languages, radio and explicit YouTube/playlist links as needed. These retained integrations have their own upstream availability requirements.
6. As a group admin, open `/admin`, toggle welcome settings and use `/setwelcome`. Add a test member and verify the greeting. Use `/manage` on a non-admin test account; test moderation permissions and destructive-action confirmation only in a group you control.
7. If using `FORCE_CHANNEL`, give the bot membership-inspection access in that channel. Confirm a non-member cannot play/search/download, then join the configured channel and retry. Confirm stop/leave and help remain available. No account should be auto-subscribed.
8. Test without `BOT_TOKEN` only if legacy userbot mode is wanted. Text commands remain usable; bot-only keyboards/colors are intentionally omitted.

## Provider and premium limits

The first API returned tracks marked DRM/pro-only, so the bot skips those and falls back. Other APIs may return links that expire, fail, or change format. No DRM bypass, paid entitlement, database persistence or subscription billing is implemented. The premium-style UI does not grant Telegram Premium. Supported colored buttons are best-effort; custom emoji require Telegram eligibility. Use only audio you are authorized to stream or redistribute.

## Security before launch

Rotate credentials that appeared in the uploaded source. Keep `.env` and session strings out of version control. Only IDs you configure in `SUDOERS` receive sudo access; the inherited unrelated hard-coded account and automatic channel subscription were removed.
