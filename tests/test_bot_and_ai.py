"""Bot engine + AI generator tests."""
from socialbot.ai import generate, generate_offline, hashtags_for, llm_available
from socialbot.bot import BotEngine
from socialbot.models import BotRule


# ------------------------------------------------------------------ bot engine
def test_rule_runs_on_mock(store):
    store.save_account("mock", {})
    rule = BotRule(name="likes", platform="mock", action="like", trigger_type="hashtag",
                   trigger_value="python", limit_per_run=3, dry_run=True)
    store.save_rule(rule)
    engine = BotEngine(store)
    result = engine.run_rule(rule)
    assert result["ok"] is True
    assert result["acted"] == 3
    assert result["dry_run"] is True

    stored = store.get_rule(rule.id)
    assert stored.last_run
    assert stored.total_actions == 3


def test_rule_live_actions_counted(store):
    store.save_account("mock", {})
    rule = BotRule(name="comments", platform="mock", action="comment", trigger_type="keyword",
                   trigger_value="growth", comment_template="Great stuff about {topic}!",
                   limit_per_run=2, dry_run=False)
    store.save_rule(rule)
    result = BotEngine(store).run_rule(rule)
    assert result["ok"] and result["acted"] == 2 and not result["dry_run"]


def test_rule_requires_account(store):
    rule = BotRule(name="x", platform="mastodon", action="like", trigger_value="a")
    result = BotEngine(store).run_rule(rule)
    assert result["ok"] is False and "no account" in result["error"]


def test_rule_unsupported_action(store):
    store.save_account("discord", {"webhook_url": "https://x"})  # no 'like' capability
    rule = BotRule(name="x", platform="discord", action="like", trigger_value="a")
    result = BotEngine(store).run_rule(rule)
    assert result["ok"] is False and "does not support" in result["error"]


def test_run_all_enabled_only(store):
    store.save_account("mock", {})
    on = BotRule(name="on", platform="mock", action="like", trigger_value="a")
    off = BotRule(name="off", platform="mock", action="like", trigger_value="b", enabled=False)
    store.save_rule(on)
    store.save_rule(off)
    results = BotEngine(store).run_all()
    assert len(results) == 1


def test_hourly_budget_limits_actions(store):
    store.save_account("mock", {})
    rule = BotRule(name="capped", platform="mock", action="like", trigger_value="x",
                   limit_per_run=10, limit_per_hour=2)
    store.save_rule(rule)
    result = BotEngine(store).run_rule(rule)
    assert result["acted"] == 2  # capped by hourly budget


# ---------------------------------------------------------------------- AI
def test_offline_generation():
    drafts = generate_offline("python automation", n=3)
    assert len(drafts) == 3
    assert all("python" in d["text"].lower() or d["text"] for d in drafts)
    assert drafts[0]["engine"] == "template"
    assert drafts[0]["hashtags"]


def test_generate_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("SOCIALBOT_AI_API_KEY", raising=False)
    drafts = generate("topic", n=2)
    assert len(drafts) == 2
    assert llm_available() is False


def test_hashtags_clean():
    tags = hashtags_for("Social Media Growth!", n=2)
    assert all(t.startswith("#") for t in tags)
    assert len(tags) >= 2
