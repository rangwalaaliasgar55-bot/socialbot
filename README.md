# 🤖 SocialBot

**All-in-one open-source social media scheduling & automation bot.** Post, schedule, auto-engage and analyze **LinkedIn, X, YouTube & Telegram** from one place — a self-hostable alternative to Buffer/Hootsuite, in the spirit of [Postiz](https://github.com/gitroomhq/postiz-app) and the classic Python growth bots, built as a single lightweight Python app.

<div align="center">

[![version](https://img.shields.io/badge/version-1.4.1-2b7a78?style=for-the-badge)]()
[![tests](https://img.shields.io/badge/tests-116%20passing-2ea043?style=for-the-badge)](https://github.com/rangwalaaliasgar55-bot/socialbot/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![license](https://img.shields.io/badge/license-MIT-green?style=for-the-badge)](LICENSE)
[![platforms](https://img.shields.io/badge/platforms-5-7c5cff?style=for-the-badge)](#-supported-platforms)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](Dockerfile)

</div>

---

## ✨ What it does

| Area | Features |
|---|---|
| 📅 **Scheduling** | One-shot, interval & **cron recurrence**, calendar view, timezone-aware, retries with backoff, cancel/reschedule |
| 📨 **Multi-platform publishing** | One composer → every network. Per-account **signatures**, **tags**, media (URLs & files), per-platform length limits |
| 🤖 **Growth bot** | Rule-driven **like / follow / comment / repost** on keyword & hashtag triggers, dry-run mode, per-run & per-hour caps, human-like pacing |
| ✨ **AI content** | Draft generation with hooks/CTAs offline, or plug any **OpenAI-compatible API** (OpenAI, Groq, OpenRouter, Ollama, LM Studio) |
| 📊 **Analytics** | Engagement metrics over time per post/platform (likes, shares, comments, impressions), CSV export |
| 🪝 **Webhooks** | Notify your systems on every publish — n8n, Make, Zapier, Slack, Discord |
| 🧩 **REST API** | Everything the dashboard does is scriptable (`/api/…` + OpenAPI docs at `/docs`) |
| 🖥 **Web dashboard** | Calendar, composer with AI drafts, queue, accounts, bot rules, analytics — zero build tools, one command |
| 🗄 **Zero-config storage** | Single SQLite file — no database server required (works anywhere) |

## 🌐 Supported platforms

| Platform | Post | Media | Delete | Metrics | Bot actions |
|---|:--:|:--:|:--:|:--:|---|
| 🧪 **Mock (demo)** | ✅ | ✅ | ✅ | ✅ | like, follow, comment, repost, search |
| 𝕏 X (Twitter) | ✅ (v2) | — | ✅ | ✅ | like, follow, search |
| 💼 LinkedIn | ✅ | — | ✅ | — | — |
| ✈️ Telegram | ✅ | ✅ | — | — | — |
| ▶️ YouTube | ✅ (video) | ✅ | ✅ | ✅ | — |

## 🚀 Quickstart

```bash
git clone https://github.com/rangwalaaliasgar55-bot/socialbot
cd socialbot
pip install -e .

# 1. create the database + demo content (mock platform, sample post & bot rule)
socialbot init --demo

# 2. launch the web dashboard
socialbot dashboard
# → open http://localhost:8000  (docs at /docs)

# 3. or work from the terminal
socialbot post "Hello world! 🚀" --to mock
socialbot post "Big launch tomorrow" --to mock,telegram --at "tomorrow 09:00"   # schedule
socialbot run                                                                   # scheduler worker
```

**No credentials? No problem.** The built-in **Mock platform** makes the whole pipeline (posting, scheduling, bot actions, analytics) work end-to-end for demos and development. Connect real networks whenever you're ready.

### Connecting a real platform

```bash
# interactive — prompts for the credentials it needs
socialbot accounts add telegram

# or non-interactive
socialbot accounts add telegram --set bot_token=123:ABC --set chat_id=-1001234567890 --label "news channel"

# check what's connected
socialbot accounts list
```

Every credential is stored **locally in your own database** — nothing leaves your machine. Each platform card in the dashboard explains exactly where to get its token (also see [`ENVIRONMENT.md`](docs/ENVIRONMENT.md)).

## 🖥 The dashboard

```bash
socialbot dashboard            # http://localhost:8000
```

- **📅 Calendar** — month grid with color-coded posts; click a day to schedule
- **✍️ Composer** — pick platforms (live character limits), media, tags, signature, recurrence, webhook, and **✨ AI drafts**
- **📮 Queue** — every post with per-platform results; click any post for full detail (results, errors, edit, remote delete)
- **🔌 Accounts** — connect/verify credentials with auto-generated forms; disconnect with one click
- **🤖 Growth bot** — create/edit/pause rules (`comment on #python posts on X`), run dry-run or live
- **📊 Analytics** — totals, engagement bars per platform, CSV export
- **⚡ Activity** — full event log

## ⚙️ Autonomous operation

The scheduler is embedded in the dashboard and CLI worker — it runs by itself:

- publishes due posts every **20s** (catches up missed posts after downtime)
- **auto-retries failed posts** with exponential backoff (2m → 4m → 8m … max 1h, up to `max_attempts`=3)
- refreshes engagement metrics every 6h
- optionally runs your enabled bot rules on a schedule: set `SOCIALBOT_BOT_INTERVAL=30` (minutes) — each rule still respects its dry-run/live mode and its own caps
- runs the **background agents** (mention monitor, inbox responder, competitor watch, trends) every `SOCIALBOT_AGENTS_INTERVAL` (default 30m) — agent runs are protected by a distributed lock so the API server and CLI worker never double-run
- captures **real-time trends** (Twitter/X + Reddit when configured, demo topics otherwise) and **RSS/curated content** into ready-to-schedule drafts
- routes all **agent-generated drafts** through the review queue — approve or reject them from the dashboard's *Review* view (`socialbot review list|approve|reject`)
- generates the **monthly growth report** on the 1st of each month (`SOCIALBOT_REPORT_HOUR`, default 6)

```bash
socialbot run          # standalone worker
socialbot dashboard    # dashboard + worker in one process
socialbot tasks list   # inspect workers + the shared task queue
socialbot review list  # agent drafts waiting for your approval
```

## 🤖 Growth bot (auto like / follow / comment)

Rules watch a **keyword or hashtag** search and act with safety caps:

```bash
# rules are created in the dashboard (Bot → New rule) or via the API…
# …then run them:
socialbot bot                # dry-run (default) — previews actions only
socialbot bot --live         # actually performs them
socialbot bot --rule <id>    # single rule
```

Safety model (like Postiz, we're **ToS-friendly**):

- official platform APIs only — no scraping, no browsers, no password stuffing
- every rule starts in **dry-run**
- per-run **and** per-hour caps + randomized human-like delays
- bot actions only on platforms whose official API allows them

## 🧩 REST API (for n8n / Make / Zapier / cron)

```bash
# schedule a post
curl -X POST http://localhost:8000/api/posts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello from n8n 🎉","platforms":["telegram","linkedin"],
       "scheduled_at":"2026-01-01T09:00:00Z"}'

# publish immediately
curl -X POST http://localhost:8000/api/posts \
  -H 'Content-Type: application/json' \
  -d '{"text":"now!","platforms":["mock"],"publish_now":true}'

# list the queue / analytics / events
curl http://localhost:8000/api/posts
curl http://localhost:8000/api/analytics/summary
curl http://localhost:8000/api/events
```

Interactive OpenAPI docs: **http://localhost:8000/docs**

Outgoing webhooks: set a `webhook_url` on a post (or `SOCIALBOT_WEBHOOK_URL` globally) and receive `post.published` events with full results.

## ⌨️ CLI reference

| Command | What it does |
|---|---|
| `socialbot init [--demo]` | create DB (+ demo data) |
| `socialbot platforms` | list supported networks & capabilities |
| `socialbot accounts add PLATFORM [--set k=v…]` | connect an account |
| `socialbot accounts list \| remove PLATFORM` | manage accounts |
| `socialbot post TEXT --to p1,p2 [--media urls] [--at "in 2h"] [--repeat daily]` | post now or schedule |
| `socialbot schedule` | show the queue |
| `socialbot cancel POST_ID` | cancel a scheduled post |
| `socialbot run [--once] [--tick 20]` | scheduler worker |
| `socialbot bot [--live] [--rule ID]` | run growth rules |
| `socialbot analytics [--refresh] [--csv out.csv]` | stats & export |
| `socialbot generate "topic" [--n 3]` | AI drafts |
| `socialbot dashboard [--port 8000]` | web dashboard + API |

`--at` accepts `in 30m / in 2h / in 3d`, `2026-01-01 09:00` (local time) or full ISO timestamps. `--repeat` accepts `daily, weekly, hourly, every:<seconds>` or a crontab like `0 9 * * mon`.

## 🐳 Docker

```bash
docker compose up --build -d      # dashboard on http://localhost:8000
```

Data (SQLite + uploads volume) persists in `./data`. See [`docker-compose.yml`](docker-compose.yml).

## ⚙️ Configuration

SocialBot is configured by **accounts in the database** plus a few environment variables ([`.env.example`](.env.example)):

| Variable | Purpose |
|---|---|
| `SOCIALBOT_DB` | SQLite path (default `./socialbot.db`) |
| `SOCIALBOT_API_TOKEN` | protect the API & dashboard with `Bearer` auth |
| `SOCIALBOT_BOT_INTERVAL` | run bot rules on a schedule (minutes, 0 = off) |
| `SOCIALBOT_WEBHOOK_URL` | global publish webhook |
| `SOCIALBOT_AI_API_KEY` | enable LLM drafts (any OpenAI-compatible API) |
| `SOCIALBOT_AI_BASE_URL` | e.g. `https://api.groq.com/openai/v1`, `http://localhost:11434/v1` |
| `SOCIALBOT_AI_MODEL` | e.g. `llama-3.1-8b-instant` |

Platform credentials can also be provided as `PLATFORM_FIELD` env vars (e.g. `TELEGRAM_BOT_TOKEN`, `LINKEDIN_ACCESS_TOKEN`) — see [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

## 🧪 Development

```bash
pip install -e ".[dev]"
pytest                     # 116 tests, no network needed
```

## 🤝 Contributing

Found a bug or have an idea? Open an [Issue](https://github.com/rangwalaaliasgar55-bot/socialbot/issues) using the templates, or submit a [Pull Request](https://github.com/rangwalaaliasgar55-bot/socialbot/pulls). See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Adding a platform = one small class in `socialbot/platforms/`:

```python
@register
class MyNetwork(Platform):
    name = "mynetwork"
    display_name = "My Network"
    capabilities = {"post"}
    auth_fields = [{"key": "token", "label": "API token", "required": True, "secret": True}]

    def publish(self, post):
        data = self.http.post_json("https://api.example.com/post",
                                   json={"text": post.text},
                                   headers={"Authorization": f"Bearer {self.require('token')}"})
        return PublishResult(platform=self.name, ok=True, remote_id=data["id"])
```

It instantly appears in the CLI, dashboard, API and scheduler.

## 🗺 Roadmap

- [ ] OAuth click-to-connect for X / LinkedIn / YouTube
- [ ] Team collaboration & approval workflows
- [ ] Media library with upload caching
- [ ] Best-time-to-post suggestions
- [ ] Restore more platforms on demand (Mastodon, Bluesky, Instagram, …)

## ⚖️ Compliance & responsible use

SocialBot uses **official platform APIs only** — no scraping, no credential stuffing, no ToS-violating automation. It never proxies or re-hosts your tokens; everything stays in your database. Respect each platform's rate limits and automation policies: keep bot rules modest, prefer dry-run until you trust a rule, and don't spam. You are responsible for the actions of your bot.

## 📄 License

[MIT](LICENSE) — same as Postiz. Built for the community, by the community. 🤝
