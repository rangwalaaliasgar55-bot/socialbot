"""SocialBot REST API (FastAPI) + embedded dashboard.

Everything the dashboard does is available as JSON under /api — use it from
n8n, Make.com, Zapier, cron or your own scripts, the same way Postiz exposes
a public API.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from .. import ai as ai_mod
from ..analytics import refresh_metrics, summary, to_csv
from ..bot import BotEngine
from ..http import HttpClient
from ..models import BotRule, Post, PostStatus, dumps, iso, parse_dt, utcnow
from ..platforms import PlatformError, platform_meta, platform_names, create_platform
from ..publisher import Publisher
from ..scheduler import Scheduler
from ..storage import Store, DEFAULT_DB

log = logging.getLogger("socialbot.api")

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
SECRET_KEYS = {field["key"] for meta in platform_meta()
               for field in meta["auth_fields"] if field.get("secret")}
API_TOKEN = os.environ.get("SOCIALBOT_API_TOKEN", "").strip()

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


class AccountIn(BaseModel):
    platform: str
    label: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


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
        post = Post(text=body.text, media=body.media, platforms=body.platforms,
                    tag=body.tag, signature=body.signature, webhook_url=body.webhook_url,
                    recurrence=body.recurrence,
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

    return app


# Module-level app for `uvicorn socialbot.api.app:app` and package imports.
# Skip auto-creation (and scheduler start) when tests set the env var or
# when pytest is collecting, to avoid side effects and disk issues.
if os.environ.get("SOCIALBOT_NO_AUTO_APP") or "pytest" in sys.modules:
    app = None  # type: ignore
else:
    app = create_app(with_scheduler=os.environ.get("SOCIALBOT_DISABLE_SCHEDULER") != "1")
