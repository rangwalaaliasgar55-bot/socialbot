# Changelog

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
