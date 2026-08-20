# Social Analytics Automation

## What it does
A tool that connects to your social platforms, analyzes follower growth and engagement, shows where you're lacking, and automatically generates an improvement plan.

## Features
- **Multi-platform connections** — YouTube, Instagram, LinkedIn, Telegram, WhatsApp. Paste API credentials in the Connections screen; without credentials it runs on realistic sample data so you can explore immediately.
- **Growth dashboard** — trailing 30-day follower-growth line chart across all platforms, plus per-platform health score rings.
- **Weak-spot diagnosis** — each platform is scored 0–100 and checked for low engagement rate, declining followers, and infrequent posting, with a plain-language explanation of each problem.
- **Auto-generated report** — a prioritized action plan telling you exactly what to fix first and how, with one-click Markdown export.

## Platform notes
- Instagram & LinkedIn require Business/Creator accounts and access tokens.
- YouTube uses a Data API v3 key (easiest to connect).
- Telegram uses a bot token + channel.
- WhatsApp Business API has no follower metric, so it is shown as engagement-volume only.

## Added: Content Planner (turns insight into action)
- **Composer + scheduler** — draft a post per platform, set a one-time or recurring (daily/weekly) time, and queue it.
- **Best-time & copy suggestions** — the engine reads each platform's analytics and recommends the best day/hour plus a drafted post (offline templates, no external API).
- **Queue + activity log** — a scheduled-queue table and an activity feed; due posts are auto-"published" (logged) by an in-process scheduler every 60s.

## How this compares to socialbot (the linked repo)
- `socialbot` (Python/FastAPI) *does* things: schedules, publishes to LinkedIn/X/YouTube/Telegram, growth bot, AI drafts.
- Our app *diagnoses* well (growth tracking, weak-spot scoring, auto-report) and now also *acts* (plan & schedule).
- Natural next step to fully match: connect the scheduler to live platform APIs so posts actually publish (not just logged).

## Added: AI, real publishing & audience interaction
- **AI copy + image** — OpenAI-compatible `/ai/draft` and `/ai/image`. With `OPENAI_API_KEY` set, the planner generates post copy and images; without it, sensible offline templates are used.
- **Audience chat** — floating assistant (`/ai/chat`) answers questions using your live report as context. Offline mode gives generic tips.
- **Real publishing** — scheduler + "Publish now" push due posts to connected platform APIs (Telegram live today; others queue with status recorded). No credentials → logged.
- **Engagement & win-back** — `/engagement` flags declining platforms and drafts a re-engagement post.
- **Env**: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_IMAGE_MODEL` (see backend/.env.example).

