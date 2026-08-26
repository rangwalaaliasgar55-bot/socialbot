"""Agent Town — Stonic-style resident AI agents for SocialBot.

Four agents with desks/roles. They map to existing SocialBot capabilities
(content, engagement, trends, inbox) and report live status for the command center.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class Agent:
    id: str
    name: str
    role: str
    specialty: str
    status: str = "online"  # online | busy | idle
    current_task: str = ""
    desk: str = "A1"
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


RESIDENTS: List[Agent] = [
    Agent("alice", "Alice", "Content Lead", "AI drafts, captions, hooks", desk="A1"),
    Agent("bob", "Bob", "Growth Operator", "likes, follows, keyword rules", desk="B2"),
    Agent("carol", "Carol", "Trend Scout", "trends, RSS, competitor watch", desk="C1"),
    Agent("dave", "Dave", "Inbox Guard", "DM intent, auto-reply, escalate", desk="D3"),
]


class AgentTown:
    def __init__(self, store=None):
        self.store = store
        self.agents = {a.id: Agent(**{**a.to_dict()}) for a in RESIDENTS}

    def list_agents(self) -> List[Dict[str, Any]]:
        self._refresh_status()
        return [a.to_dict() for a in self.agents.values()]

    def _refresh_status(self) -> None:
        if self.store is None:
            return
        posts = self.store.list_posts(limit=50)
        rules = self.store.list_rules()
        pending = [p for p in posts if p.review_status == "pending"]
        scheduled = [p for p in posts if p.status == "scheduled"]

        alice = self.agents["alice"]
        alice.current_task = f"{len(scheduled)} scheduled · {len(pending)} in review" if posts else "awaiting brief"
        alice.status = "busy" if pending else "online"
        alice.stats = {"scheduled": len(scheduled), "review": len(pending)}

        bob = self.agents["bob"]
        enabled = [r for r in rules if r.enabled]
        bob.current_task = f"{len(enabled)} growth rules armed" if enabled else "no rules — idle at desk"
        bob.status = "online" if enabled else "idle"
        bob.stats = {"rules": len(enabled)}

        carol = self.agents["carol"]
        trends = self.store.list_trends(limit=5)
        feeds = self.store.list_feeds()
        carol.current_task = f"{len(trends)} trends · {len(feeds)} feeds" if trends or feeds else "scanning horizon"
        carol.status = "busy" if trends else "online"
        carol.stats = {"trends": len(trends), "feeds": len(feeds)}

        dave = self.agents["dave"]
        inbox = self.store.list_inbox_rules()
        dave.current_task = f"{len(inbox)} responders on watch" if inbox else "inbox quiet"
        dave.status = "online" if inbox else "idle"
        dave.stats = {"responders": len(inbox)}

    def assign(self, agent_id: str, task: str) -> Dict[str, Any]:
        agent = self.agents.get(agent_id)
        if not agent:
            return {"ok": False, "error": "unknown agent"}
        agent.current_task = task
        agent.status = "busy"
        if self.store:
            self.store.log_event("agent.assign", f"{agent.name}: {task}", {"agent": agent_id})
        return {"ok": True, "agent": agent.to_dict()}


def system_core(store=None) -> Dict[str, Any]:
    """Memory / Skills / Soul / Settings snapshot for the HUD."""
    chatgpt = False
    chatgpt_account = None
    if store is not None:
        try:
            from .chatgpt_oauth import ChatGPTOAuth
            c = ChatGPTOAuth(store=store)
            chatgpt = c.is_authenticated()
            chatgpt_account = c.account_id()
        except Exception:
            pass
    accounts = store.list_accounts() if store else []
    rules = store.list_rules() if store else []
    posts = store.list_posts(limit=200) if store else []
    return {
        "memory": {
            "label": "Memory",
            "value": f"{len(posts)} posts remembered",
            "detail": "local SQLite · zero telemetry of post content off-box",
        },
        "skills": {
            "label": "Skills",
            "value": f"{len(accounts)} networks · {len(rules)} bot skills",
            "detail": "publish · schedule · engage · analyze · generate",
        },
        "soul": {
            "label": "Soul",
            "value": "operator mode",
            "detail": "tone set per generate --tone; agents dry-run by default",
        },
        "settings": {
            "label": "Settings",
            "value": "ChatGPT " + ("linked" if chatgpt else "not linked"),
            "detail": chatgpt_account or "socialbot chatgpt login",
            "chatgpt_authenticated": chatgpt,
            "chatgpt_account_id": chatgpt_account,
        },
        "ts": datetime.now(timezone.utc).isoformat(),
    }
