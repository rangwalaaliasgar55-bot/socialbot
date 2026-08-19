"""SocialBot command line interface."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import click

from . import __version__
from . import ai as ai_mod
from .analytics import refresh_metrics, summary, to_csv
from .bot import BotEngine
from .http import HttpClient
from .models import BotRule, Post, PostStatus, iso, utcnow
from .platforms import PlatformError, create_platform, platform_meta, platform_names
from .publisher import Publisher
from .scheduler import Scheduler
from .storage import Store

pass_store = click.make_pass_decorator(Store)


def get_store() -> Store:
    return Store()


def echo_json(obj) -> None:
    click.echo(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def parse_when(value: str) -> datetime:
    """Accepts ISO timestamps, 'YYYY-MM-DD HH:MM', and 'in 30m/2h/3d'."""
    value = value.strip()
    rel = re.fullmatch(r"in\s+(\d+)\s*([smhd])", value, re.I)
    if rel:
        n, unit = int(rel.group(1)), rel.group(2).lower()
        delta = {"s": timedelta(seconds=n), "m": timedelta(minutes=n),
                 "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        return utcnow() + delta
    text = value.replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            local = datetime.strptime(text, fmt)
            # interpret as local time -> UTC
            offset = datetime.now().astimezone().utcoffset() or timedelta(0)
            return (local - offset).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise click.BadParameter(f"cannot parse time '{value}' (try 'in 2h', "
                                 f"'2026-01-01 09:00', or full ISO)")


def schedule_options(fn):
    fn = click.option("--at", "when", default=None,
                      help="When to publish: 'in 2h', '2026-01-01 09:00' or ISO timestamp. "
                           "Default: immediately.")(fn)
    fn = click.option("--repeat", default=None,
                      help="Repeat: 'daily', 'weekly', 'hourly', cron like '0 9 * * *', "
                           "or interval seconds like 'every:3600'")(fn)
    return fn


@click.group()
@click.version_option(__version__, prog_name="socialbot")
def cli():
    """🤖 SocialBot — post, schedule, automate & analyze every social network."""
    # Windows consoles default to cp1252 and crash on emoji — force UTF-8 output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# --------------------------------------------------------------------- init
@cli.command()
@click.option("--demo", is_flag=True, help="seed a mock account, sample posts and a bot rule")
def init(demo: bool):
    """Set up the database (and optionally demo content)."""
    store = get_store()
    click.echo(f"✅ database ready: {store.path}")
    if demo:
        store.save_account("mock", {"username": "demo"}, label="Demo account")
        sample = Post(
            text="Hello world from SocialBot! 🚀 Scheduling every social network from one place.",
            platforms=["mock"], status=PostStatus.SCHEDULED.value,
            scheduled_at=iso(utcnow() + timedelta(minutes=1)), tag="launch")
        store.save_post(sample)
        rule = BotRule(name="engage-python-fans", platform="mock", action="like",
                       trigger_type="hashtag", trigger_value="python", limit_per_run=3)
        store.save_rule(rule)
        click.echo("🎉 demo data seeded: mock account, 1 scheduled post, 1 bot rule")
        click.echo("→ try:  socialbot run      (publishes the post when due)")
        click.echo("→ or:   socialbot dashboard  (full web UI)")
    click.echo("\nNext steps:")
    click.echo("  socialbot platforms                 # see supported networks")
    click.echo("  socialbot accounts add mastodon     # connect an account")
    click.echo("  socialbot post 'hi' --to mock       # first post")


# ---------------------------------------------------------------- platforms
@cli.command()
def platforms():
    """List supported platforms and connection status."""
    store = get_store()
    accounts = {a["platform"] for a in store.list_accounts()}
    rows = []
    for meta in platform_meta():
        account = store.get_account(meta["name"])
        platform = create_platform(meta["name"], (account or {}).get("config", {}))
        state = "✅ connected" if meta["name"] in accounts and platform.is_configured() else "—"
        rows.append((meta["icon"], meta["display_name"], meta["name"],
                     ",".join(sorted(meta["capabilities"])), state))
    width = max(len(r[1]) for r in rows) + 2
    for icon, disp, name, caps, state in rows:
        click.echo(f"{icon} {disp:<{width}} {name:<12} {state:<12} {caps}")
    click.echo(f"\n{len(rows)} platforms supported")


# ----------------------------------------------------------------- accounts
@cli.command()
@click.argument("platform_name", metavar="PLATFORM")
@click.option("--set", "settings", multiple=True,
              help="key=value credential, repeatable (e.g. --set bot_token=xxx --set chat_id=123)")
@click.option("--label", default="", help="account nickname")
def accounts_add(platform_name: str, settings: tuple, label: str):
    """Add or update a platform account (interactive prompts for missing fields)."""
    if platform_name not in platform_names():
        raise click.ClickException(f"unknown platform '{platform_name}' — run `socialbot platforms`")
    store = get_store()
    existing = store.get_account(platform_name) or {"config": {}}
    config = dict(existing.get("config", {}))
    for pair in settings:
        key, _, value = pair.partition("=")
        if not value:
            raise click.ClickException(f"--set expects key=value, got '{pair}'")
        config[key.strip()] = value.strip()

    cls = create_platform(platform_name, config)
    for field in cls.auth_fields:
        if field.get("required", True) and not config.get(field["key"]):
            prompt = f"{field['label']}"
            if field.get("help"):
                prompt += f" ({field['help']})"
            config[field["key"]] = click.prompt(prompt, hide_input=field.get("secret", False),
                                                default="")
    store.save_account(platform_name, config, label)
    platform = create_platform(platform_name, config)
    ok, message = platform.verify()
    click.echo(f"💾 saved. verify: {'✅' if ok else '⚠️'} {message}")
    if not ok:
        click.echo("   (you can fix credentials later with `socialbot accounts add "
                   f"{platform_name} --set key=value`)")


@cli.command("accounts")
@click.argument("action", type=click.Choice(["list", "remove"]))
@click.argument("platform_name", required=False)
def accounts(action: str, platform_name: Optional[str]):
    """List or remove accounts: socialbot accounts list|remove [PLATFORM]"""
    store = get_store()
    if action == "list":
        accounts = store.list_accounts()
        if not accounts:
            click.echo("no accounts yet — add one with `socialbot accounts add <platform>`")
            return
        for a in accounts:
            keys = ", ".join(a["config"].keys())
            click.echo(f"• {a['platform']:<12} {a['label'] or '(no label)':<20} keys: {keys}")
    else:
        if not platform_name:
            raise click.ClickException("specify a platform: socialbot accounts remove mastodon")
        click.echo("removed" if store.delete_account(platform_name) else "not found")


# --------------------------------------------------------------------- post
def build_post(text: str, targets: str, media: Optional[str], tag: Optional[str],
               signature: Optional[str], webhook: Optional[str]) -> Post:
    platforms_list = [p.strip() for p in targets.split(",") if p.strip()]
    unknown = [p for p in platforms_list if p not in platform_names()]
    if unknown:
        raise click.ClickException(f"unknown platforms: {', '.join(unknown)}")
    if not platforms_list:
        raise click.ClickException("no target platforms given")
    return Post(text=text, platforms=platforms_list,
                media=[m.strip() for m in (media or "").split(",") if m.strip()],
                tag=tag, signature=signature, webhook_url=webhook)


def recurrence_from(repeat: Optional[str]):
    if not repeat:
        return None
    if repeat == "daily":
        return {"type": "cron", "value": "0 9 * * *"}
    if repeat == "weekly":
        return {"type": "cron", "value": "0 9 * * 1"}
    if repeat == "hourly":
        return {"type": "interval", "value": 3600}
    if repeat.startswith("every:"):
        return {"type": "interval", "value": int(repeat.split(":", 1)[1])}
    if re.fullmatch(r"[\d*/,-\s]+", repeat):
        return {"type": "cron", "value": repeat.strip()}
    raise click.BadParameter(f"cannot parse repeat '{repeat}'")


@cli.command()
@click.argument("text")
@click.option("--to", "targets", default="mock", show_default=True,
              help="comma-separated platforms (e.g. mastodon,telegram)")
@click.option("--media", default=None, help="comma-separated media URLs/paths")
@click.option("--tag", default=None, help="colored tag for the calendar")
@click.option("--signature", default=None, help="signature appended to the post")
@click.option("--webhook", default=None, help="webhook URL notified after publish")
@schedule_options
def post(text: str, targets: str, media: Optional[str], tag: Optional[str],
         signature: Optional[str], webhook: Optional[str], when: Optional[str],
         repeat: Optional[str]):
    """Post TEXT now (or schedule it with --at/--repeat)."""
    store = get_store()
    p = build_post(text, targets, media, tag, signature, webhook)
    publisher = Publisher(store)
    if when:
        p.scheduled_at = iso(parse_when(when))
        p.recurrence = recurrence_from(repeat)
        p.status = PostStatus.SCHEDULED.value
        store.save_post(p)
        click.echo(f"🕓 scheduled {p.id} → {targets} at {p.scheduled_at}")
        click.echo("   the scheduler will pick it up: `socialbot run`")
        return
    if repeat:
        raise click.BadParameter("--repeat requires --at")
    result = publisher.publish_now(p)
    for platform_name, res in result.results.items():
        mark = "✅" if res.get("ok") else "❌"
        click.echo(f"{mark} {platform_name}: {res.get('url') or res.get('error') or 'ok'}")
    click.echo(f"status: {result.status}")
    sys.exit(0 if result.status == PostStatus.PUBLISHED.value else 1)


@cli.command()
def schedule():
    """Manage the scheduled queue."""
    store = get_store()
    posts = [p for p in store.list_posts() if p.status in ("scheduled", "publishing")]
    if not posts:
        click.echo("queue is empty — add with `socialbot post 'text' --to mock --at 'in 1h'`")
        return
    for p in sorted(posts, key=lambda x: x.scheduled_at or ""):
        click.echo(f"• {p.scheduled_at}  {','.join(p.platforms):<22} "
                   f"{(p.text[:48] + '…') if len(p.text) > 48 else p.text}   [{p.id}]")
    click.echo(f"\n{len(posts)} scheduled · start the worker with `socialbot run`")


@cli.command()
@click.argument("post_id")
@click.confirmation_option(prompt="cancel this scheduled post?")
def cancel(post_id: str):
    """Cancel a scheduled post."""
    store = get_store()
    p = store.get_post(post_id)
    if not p:
        raise click.ClickException("post not found")
    p.status = PostStatus.CANCELLED.value
    store.save_post(p)
    click.echo("cancelled ✅")


# ---------------------------------------------------------------------- run
@cli.command()
@click.option("--once", is_flag=True, help="process due posts once and exit")
@click.option("--tick", default=20, show_default=True, help="scheduler tick (seconds)")
def run(once: bool, tick: int):
    """Run the scheduler worker (publishes due posts, refreshes metrics)."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    store = get_store()
    publisher = Publisher(store)
    if once:
        processed = publisher.process_due()
        click.echo(f"processed {len(processed)} post(s)")
        for p in processed:
            click.echo(f"  {p.id}: {p.status}")
        return
    scheduler = Scheduler(store, publisher, tick_seconds=tick)
    click.echo("🤖 scheduler running — Ctrl+C to stop")
    scheduler.run_forever()


# ---------------------------------------------------------------------- bot
@cli.command()
@click.option("--dry-run/--live", "dry_run", default=True,
              help="dry-run only previews actions (default)")
@click.option("--rule", default=None, help="run a single rule id")
def bot(dry_run: bool, rule: Optional[str]):
    """Run growth-bot rules (like/follow/comment on keyword triggers)."""
    store = get_store()
    engine = BotEngine(store)
    rules = store.list_rules()
    if rule:
        rules = [r for r in rules if r.id == rule or r.name == rule]
        if not rules:
            raise click.ClickException("rule not found")
    if not rules:
        click.echo("no rules — create one in the dashboard (Bot → New rule) "
                   "or with the API")
        return
    for r in rules:
        if not r.enabled:
            continue
        result = engine.run_rule(r, dry_run=dry_run)
        if result.get("ok"):
            click.echo(f"• {r.name}: found {result.get('found')}, acted {result.get('acted')} "
                       f"{'(dry-run)' if result.get('dry_run') else '(LIVE)'}")
            for err in result.get("errors", []):
                click.echo(f"   ⚠️ {err}")
        else:
            click.echo(f"• {r.name}: ❌ {result.get('error')}")


# ----------------------------------------------------------------- analytics
@cli.command()
@click.option("--refresh", is_flag=True, help="pull fresh metrics first")
@click.option("--csv", "csv_path", default=None, help="write CSV to file")
def analytics(refresh: bool, csv_path: Optional[str]):
    """Show analytics summary (or export CSV)."""
    store = get_store()
    if refresh:
        updated = refresh_metrics(store)
        click.echo(f"refreshed {updated} metric record(s)")
    if csv_path:
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write(to_csv(store))
        click.echo(f"wrote {csv_path}")
        return
    data = summary(store)
    click.echo(f"total posts: {data['total_posts']}")
    for status, count in sorted(data["by_status"].items()):
        click.echo(f"  {status:<10} {count}")
    if data["engagement"]:
        click.echo("engagement by platform:")
        for platform_name, metrics in data["engagement"].items():
            human = " ".join(f"{k}={v}" for k, v in sorted(metrics.items()))
            click.echo(f"  {platform_name:<12} {human}")
    else:
        click.echo("no engagement data yet — publish then `socialbot analytics --refresh`")


# ---------------------------------------------------------------- dashboard
@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
def dashboard(host: str, port: int):
    """Launch the web dashboard + API server."""
    import uvicorn
    from .api.app import create_app
    click.echo(f"🌐 dashboard → http://{host}:{port}")
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


# ----------------------------------------------------------------- generate
@cli.command()
@click.argument("topic")
@click.option("--n", default=3, show_default=True, help="number of drafts")
@click.option("--tone", default="friendly", show_default=True)
def generate(topic: str, n: int, tone: str):
    """AI-generate post drafts about TOPIC (templates offline, LLM if key set)."""
    drafts = ai_mod.generate(topic, n, tone)
    for i, d in enumerate(drafts, 1):
        click.echo(f"\n── draft {i} ({d['engine']}) " + "─" * 30)
        click.echo(d["text"])
    click.echo("\ntip: use `socialbot post '<draft>' --to mastodon` or the composer")
