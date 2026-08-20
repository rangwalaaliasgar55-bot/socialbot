"""SocialBot REST API (FastAPI) + embedded dashboard.

Everything the dashboard does is available as JSON under /api — use it from
n8n, Make.com, Zapier, cron or your own scripts, the same way Postiz exposes
a public API.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from .. import ai as ai_mod
from ..agents import AgentEngine
from ..ai_engine import AIEngine, ContentStrategy
from ..analytics import refresh_metrics, summary, to_csv
from ..bot import BotEngine
from ..coordination import get_coordinator
from ..http import HttpClient
from ..models import (BotRule, CompetitorRule, FeedSource, InboxRule, MentionRule,
                      Post, PostStatus, dumps, iso, parse_dt, utcnow)
from ..monitoring import get_monitoring
from ..oauth import (PENDING_STATES, STATE_TTL, build_auth_url, exchange_code,
                     new_state)
from ..platforms import PlatformError, platform_meta, platform_names, create_platform
from ..publisher import Publisher
from ..scheduler import Scheduler
from ..storage import Store, DEFAULT_DB

log = logging.getLogger("socialbot.api")

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
SECRET_KEYS = {field["key"] for meta in platform_meta()
               for field in meta["auth_fields"] if field.get("secret")}
API_TOKEN = os.environ.get("SOCIALBOT_API_TOKEN", "").strip()


def platform_meta_by_name(name: str) -> Optional[dict]:
    try:
        return next((m for m in platform_meta() if m["name"] == name), None)
    except Exception:
        return None


def _oauth_page(title: str, message: str, platform: str = "") -> str:
    """Minimal page shown after the OAuth callback (rendered in the popup)."""
    notify = (f"<script>try{{if(window.opener)window.opener.postMessage("
              f"{{type:'socialbot-oauth-done',platform:'{platform}'}},location.origin);"
              f"}}catch(e){{}}</script>") if platform else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SocialBot</title></head>
<body style="font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
display:grid;place-items:center;min-height:100vh;margin:0">
<div style="text-align:center;max-width:440px;padding:24px">
<h2>{title}</h2><p>{message}</p>
{notify}
<script>setTimeout(function(){{ try {{ window.close(); }} catch (e) {{}} }}, 1500);</script>
</div></body></html>"""

# --------------------------------------------------------------------- models
class PostIn(BaseModel):
    text: str
    platforms: List[str] = Field(default_factory=list)
    media: List[str] = Field(default_factory=list)
    scheduled_at: Optional[str] = None
    recurrence: Optional[Dict[str, Any]] = None
    tag: Optional[str] = None
    signature: Optional[str] = None
    webhook_url: Optional[str] = None
    publish_now: bool = False
    variants: Dict[str, str] = Field(default_factory=dict)
    thread: bool = False
    thread_parts: List[str] = Field(default_factory=list)
    best_time: bool = False
    origin: Optional[str] = None


class PostPatch(BaseModel):
    """Partial update for draft/scheduled posts — only provided fields change."""
    text: Optional[str] = None
    platforms: Optional[List[str]] = None
    media: Optional[List[str]] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[Dict[str, Any]] = None
    tag: Optional[str] = None
    signature: Optional[str] = None
    webhook_url: Optional[str] = None
    variants: Optional[Dict[str, str]] = None
    thread: Optional[bool] = None
    best_time: Optional[bool] = None


class AccountIn(BaseModel):
    platform: str
    label: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class OAuthStartIn(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""


class GenerateIn(BaseModel):
    topic: str
    n: int = 3
    tone: str = "friendly"


class RuleIn(BaseModel):
    name: str = "untitled rule"
    platform: str
    action: str = "like"
    trigger_type: str = "keyword"
    trigger_value: str = ""
    comment_template: str = ""
    limit_per_run: int = 5
    limit_per_hour: int = 20
    dry_run: bool = True
    enabled: bool = True
    interests: str = ""
    min_sentiment: float = 0.0
    whitelist_only: bool = False
    skip_blacklisted: bool = True
    max_per_day: int = 200


class MentionRuleIn(BaseModel):
    name: str = "untitled monitor"
    platform: str
    query: str = ""
    action: str = "like"
    comment_template: str = ""
    limit_per_run: int = 5
    limit_per_hour: int = 20
    dry_run: bool = True
    dedupe: bool = True
    min_sentiment: float = 0.0
    whitelist_only: bool = False
    skip_blacklisted: bool = True
    enabled: bool = True


class CompetitorRuleIn(BaseModel):
    name: str = "untitled watch"
    platform: str
    competitors: List[str] = Field(default_factory=list)
    interests: str = ""
    create_drafts: bool = True
    limit_per_competitor: int = 10
    enabled: bool = True


class InboxRuleIn(BaseModel):
    name: str = "untitled responder"
    platform: str
    intents: List[str] = Field(default_factory=list)
    auto_reply: bool = True
    reply_template: str = ""
    escalate_webhook: Optional[str] = None
    max_per_run: int = 10
    enabled: bool = True


class FeedIn(BaseModel):
    name: str
    kind: str = "rss"
    url: str = ""
    items: List[Dict[str, Any]] = Field(default_factory=list)
    interval_min: int = 60
    n_drafts: int = 3
    auto_draft: bool = True
    target_platforms: List[str] = Field(default_factory=list)
    enabled: bool = True


class SafetyIn(BaseModel):
    list_type: str = "blacklist"
    platform: str = ""
    username: str
    note: str = ""


class AnalyzeIn(BaseModel):
    text: str


class TaskIn(BaseModel):
    task_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    max_retries: int = 3


class StrategyIn(BaseModel):
    topic: str
    platform: str = "linkedin"
    tone: str = "professional yet empathetic"
    target_audience: str = "general audience"
    trending_keywords: List[str] = Field(default_factory=list)
    seo_goal: str = "engagement"


class ReviewApproveIn(BaseModel):
    platforms: List[str] = Field(default_factory=list)
    scheduled_at: Optional[str] = None  # ISO time, or "now" for immediate publish
    best_time: bool = False


class ReviewRejectIn(BaseModel):
    note: str = ""


# ----------------------------------------------------------------------- app
def create_app(store: Optional[Store] = None, with_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="SocialBot API", version=__version__,
                  description="All-in-one social media scheduling & automation bot")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        token = os.environ.get("SOCIALBOT_API_TOKEN", "").strip() or API_TOKEN
        if not token:
            return await call_next(request)
        path = request.url.path
        if path.startswith("/api/") or path in ("/docs", "/redoc", "/openapi.json"):
            expected = f"Bearer {token}"
            if request.headers.get("authorization") != expected:
                return PlainTextResponse("unauthorized", status_code=401)
        return await call_next(request)

    state: Dict[str, Any] = {"store": store or Store()}
    state["http"] = HttpClient()
    state["publisher"] = Publisher(state["store"], state["http"])
    state["scheduler"] = Scheduler(state["store"], state["publisher"])
    state["bot"] = BotEngine(state["store"], state["http"])
    state["agents"] = AgentEngine(state["store"], state["http"])
    state["coordinator"] = get_coordinator(store=state["store"])
    state["monitoring"] = get_monitoring()
    app.state.sb = state

    if with_scheduler:
        state["scheduler"].start()

    # ------------------------------------------------------------ dashboard
    if DASHBOARD_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(str(DASHBOARD_DIR / "index.html"))

    # ---------------------------------------------------------------- meta
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "now": iso(utcnow()),
                "scheduler": state["scheduler"].status()}

    @app.get("/api/platforms")
    def platforms():
        accounts = {a["platform"]: a for a in state["store"].list_accounts()}
        out = []
        for meta in platform_meta():
            acc = accounts.get(meta["name"])
            platform = create_platform(meta["name"], (acc or {}).get("config", {}), state["http"])
            out.append({**meta,
                        "configured": bool(acc) and platform.is_configured(),
                        "label": (acc or {}).get("label", ""),
                        "signature": (acc or {}).get("config", {}).get("signature", "")})
        return out

    # --------------------------------------------------------------- posts
    @app.get("/api/posts")
    def list_posts(status: Optional[str] = None, limit: int = 500):
        return [p.to_dict() for p in state["store"].list_posts(status, limit)]

    @app.post("/api/posts", status_code=201)
    def create_post(body: PostIn):
        if not body.platforms:
            raise HTTPException(422, "choose at least one platform")
        unknown = [p for p in body.platforms if p not in platform_names()]
        if unknown:
            raise HTTPException(422, f"unknown platforms: {', '.join(unknown)}")
        scheduled = parse_dt(body.scheduled_at) if body.scheduled_at else None
        if body.best_time and scheduled is None:
            from ..adaptive import suggest_time
            picked = suggest_time(state["store"], body.platforms[0])
            scheduled = parse_dt(picked) if picked else utcnow()
        post = Post(text=body.text, media=body.media, platforms=body.platforms,
                    tag=body.tag, signature=body.signature, webhook_url=body.webhook_url,
                    recurrence=body.recurrence, variants=body.variants,
                    thread=body.thread, thread_parts=body.thread_parts,
                    best_time=body.best_time, origin=body.origin,
                    scheduled_at=iso(scheduled) if scheduled else None)
        if body.publish_now or scheduled is None and not body.recurrence:
            return state["publisher"].publish_now(post).to_dict()
        post.status = PostStatus.SCHEDULED.value
        state["store"].save_post(post)
        return post.to_dict()

    @app.get("/api/posts/{post_id}")
    def get_post(post_id: str):
        post = state["store"].get_post(post_id)
        if not post:
            raise HTTPException(404, "post not found")
        return post.to_dict()

    @app.delete("/api/posts/{post_id}")
    def delete_post(post_id: str):
        if not state["store"].delete_post(post_id):
            raise HTTPException(404, "post not found")
        return {"ok": True, "deleted": post_id}

    @app.post("/api/posts/{post_id}/publish")
    def publish_post(post_id: str):
        post = state["store"].get_post(post_id)
        if not post:
            raise HTTPException(404, "post not found")
        return state["publisher"].publish_now(post).to_dict()

    @app.post("/api/posts/{post_id}/retry")
    def retry_post(post_id: str):
        result = state["publisher"].retry(post_id)
        if not result:
            raise HTTPException(404, "post not found")
        return result.to_dict()

    @app.post("/api/posts/{post_id}/remote")
    def delete_remote(post_id: str):
        """Delete the post from every platform that supports remote deletion."""
        post = state["store"].get_post(post_id)
        if not post:
            raise HTTPException(404, "post not found")
        outcomes = {}
        for platform_name, result in (post.results or {}).items():
            if not result.get("ok") or not result.get("remote_id"):
                continue
            try:
                account = state["store"].get_account(platform_name)
                platform = create_platform(platform_name,
                                           (account or {}).get("config", {}), state["http"])
                if "delete" not in platform.capabilities:
                    outcomes[platform_name] = "not supported"
                    continue
                platform.delete(result["remote_id"])
                outcomes[platform_name] = "deleted"
            except PlatformError as exc:
                outcomes[platform_name] = f"error: {exc}"
        if not outcomes:
            raise HTTPException(400, "no published platforms with remote delete support")
        state["store"].log_event("post.delete_remote", f"remote delete for {post.id}: {outcomes}")
        return {"ok": True, "outcomes": outcomes}

    @app.patch("/api/posts/{post_id}")
    def patch_post(post_id: str, body: PostPatch):
        """Edit a draft/scheduled post (text, platforms, media, schedule, tag…)."""
        post = state["store"].get_post(post_id)
        if not post:
            raise HTTPException(404, "post not found")
        if post.status not in (PostStatus.DRAFT.value, PostStatus.SCHEDULED.value):
            raise HTTPException(400, "only draft or scheduled posts can be edited")
        if body.text is not None:
            post.text = body.text
        if body.platforms is not None:
            unknown = [p for p in body.platforms if p not in platform_names()]
            if unknown:
                raise HTTPException(422, f"unknown platforms: {', '.join(unknown)}")
            if not body.platforms:
                raise HTTPException(422, "choose at least one platform")
            post.platforms = body.platforms
        if body.media is not None:
            post.media = body.media
        if body.tag is not None:
            post.tag = body.tag or None
        if body.signature is not None:
            post.signature = body.signature or None
        if body.webhook_url is not None:
            post.webhook_url = body.webhook_url or None
        if body.recurrence is not None:
            post.recurrence = body.recurrence
        if body.scheduled_at is not None:
            scheduled = parse_dt(body.scheduled_at)
            post.scheduled_at = iso(scheduled) if scheduled else None
        if body.variants is not None:
            post.variants = body.variants
        if body.thread is not None:
            post.thread = body.thread
        if body.best_time is not None:
            post.best_time = body.best_time
        state["store"].save_post(post)
        return post.to_dict()

    @app.post("/api/scheduler/{action}")
    def scheduler_control(action: str):
        if action == "start":
            state["scheduler"].start()
        elif action == "stop":
            state["scheduler"].stop()
        elif action == "tick":
            processed = state["publisher"].process_due()
            return {"ok": True, "processed": len(processed)}
        else:
            raise HTTPException(400, "action must be start|stop|tick")
        return {"ok": True, "scheduler": state["scheduler"].status()}

    # ------------------------------------------------------------ accounts
    @app.get("/api/accounts")
    def list_accounts():
        return [{**a, "config": {k: ("•••" if k in SECRET_KEYS and v else v)
                                 for k, v in a["config"].items()}}
                for a in state["store"].list_accounts()]

    @app.post("/api/accounts", status_code=201)
    def upsert_account(body: AccountIn):
        if body.platform not in platform_names():
            raise HTTPException(422, f"unknown platform '{body.platform}'")
        # merge with existing so partial updates don't wipe secrets
        existing = state["store"].get_account(body.platform) or {"config": {}}
        config = dict(existing.get("config", {}))
        for k, v in body.config.items():
            if v == "•••":
                continue
            config[k] = v
        account = state["store"].save_account(body.platform, config, body.label, body.enabled)
        # verify credentials
        platform = create_platform(body.platform, config, state["http"])
        ok, message = platform.verify()
        state["store"].log_event("account.save", f"{body.platform}: {message}",
                                 {"platform": body.platform})
        return {**account, "verified": ok, "verify_message": message}

    @app.delete("/api/accounts/{platform}")
    def delete_account(platform: str):
        return {"ok": state["store"].delete_account(platform)}

    @app.post("/api/accounts/{platform}/verify")
    def verify_account(platform: str):
        account = state["store"].get_account(platform)
        if not account:
            raise HTTPException(404, "no account for this platform")
        p = create_platform(platform, account["config"], state["http"])
        ok, message = p.verify()
        return {"ok": ok, "message": message}

    # ------------------------------------------------------------ oauth flow
    @app.post("/api/accounts/{platform}/oauth/start")
    def oauth_start(platform: str, body: OAuthStartIn, request: Request):
        """One-click connect: returns the provider's authorization URL.

        The dashboard opens it in a popup; the provider redirects back to
        ``/api/accounts/{platform}/oauth/callback`` where tokens are exchanged
        and stored. Client id/secret are saved with the account first so the
        callback can use them.
        """
        meta = platform_meta_by_name(platform)
        if not meta or not meta.get("oauth"):
            raise HTTPException(400, f"{platform} does not support one-click OAuth "
                                     f"— connect it manually in the form below")
        existing = state["store"].get_account(platform) or {"config": {}}
        config = dict(existing.get("config", {}))
        oauth = meta["oauth"]
        for key, value in ((oauth.get("client_id_key", "client_id"), body.client_id),
                           (oauth.get("client_secret_key", "client_secret"), body.client_secret)):
            if value:
                config[key] = value
        if not config.get(oauth.get("client_id_key", "client_id")):
            raise HTTPException(400, f"missing {oauth.get('client_id_key', 'client_id')} — "
                                     f"paste it first (see the guide above)")
        state["store"].save_account(platform, config, existing.get("label", ""),
                                    existing.get("enabled", True))

        base = str(request.base_url).rstrip("/")
        redirect_uri = body.redirect_uri or f"{base}/api/accounts/{platform}/oauth/callback"
        state_token = new_state()
        try:
            auth_url, verifier = build_auth_url(platform, config["client_id"],
                                                redirect_uri, state_token)
        except PlatformError as exc:
            raise HTTPException(400, str(exc))
        PENDING_STATES[state_token] = {"platform": platform, "redirect_uri": redirect_uri,
                                       "verifier": verifier,
                                       "expires": utcnow().timestamp() + STATE_TTL}
        return {"auth_url": auth_url, "redirect_uri": redirect_uri, "state": state_token}

    @app.get("/api/accounts/{platform}/oauth/callback")
    def oauth_callback(platform: str, code: str = "",
                       oauth_state: str = Query("", alias="state"), error: str = ""):
        """Provider redirect target. Exchanges the code and stores the tokens."""
        pending = PENDING_STATES.pop(oauth_state, None)
        if pending is None or pending["platform"] != platform:
            return HTMLResponse(_oauth_page("❌ Authorization failed",
                                            "Unknown or expired session — start the connect flow again.",
                                            platform))
        if error:
            return HTMLResponse(_oauth_page("❌ Authorization denied",
                                            f"The provider returned: {error}. Nothing was saved.",
                                            platform))
        if not code:
            return HTMLResponse(_oauth_page("❌ Missing code",
                                            "No code received from the provider.", platform))
        account = state["store"].get_account(platform)
        if not account:
            return HTMLResponse(_oauth_page("❌ No account",
                                            f"No {platform} account found — save one first.", platform))
        config = dict(account.get("config", {}))
        oauth = platform_meta_by_name(platform)["oauth"]
        cid = config.get(oauth.get("client_id_key", "client_id"), "")
        secret = config.get(oauth.get("client_secret_key", "client_secret"), "")
        try:
            updates = exchange_code(platform, cid, secret, code, pending["redirect_uri"],
                                    pending.get("verifier"), state["http"])
        except PlatformError as exc:
            return HTMLResponse(_oauth_page("❌ Token exchange failed", str(exc), platform))
        config.update(updates)
        state["store"].save_account(platform, config, account.get("label", ""),
                                    account.get("enabled", True))
        state["store"].log_event("account.oauth", f"{platform} connected via OAuth",
                                 {"platform": platform})
        return HTMLResponse(_oauth_page("✅ Connected!",
                                        f"{platform} is now connected. You can close this window.",
                                        platform))

    # ------------------------------------------------------------ bot rules
    @app.get("/api/bot/rules")
    def list_rules():
        return [r.to_dict() for r in state["store"].list_rules()]

    @app.post("/api/bot/rules", status_code=201)
    def create_rule(body: RuleIn):
        rule = BotRule(**body.model_dump())
        state["store"].save_rule(rule)
        return rule.to_dict()

    @app.patch("/api/bot/rules/{rule_id}")
    def patch_rule(rule_id: str, body: RuleIn):
        rule = state["store"].get_rule(rule_id)
        if not rule:
            raise HTTPException(404, "rule not found")
        for key, value in body.model_dump().items():
            setattr(rule, key, value)
        state["store"].save_rule(rule)
        return rule.to_dict()

    @app.post("/api/bot/rules/{rule_id}/run")
    def run_rule(rule_id: str, dry_run: Optional[bool] = None):
        rule = state["store"].get_rule(rule_id)
        if not rule:
            raise HTTPException(404, "rule not found")
        return state["bot"].run_rule(rule, dry_run)

    @app.post("/api/bot/run")
    def run_all_rules(dry_run: Optional[bool] = None):
        return {"results": state["bot"].run_all(dry_run)}

    @app.delete("/api/bot/rules/{rule_id}")
    def delete_rule(rule_id: str):
        return {"ok": state["store"].delete_rule(rule_id)}

    # ----------------------------------------------------------- analytics
    @app.get("/api/analytics/summary")
    def analytics_summary():
        return summary(state["store"])

    @app.get("/api/analytics/export.csv")
    def analytics_export():
        return PlainTextResponse(to_csv(state["store"]), media_type="text/csv",
                                 headers={"Content-Disposition":
                                          "attachment; filename=socialbot-analytics.csv"})

    @app.post("/api/analytics/refresh")
    def analytics_refresh():
        updated = refresh_metrics(state["store"], state["http"])
        return {"ok": True, "updated": updated}

    # ------------------------------------------------------------------ AI
    @app.post("/api/generate")
    def generate(body: GenerateIn):
        return {"drafts": ai_mod.generate(body.topic, body.n, body.tone)}

    # -------------------------------------------------------------- events
    @app.get("/api/events")
    def events(limit: int = 100):
        return state["store"].list_events(limit)

    # ---------------------------------------------------------------- analyze
    @app.post("/api/analyze")
    def analyze(body: AnalyzeIn):
        from ..intelligence import analyze as nlp_analyze
        return nlp_analyze(body.text)

    # ------------------------------------------------------------ safety lists
    @app.get("/api/safety")
    def list_safety(list_type: Optional[str] = None):
        from ..safety import Safety
        return [r.to_dict() for r in Safety(state["store"]).list(list_type)]

    @app.post("/api/safety", status_code=201)
    def add_safety(body: SafetyIn):
        from ..safety import Safety
        return Safety(state["store"]).add(body.list_type, body.platform,
                                          body.username, body.note).to_dict()

    @app.delete("/api/safety/{rule_id}")
    def delete_safety(rule_id: str):
        from ..safety import Safety
        return {"ok": Safety(state["store"]).remove(rule_id)}

    # ---------------------------------------------------------------- profiles
    @app.get("/api/profiles")
    def list_profiles(limit: int = 200):
        return [p.to_dict() for p in state["store"].list_profiles(limit)]

    @app.get("/api/profiles/similar")
    def similar_profiles(interests: str, platform: str = "mock", limit: int = 10):
        from ..profiles import similar_targets
        return similar_targets(state["store"], platform,
                               [i.strip() for i in interests.split(",") if i.strip()],
                               limit=limit)

    # -------------------------------------------------------------- feed sources
    @app.get("/api/feeds")
    def list_feeds():
        return [f.to_dict() for f in state["store"].list_feeds()]

    @app.post("/api/feeds", status_code=201)
    def create_feed(body: FeedIn):
        if body.kind == "rss" and not body.url:
            raise HTTPException(422, "rss feeds need a url")
        feed = FeedSource(**body.model_dump())
        state["store"].save_feed(feed)
        return feed.to_dict()

    @app.post("/api/feeds/{feed_id}/run")
    def run_feed(feed_id: str):
        from ..feeds import run_feed as run_feed_fn
        feed = next((f for f in state["store"].list_feeds() if f.id == feed_id), None)
        if not feed:
            raise HTTPException(404, "feed not found")
        return run_feed_fn(feed, state["store"], state["http"])

    @app.delete("/api/feeds/{feed_id}")
    def delete_feed(feed_id: str):
        return {"ok": state["store"].delete_feed(feed_id)}

    # ------------------------------------------------------- monitors (mention/competitor)
    @app.get("/api/monitors")
    def list_monitors():
        out = []
        for item in state["store"].list_monitors():
            out.append({"kind": item["kind"], **item["rule"].to_dict()})
        return out

    @app.post("/api/monitors/mention", status_code=201)
    def create_mention_monitor(body: MentionRuleIn):
        rule = MentionRule(**body.model_dump())
        state["store"].save_monitor("mention", rule)
        return {"kind": "mention", **rule.to_dict()}

    @app.post("/api/monitors/competitor", status_code=201)
    def create_competitor_monitor(body: CompetitorRuleIn):
        rule = CompetitorRule(**body.model_dump())
        state["store"].save_monitor("competitor", rule)
        return {"kind": "competitor", **rule.to_dict()}

    @app.post("/api/monitors/mention/{rule_id}/run")
    def run_mention_monitor(rule_id: str, dry_run: Optional[bool] = None):
        results = state["agents"].run_mentions(rule=rule_id, dry_run=dry_run)
        if not results:
            raise HTTPException(404, "monitor not found")
        return results[0]

    @app.post("/api/monitors/competitor/{rule_id}/run")
    def run_competitor_monitor(rule_id: str):
        results = state["agents"].run_competitors(rule=rule_id)
        if not results:
            raise HTTPException(404, "watch not found")
        return results[0]

    @app.delete("/api/monitors/{monitor_id}")
    def delete_monitor(monitor_id: str):
        return {"ok": state["store"].delete_monitor(monitor_id)}

    # ------------------------------------------------------------------ inbox
    @app.get("/api/inbox")
    def list_inbox_rules():
        return [r.to_dict() for r in state["store"].list_inbox_rules()]

    @app.post("/api/inbox", status_code=201)
    def create_inbox_rule(body: InboxRuleIn):
        rule = InboxRule(**body.model_dump())
        state["store"].save_inbox_rule(rule)
        return rule.to_dict()

    @app.post("/api/inbox/{rule_id}/run")
    def run_inbox_rule(rule_id: str):
        results = state["agents"].run_inbox(rule=rule_id)
        if not results:
            raise HTTPException(404, "rule not found")
        return results[0]

    @app.delete("/api/inbox/{rule_id}")
    def delete_inbox_rule(rule_id: str):
        return {"ok": state["store"].delete_inbox_rule(rule_id)}

    # ----------------------------------------------------------------- trends
    @app.get("/api/trends")
    def list_trends(platform: Optional[str] = None, limit: int = 100):
        return state["store"].list_trends(platform, limit)

    @app.post("/api/trends/capture")
    def capture_trends(create_drafts: bool = True):
        return {"reports": state["agents"].run_trends(create_drafts=create_drafts)}

    # ------------------------------------------------------------ agents / all
    @app.post("/api/agents/run")
    def run_agents():
        return state["agents"].run_all()

    # ----------------------------------------------------------------- adaptive
    @app.get("/api/adapt/best-time")
    def best_time_endpoint(platform: Optional[str] = None):
        from ..adaptive import best_times, human_window, schedule_summary
        return schedule_summary(state["store"])

    @app.post("/api/adapt/suggest-time")
    def suggest_time_endpoint(platform: Optional[str] = None):
        from ..adaptive import suggest_time
        return {"scheduled_at": suggest_time(state["store"], platform)}

    @app.post("/api/adapt/vibe")
    def vibe_fit_endpoint(body: AnalyzeIn, platform: Optional[str] = None):
        from ..adaptive import vibe_fit
        return vibe_fit(state["store"], body.text, platform)

    @app.post("/api/adapt/hashtags")
    def adaptive_hashtags_endpoint(body: AnalyzeIn, platform: Optional[str] = None):
        from ..adaptive import adaptive_hashtags
        return {"hashtags": adaptive_hashtags(state["store"], body.text, platform)}

    # ----------------------------------------------------------------- reports
    @app.get("/api/reports")
    def get_report(month: Optional[str] = None):
        from ..reports import monthly_report
        return monthly_report(state["store"], month)

    @app.post("/api/reports")
    def make_report(month: Optional[str] = None, webhook: Optional[str] = None):
        from ..reports import save_and_deliver
        return save_and_deliver(state["store"], month, webhook)

    # ------------------------------------------------------ coordination & tasks
    @app.get("/api/agents")
    def list_agent_workers(include_dead: bool = False):
        coordinator = state["coordinator"]
        return {"stats": coordinator.get_stats(),
                "agents": [a.to_dict() for a in coordinator.list_agents(include_dead)]}

    @app.get("/api/tasks")
    def list_tasks(status: Optional[str] = None, limit: int = 100):
        return {"tasks": [t.to_dict() for t in state["coordinator"].list_tasks(status, limit)]}

    @app.post("/api/tasks")
    def enqueue_task(body: TaskIn):
        task_id = state["coordinator"].enqueue_task(
            body.task_type, body.payload, body.priority, body.max_retries)
        return {"task_id": task_id}

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        task = state["coordinator"].get_task(task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        return task.to_dict()

    # ------------------------------------------------------------------ monitoring
    @app.get("/api/monitoring")
    def monitoring_status():
        monitoring = state["monitoring"]
        monitoring.health.run_checks()
        return {
            "health": monitoring.health.get_health_report(),
            "metrics": monitoring.metrics.get_all_metrics(),
            "resources": monitoring.resource_monitor.get_usage(),
            "timestamp": iso(utcnow()),
        }

    # --------------------------------------------------------- trend strategies
    @app.post("/api/trends/strategy")
    def trend_strategy(platform: str = "linkedin"):
        from ..trend_analyzer import RealTrendAnalyzer
        return RealTrendAnalyzer(session=state["http"].session).generate_content_strategy(platform)

    # ------------------------------------------------------------ AI content kit
    @app.post("/api/ai/content")
    def ai_content(body: StrategyIn):
        engine = AIEngine()
        strategy = ContentStrategy(
            topic=body.topic, platform=body.platform, tone=body.tone,
            target_audience=body.target_audience,
            trending_keywords=body.trending_keywords, seo_goal=body.seo_goal,
        )
        return engine.create_full_content_package(strategy).to_dict()

    # ------------------------------------------------------------ review queue
    @app.get("/api/review")
    def review_queue(limit: int = 100):
        pending = state["store"].list_posts_for_review("pending", limit)
        approved = state["store"].list_posts_for_review("approved", limit)
        rejected = state["store"].list_posts_for_review("rejected", limit)
        return {"pending": [p.to_dict() for p in pending],
                "approved": [p.to_dict() for p in approved],
                "rejected": [p.to_dict() for p in rejected],
                "stats": {"pending": len(pending), "approved": len(approved),
                          "rejected": len(rejected)}}

    @app.post("/api/review/{post_id}/approve")
    def review_approve(post_id: str, body: ReviewApproveIn):
        post = state["store"].get_post(post_id)
        if post is None:
            raise HTTPException(404, "post not found")
        if body.platforms:
            post.platforms = body.platforms
        post.review_status = "approved"
        post.reviewed_at = iso(utcnow())
        if body.scheduled_at == "now":
            post.status = PostStatus.SCHEDULED.value
            post.scheduled_at = iso(utcnow())
        elif body.scheduled_at:
            post.status = PostStatus.SCHEDULED.value
            post.scheduled_at = iso(parse_dt(body.scheduled_at))
        elif body.best_time:
            from ..adaptive import suggest_time
            post.status = PostStatus.SCHEDULED.value
            post.scheduled_at = suggest_time(state["store"],
                                             post.platforms[0] if post.platforms else None) \
                or iso(utcnow() + timedelta(hours=1))
        state["store"].save_post(post)
        state["store"].log_event("review.approve",
                                 f"post {post.id} approved (status={post.status})",
                                 {"post_id": post.id, "status": post.status,
                                  "platforms": post.platforms})
        return post.to_dict()

    @app.post("/api/review/{post_id}/reject")
    def review_reject(post_id: str, body: ReviewRejectIn):
        store = state["store"]
        if not store.set_review(post_id, "rejected"):
            raise HTTPException(404, "post not found")
        store.log_event("review.reject", f"post {post_id} rejected{': ' + body.note if body.note else ''}",
                        {"post_id": post_id, "note": body.note})
        return {"ok": True, "review_status": "rejected"}

    return app


# Module-level app for `uvicorn socialbot.api.app:app` and package imports.
# Skip auto-creation (and scheduler start) when tests set the env var or
# when pytest is collecting, to avoid side effects and disk issues.
if os.environ.get("SOCIALBOT_NO_AUTO_APP") or "pytest" in sys.modules:
    app = None  # type: ignore
else:
    app = create_app(with_scheduler=os.environ.get("SOCIALBOT_DISABLE_SCHEDULER") != "1")
