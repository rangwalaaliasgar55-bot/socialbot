# Changelog

## 1.1.0 — 2026-08-19

- **New platforms**: YouTube, TikTok, Nostr, Lemmy (17 total).
  - **YouTube** — Data API v3 resumable video upload, delete, metrics; OAuth access/refresh tokens.
  - **TikTok** — Content Posting API (init → chunk upload → poll); requires approved app.
  - **Nostr** — NIP-01 kind-1 notes to multiple relays; hex/nsec keys; optional coincurve + websocket-client.
  - **Lemmy** — Create posts, vote, comment, search, metrics on any instance via JWT or login.
- Docs: credential setup for the four new networks in `docs/ENVIRONMENT.md`.
- Tests: registry coverage for the new platforms.

## 1.0.1 — 2026-08-19

- **Reliability**: Guard module-level FastAPI `app` creation so imports / pytest
  collection no longer start the scheduler or hit SQLite side-effects.
- **Tests**: Set `SOCIALBOT_NO_AUTO_APP` early in API tests; full suite (58)
  now collects and runs cleanly in any environment.
- **CI**: Enabled GitHub Actions workflow (`.github/workflows/ci.yml`).

## 1.0.0 — 2026-08-19

Initial release. 🎉

- **13 platforms**: Mock, Mastodon, Bluesky, Reddit, X, LinkedIn, Facebook,
  Instagram, Threads, Pinterest, Telegram, Discord, Slack
- Scheduling: one-shot, interval & cron recurrence, retries, cancel
- Web dashboard: calendar, composer (+ AI drafts), queue, accounts,
  bot rules, analytics, activity log
- REST API + OpenAPI docs, outgoing publish webhooks
- Growth bot engine: like/follow/comment/repost rules with caps & dry-run
- AI content generation (offline templates or any OpenAI-compatible API)
- Analytics with metrics snapshots + CSV export
- CLI (`socialbot …`), Docker, CI, 58 tests
