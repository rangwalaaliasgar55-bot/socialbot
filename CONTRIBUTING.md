# Contributing to SocialBot

Thanks for helping build SocialBot! 🤝

## Getting started

```bash
git clone https://github.com/rangwalaaliasgar55-bot/socialbot
cd socialbot
pip install -e ".[dev]"
pytest
```

## Adding a platform provider

1. Create `socialbot/platforms/<name>.py` with a `@register`-decorated `Platform` subclass
2. Declare `auth_fields` (this auto-renders dashboard forms), `capabilities`, and `max_length`
3. Implement `publish()` (required) and any of `delete()`, `get_metrics()`, `search()`,
   `like()`, `follow()`, `comment()`, `repost()`
4. Add tests in `tests/test_platforms.py` using the `FakeSession` helper (no network!)
5. Add a row to the platform matrix in `README.md`

## Guidelines

- **Official APIs only** — no scraping or credential stuffing
- Every new feature needs tests; the suite runs fully offline
- Keep dependencies minimal (stdlib + requests/fastapi/apscheduler/yaml/click)
- One PR per feature, with a short changelog entry

## Reporting issues

Include: platform, logs (`socialbot run` output), and the `events` table
(`sqlite3 socialbot.db 'select * from events order by ts desc limit 20'`).
Never paste real access tokens — redact them.
