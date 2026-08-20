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
from .models import (BotRule, CompetitorRule, FeedSource, InboxRule, MentionRule,
                     Post, PostStatus, iso, utcnow)
from .platforms import PlatformError, create_platform, platform_meta, platform_names
from .publisher import Publisher
from .scheduler import Scheduler
from .storage import Store

pass_store = click.make_pass_decorator(Store)

# Windows consoles default to cp1252 and crash on emoji — force UTF-8 output
# at import time so even `--help` (emitted before the group callback runs)
# renders safely.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


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
               signature: Optional[str], webhook: Optional[str],
               variants: Optional[tuple] = None, thread: bool = False,
               best_time: bool = False) -> Post:
    platforms_list = [p.strip() for p in targets.split(",") if p.strip()]
    unknown = [p for p in platforms_list if p not in platform_names()]
    if unknown:
        raise click.ClickException(f"unknown platforms: {', '.join(unknown)}")
    if not platforms_list:
        raise click.ClickException("no target platforms given")
    parsed_variants = {}
    for pair in (variants or ()):
        platform_name, _, variant_text = pair.partition("=")
        platform_name = platform_name.strip()
        if not variant_text:
            raise click.ClickException(f"--variant expects platform=text, got '{pair}'")
        if platform_name not in platform_names():
            raise click.ClickException(f"unknown platform '{platform_name}' in --variant")
        parsed_variants[platform_name] = variant_text.strip()
    return Post(text=text, platforms=platforms_list,
                media=[m.strip() for m in (media or "").split(",") if m.strip()],
                tag=tag, signature=signature, webhook_url=webhook,
                variants=parsed_variants, thread=thread, best_time=best_time)


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
@click.option("--variant", "variants", multiple=True,
              help="per-platform text override, repeatable (e.g. --variant mastodon='short version')")
@click.option("--thread", is_flag=True, help="split long text into a thread/carousel")
@click.option("--best-time", is_flag=True,
              help="schedule at the best engagement window from your history")
@schedule_options
def post(text: str, targets: str, media: Optional[str], tag: Optional[str],
         signature: Optional[str], webhook: Optional[str], variants: tuple,
         thread: bool, best_time: bool, when: Optional[str], repeat: Optional[str]):
    """Post TEXT now (or schedule it with --at/--repeat)."""
    store = get_store()
    p = build_post(text, targets, media, tag, signature, webhook,
                   variants=variants, thread=thread, best_time=best_time)
    publisher = Publisher(store)
    if best_time:
        from .adaptive import suggest_time
        p.scheduled_at = suggest_time(store, targets.split(",")[0].strip()) or iso(utcnow() + timedelta(hours=1))
        p.recurrence = recurrence_from(repeat)
        p.status = PostStatus.SCHEDULED.value
        store.save_post(p)
        click.echo(f"🕓 scheduled {p.id} → {targets} at {p.scheduled_at} (best engagement window)")
        click.echo("   the scheduler will pick it up: `socialbot run`")
        return
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
        detail = res.get("url") or res.get("error") or "ok"
        parts = res.get("parts")
        if parts:
            detail = f"{detail} (thread: {len(parts)} parts)"
        click.echo(f"{mark} {platform_name}: {detail}")
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


# ------------------------------------------------------------------- analyze
@cli.command()
@click.argument("text")
def analyze(text: str):
    """Sentiment + intent analysis with a suggested reply (NLP, fully offline)."""
    from .intelligence import analyze as analyze_text
    result = analyze_text(text)
    click.echo(f"sentiment: {result['label']} ({result['sentiment']:+.2f})")
    click.echo(f"intent:    {result['intent']}")
    click.echo(f"topics:    {', '.join(result['topics']) or '—'}")
    click.echo(f"\nsuggested reply:\n{result['suggested_reply']}")


# --------------------------------------------------------------------- feeds
@cli.command("feeds")
@click.argument("action", type=click.Choice(["add", "list", "pull", "remove"]))
@click.option("--name", default=None, help="feed name")
@click.option("--url", default=None, help="RSS URL (for kind=rss)")
@click.option("--kind", default="rss", type=click.Choice(["rss", "curated"]))
@click.option("--n", "n_drafts", default=3, show_default=True,
              help="drafts to create per pull")
@click.option("--to", "targets", default=None,
              help="default platforms for drafts (comma separated)")
@click.option("--feed-id", default=None, help="feed id for remove/pull")
def feeds(action: str, name: Optional[str], url: Optional[str], kind: str,
          n_drafts: int, targets: Optional[str], feed_id: Optional[str]):
    """Manage content sources (RSS / curated) that auto-generate drafts."""
    store = get_store()
    if action == "add":
        if not name:
            raise click.ClickException("--name is required")
        if kind == "rss" and not url:
            raise click.ClickException("--url is required for rss feeds")
        feed = FeedSource(name=name, kind=kind, url=url or "",
                          n_drafts=n_drafts,
                          target_platforms=[p.strip() for p in (targets or "").split(",")
                                            if p.strip()])
        store.save_feed(feed)
        click.echo(f"✅ added feed '{feed.name}' [{feed.id}]")
        return
    if action == "list":
        feeds_list = store.list_feeds()
        if not feeds_list:
            click.echo("no feeds — add one: `socialbot feeds add --name blog --url https://…/rss`")
            return
        for f in feeds_list:
            state = "✅" if f.enabled else "⏸"
            click.echo(f"{state} {f.name:<20} {f.kind:<8} {f.url or f'{len(f.items)} curated items':<30} [{f.id}]")
        return
    if action == "remove":
        if not feed_id:
            raise click.ClickException("--feed-id is required")
        click.echo("removed" if store.delete_feed(feed_id) else "not found")
        return
    if action == "pull":
        from .feeds import run_feed
        feeds_list = store.list_feeds()
        if feed_id:
            feeds_list = [f for f in feeds_list if f.id == feed_id]
        if not feeds_list:
            click.echo("no feeds configured")
            return
        for f in feeds_list:
            result = run_feed(f, store)
            click.echo(f"• {f.name}: {'✅' if result.get('ok') else '❌'} "
                       f"{result.get('items', 0)} items, {result.get('new', 0)} new, "
                       f"{result.get('drafts', 0)} draft(s) "
                       f"{result.get('error', '')}")


# --------------------------------------------------------------- monitors
@cli.command("monitor")
@click.argument("action", type=click.Choice(["add", "list", "run", "remove"]))
@click.option("--name", default=None, help="monitor name")
@click.option("--platform", "platform_name", default="mock",
              help="platform to watch (needs search)")
@click.option("--query", default=None, help="hashtag / keyword / @mention to watch")
@click.option("--act", "action_type", default="like",
              type=click.Choice(["like", "follow", "comment", "repost", "quote"]),
              help="engagement action")
@click.option("--comment", "comment_template", default="", help="comment template ({topic})")
@click.option("--per-run", default=5, show_default=True, type=int)
@click.option("--dry-run/--live", "dry_run", default=True)
@click.option("--monitor-id", default=None, help="monitor id for run/remove")
def monitor(action: str, name: Optional[str], platform_name: str, query: Optional[str],
            action_type: str, comment_template: str, per_run: int, dry_run: bool,
            monitor_id: Optional[str]):
    """Manage mention & hashtag monitors (background engagement agent)."""
    store = get_store()
    if action == "add":
        if not query:
            raise click.ClickException("--query is required (e.g. #python or @brand)")
        rule = MentionRule(name=name or f"watch {query}", platform=platform_name,
                           query=query, action=action_type,
                           comment_template=comment_template,
                           limit_per_run=per_run, dry_run=dry_run)
        store.save_monitor("mention", rule)
        click.echo(f"✅ added monitor '{rule.name}' [{rule.id}] "
                   f"({'dry-run' if dry_run else 'LIVE'})")
        return
    if action == "list":
        monitors = store.list_monitors(kind="mention")
        if not monitors:
            click.echo("no monitors — try: socialbot monitor add --query #python")
            return
        for m in monitors:
            r = m["rule"]
            click.echo(f"{'✅' if r.enabled else '⏸'} {r.name:<20} {r.platform:<10} "
                       f"{r.action:<8} {r.query:<20} "
                       f"({r.limit_per_run}/run) [{r.id}]")
        return
    if action == "remove":
        if not monitor_id:
            raise click.ClickException("--monitor-id is required")
        click.echo("removed" if store.delete_monitor(monitor_id) else "not found")
        return
    from .agents import AgentEngine
    results = AgentEngine(store).run_mentions(rule=monitor_id, dry_run=dry_run)
    if not results:
        click.echo("no monitors found")
        return
    for result in results:
        if result.get("ok"):
            click.echo(f"• {result.get('query')}: found {result.get('found')}, "
                       f"acted {result.get('acted')} "
                       f"({'dry-run' if result.get('dry_run') else 'LIVE'})")
        else:
            click.echo(f"• ❌ {result.get('error')}")


# -------------------------------------------------------------------- inbox
@cli.command("inbox")
@click.argument("action", type=click.Choice(["add", "list", "run", "remove"]))
@click.option("--name", default=None, help="responder name")
@click.option("--platform", "platform_name", default="mock",
              help="platform with inbox support (mock)")
@click.option("--intents", default="pricing,demo,thanks,complaint",
              help="comma-separated intents to auto-reply to")
@click.option("--reply", "reply_template", default="", help="reply template")
@click.option("--escalate", "escalate_webhook", default=None,
              help="webhook for complaints/unknown intents")
@click.option("--no-reply", "no_reply", is_flag=True,
              help="analyze & escalate only, never auto-reply")
@click.option("--inbox-id", default=None, help="rule id for run/remove")
def inbox(action: str, name: Optional[str], platform_name: str, intents: str,
          reply_template: str, escalate_webhook: Optional[str], no_reply: bool,
          inbox_id: Optional[str]):
    """Manage the inbox responder agent (auto-answers DMs by intent)."""
    store = get_store()
    if action == "add":
        rule = InboxRule(name=name or "inbox responder", platform=platform_name,
                         intents=[i.strip() for i in intents.split(",") if i.strip()],
                         auto_reply=not no_reply, reply_template=reply_template,
                         escalate_webhook=escalate_webhook)
        store.save_inbox_rule(rule)
        click.echo(f"✅ added responder '{rule.name}' [{rule.id}] "
                   f"(auto_reply={rule.auto_reply})")
        return
    if action == "list":
        rules = store.list_inbox_rules()
        if not rules:
            click.echo("no responders — `socialbot inbox add` to create one")
            return
        for r in rules:
            click.echo(f"{'✅' if r.enabled else '⏸'} {r.name:<20} {r.platform:<10} "
                       f"intents: {','.join(r.intents)} [{r.id}]")
        return
    if action == "remove":
        if not inbox_id:
            raise click.ClickException("--inbox-id is required")
        click.echo("removed" if store.delete_inbox_rule(inbox_id) else "not found")
        return
    from .agents import AgentEngine
    results = AgentEngine(store).run_inbox(rule=inbox_id)
    if not results:
        click.echo("no responders found")
        return
    for result in results:
        if result.get("ok"):
            click.echo(f"• messages {result.get('messages')}, replied {result.get('replied')}, "
                       f"escalated {result.get('escalated')}")
        else:
            click.echo(f"• ❌ {result.get('error')}")


# ------------------------------------------------------------------ trends
@cli.command()
@click.option("--no-drafts", is_flag=True, help="capture trends but don't create drafts")
def trends(no_drafts: bool):
    """Capture trending topics and (by default) create draft posts."""
    store = get_store()
    from .agents import AgentEngine
    reports = AgentEngine(store).run_trends(create_drafts=not no_drafts)
    if not reports:
        click.echo("no platform supports trending yet (mock does — add a mock account)")
        return
    for report in reports:
        if report.get("ok"):
            click.echo(f"• {report['platform']}: captured {report['captured']} topic(s)")
        else:
            click.echo(f"• {report['platform']}: ❌ {report.get('error')}")
    stored = store.list_trends(limit=15)
    if stored:
        click.echo("\nlatest trends:")
        for t in stored[:10]:
            click.echo(f"  • {t['topic']}  ({t['platform']}, {t['captured_at'][:16]})")


# ------------------------------------------------------------------- safety
@cli.command("safety")
@click.argument("action", type=click.Choice(["add", "list", "remove"]))
@click.option("--type", "list_type", default="blacklist",
              type=click.Choice(["blacklist", "whitelist"]))
@click.option("--platform", "platform_name", default="", help="platform (empty = all)")
@click.option("--username", default=None, help="username to add")
@click.option("--note", default="", help="why (for transparency)")
@click.option("--rule-id", default=None, help="rule id for remove")
def safety(action: str, list_type: str, platform_name: str, username: Optional[str],
           note: str, rule_id: Optional[str]):
    """Blacklist/whitelist — accounts the agents must never/always engage."""
    store = get_store()
    from .safety import Safety
    safety = Safety(store)
    if action == "add":
        if not username:
            raise click.ClickException("--username is required")
        rule = safety.add(list_type, platform_name, username, note)
        click.echo(f"✅ {rule.list_type} added: @{rule.username} "
                   f"(platform: {rule.platform or 'all'})")
        return
    if action == "list":
        rules = safety.list()
        if not rules:
            click.echo("no safety rules — blacklist spammers/competitors, whitelist fans")
            return
        for r in rules:
            click.echo(f"• {r.list_type:<10} @{r.username:<24} {r.platform or 'all':<10} "
                       f"{r.note} [{r.id}]")
        return
    if not rule_id:
        raise click.ClickException("--rule-id is required")
    click.echo("removed" if safety.remove(rule_id) else "not found")


# ----------------------------------------------------------------- profiles
@cli.command()
@click.option("--similar", "similar_to", default=None,
              help="comma-separated interests to find similar users for")
@click.option("--limit", default=15, show_default=True)
def profiles(similar_to: Optional[str], limit: int):
    """Show learned user profiles (and find similar users for targeting)."""
    store = get_store()
    if similar_to:
        from .profiles import similar_targets
        targets = similar_targets(store, "mock", [i.strip() for i in similar_to.split(",")],
                                  limit=limit)
        if not targets:
            click.echo("no similar users yet — run the bot/monitors first to build profiles")
            return
        click.echo(f"{len(targets)} similar user(s):")
        for t in targets:
            click.echo(f"• @{t['username']:<20} interests: {', '.join(t['interests'][:5])}")
        return
    profiles_list = store.list_profiles(limit=limit)
    if not profiles_list:
        click.echo("no profiles yet — run `socialbot bot --live` or the agents to build them")
        return
    for p in profiles_list:
        actions = p.data.get("actions", {})
        click.echo(f"• @{p.username:<24} {p.platform:<8} "
                   f"interests: {', '.join(p.data.get('interests', [])[:4]) or '—':<40} "
                   f"actions: {actions}")


# --------------------------------------------------------------- best-time
@cli.command("best-time")
@click.option("--platform", "platform_name", default=None,
              help="platform to analyse (default: all)")
def best_time(platform_name: Optional[str]):
    """Show your best engagement windows (from post + metrics history)."""
    store = get_store()
    from .adaptive import best_times, human_window
    windows = best_times(store, platform_name)
    if not windows:
        click.echo("not enough history yet — publish at least a few posts and "
                   "run `socialbot analytics --refresh`")
        return
    click.echo("best engagement windows:")
    for i, w in enumerate(windows[:8], 1):
        click.echo(f"{i}. {human_window(w):<18} avg engagement {w['avg_engagement']:.1f} "
                   f"({w['posts']} post(s))")


# ------------------------------------------------------------------ report
@cli.command()
@click.option("--month", default=None, help="month as YYYY-MM (default: last month)")
@click.option("--webhook", default=None, help="deliver the report to a webhook")
def report(month: Optional[str], webhook: Optional[str]):
    """Generate the monthly growth report."""
    from .reports import monthly_report, render_report, save_and_deliver
    store = get_store()
    data = save_and_deliver(store, month, webhook=webhook)
    click.echo(render_report(data))
