# Changelog

## 1.4.1 — 2026-08-20

Focused build: SocialBot now ships with exactly the platforms you need.

- **Platforms trimmed to 5**: Mock (demo), LinkedIn, X (Twitter), Telegram and
  YouTube. Removed Mastodon, Bluesky, Reddit, Discord, Slack, Facebook,
  Instagram, Threads, Pinterest, TikTok, Nostr, Lemmy.
- **Docs** updated everywhere (README, ENVIRONMENT.md, .env.example) so only
  the kept platforms are shown.
- 116 tests (was 126 — removed 11 platform tests, added 1 YouTube test)

## 1.4.0 — 2026-08-20

Human-in-the-loop review queue for agent-generated content.

- **Review queue**: drafts from feeds, trends and competitor watchers now land
  as `review_status="pending"` and wait for a human before going live — no more
  unvetted agent content reaching your calendar
- **Store**: `review_status` / `reviewed_at` columns (auto-migrated),
  `list_posts_for_review()`, `set_review()`
- **CLI**: `socialbot review list|approve|reject` — approve optionally
  schedules (`--at`, `--best-time`, `--now`) or keeps the post as an approved
  draft for later editing; reject takes `--note`
- **API**: `GET /api/review` (pending/approved/rejected + stats),
  `POST /api/review/{id}/approve` (platforms, `best_time`, `scheduled_at:
  "now"|ISO`), `POST /api/review/{id}/reject` (note)
- **Dashboard**: new "Review" view — pending/approved queue with one-click
  Approve (pick platforms + timing) and Reject (with note)
- 126 tests (was 110)

## 1.3.0 — 2026-08-20

Coordination, monitoring & AI content kit — ports PR #3's multi-agent layer,
reconciled with the v1.2.0 agent engine (supersedes PR #3).

- **Coordination** (`socialbot/coordination.py`): agent registration +
  heartbeats + dead-agent detection, distributed locks backed by SQLite
  (safe across processes; fixed cross-connection visibility + lock-leak bugs
  from PR #3), persistent task queue with claiming, retries and stats
- **Monitoring** (`socialbot/monitoring.py`): counters/gauges/timings,
  component health checks, structured JSON logging, resource monitor that
  degrades gracefully without `psutil` (optional)
- **AI content kit** (`socialbot/ai_engine.py`): platform-aware visual
  prompts, image generation (OpenAI or any OpenAI-compatible endpoint via
  `OPENAI_BASE_URL` — works with Groq), captions + hashtags + SEO scoring;
  full offline mock mode when no API key is set
- **Real-time trend analyzer** (`socialbot/trend_analyzer.py`): Twitter/X +
  Reddit sources (Bearer / OAuth client credentials), demo-topic fallback,
  merged into the trends agent (`socialbot trends` / `--no-real` to disable)
- **Scheduler**: agent runs now take the distributed lock (no double-runs
  across API server + worker processes) and are timed via monitoring
- **API**: `/api/agents` (workers + stats), `/api/tasks` (GET/POST/GET:id),
  `/api/monitoring`, `/api/trends/strategy`, `/api/ai/content`
- **CLI**: `socialbot tasks list|enqueue|stats`; `trends --no-real`
- **Dashboard**: "Coordination & monitoring" panel (workers, task queue,
  health) in the Agents view
- 110 tests (was 90)

## 1.2.0 — 2026-08-20

Growth & intelligence release — "agents + self-learning" edition.

- **Real posting**: per-platform text variants (`--variant`), automatic
  thread/carousel splitting (`--thread`), best-time-to-post scheduling
  (`--best-time`, from your own engagement history)
- **Content sources**: RSS/Atom ingestion (stdlib XML, no new deps) and
  curated lists → auto-generated draft posts (`socialbot feeds`)
- **Background agents** (`socialbot monitor / inbox / trends`):
  mention & hashtag monitor (dedupe, dry-run, caps), trend analyzer with
  auto-drafts, inbox responder (intent detection + webhook escalation),
  competitor watch with content-gap drafts
- **Intelligence**: offline sentiment analysis, intent detection,
  context-aware replies, topic extraction, post "vibe" metrics
  (`socialbot analyze`)
- **Safety**: persistent token-bucket rate limiter + blacklist/whitelist
  enforced across the bot and all agents (`socialbot safety`)
- **User profiling**: learned interest/activity profiles + similar-user
  targeting for smarter growth (`socialbot profiles`)
- **Self-learning loop**: best-time windows, vibe-fit scoring, adaptive
  hashtags (`socialbot best-time`, Insights tab)
- **Monthly growth report**: posts/engagement/follows/agent activity,
  delivered to webhooks (`socialbot report`)
- **Scheduler**: new jobs for agents, feeds, trends & monthly reports
- **Dashboard**: new 🧠 Agents and 🔮 Insights views
- **Windows fix**: `--help` no longer crashes on cp1252 consoles
- 90 tests (was 66)

## 1.1.0 — 2026-08-19

Parallel lines merged: platform expansion + autonomy hardening.

- **New platforms**: YouTube, TikTok, Nostr, Lemmy (17 total).
  - **YouTube** — Data API v3 resumable video upload, delete, metrics; OAuth access/refresh tokens.
  - **TikTok** — Content Posting API (init → chunk upload → poll); requires approved app.
  - **Nostr** — NIP-01 kind-1 notes to multiple relays; hex/nsec keys; optional coincurve + websocket-client.
  - **Lemmy** — Create posts, vote, comment, search, metrics on any instance via JWT or login.
- Docs: credential setup for the four new networks in `docs/ENVIRONMENT.md`.
- **Autonomous operation**: scheduler auto-retries failed posts with
  exponential backoff (2m→4m→8m…max 1h, up to max_attempts); optional
  scheduled bot rules via `SOCIALBOT_BOT_INTERVAL`
- **API**: `DELETE /api/posts/:id` now really deletes any post; new
  `PATCH /api/posts/:id` (edit drafts/scheduled), `POST /api/posts/:id/remote`
  (delete on remote platforms), `PATCH /api/bot/rules/:id`, optional
  `SOCIALBOT_API_TOKEN` Bearer auth for `/api` + docs
- **Publisher**: retries now preserve earlier per-platform successes
  (no more partial-state loss)
- **Bot engine**: per-hour cap now counts *all* live actions in the last
  hour (was: latest run only — repeated runs could exceed the cap)
- **Platform fixes**: Telegram local-file uploads keep chat_id/caption;
  Slack image blocks use the correct schema; Bluesky always publishes with
  the DID repo after login; Mastodon cleanup
- **Dashboard**: clickable post detail modal (results, errors, edit,
  remote delete), composer draft autosave + Ctrl+Enter, calendar "Today",
  rule edit/pause/resume, account disconnect, API-token prompt, live
  queued-post count
- 66 tests (was 58)

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
