"""Storage layer tests."""
from socialbot.models import BotRule, Post, PostStatus


def test_save_and_get_post(store):
    post = Post(text="hello", platforms=["mock"], status=PostStatus.SCHEDULED.value,
                scheduled_at="2026-01-01T09:00:00+00:00", tag="launch")
    store.save_post(post)

    loaded = store.get_post(post.id)
    assert loaded is not None
    assert loaded.text == "hello"
    assert loaded.platforms == ["mock"]
    assert loaded.tag == "launch"
    assert loaded.status == "scheduled"


def test_save_post_upsert(store):
    post = Post(text="v1", platforms=["mock"])
    store.save_post(post)
    post.text = "v2"
    store.save_post(post)
    assert len(store.list_posts()) == 1
    assert store.get_post(post.id).text == "v2"


def test_list_posts_filter(store):
    store.save_post(Post(text="a", status="scheduled"))
    store.save_post(Post(text="b", status="published"))
    assert len(store.list_posts()) == 2
    assert len(store.list_posts(status="published")) == 1


def test_due_posts(store):
    store.save_post(Post(text="due", status="scheduled", scheduled_at="2026-01-01T00:00:00+00:00"))
    store.save_post(Post(text="later", status="scheduled", scheduled_at="2099-01-01T00:00:00+00:00"))
    store.save_post(Post(text="done", status="published", scheduled_at="2026-01-01T00:00:00+00:00"))
    due = store.due_posts("2026-06-01T00:00:00+00:00")
    assert [p.text for p in due] == ["due"]


def test_accounts_crud(store):
    store.save_account("mock", {"username": "me"}, label="demo")
    account = store.get_account("mock")
    assert account["label"] == "demo"
    assert account["config"]["username"] == "me"

    # upsert keeps a single row per platform
    store.save_account("mock", {"username": "you"}, label="other")
    accounts = store.list_accounts()
    assert len(accounts) == 1
    assert accounts[0]["config"]["username"] == "you"

    assert store.delete_account("mock") is True
    assert store.get_account("mock") is None


def test_rules_crud(store):
    rule = BotRule(name="r1", platform="mock", action="like", trigger_value="python")
    store.save_rule(rule)
    assert store.get_rule(rule.id).name == "r1"
    rule.enabled = False
    store.save_rule(rule)
    assert len(store.list_rules()) == 1
    assert len(store.list_rules(only_enabled=True)) == 0
    assert store.delete_rule(rule.id) is True


def test_metrics_and_events(store):
    store.save_metrics("p1", "mock", "m1", {"likes": 5})
    store.save_metrics("p1", "mock", "m1", {"likes": 9})
    store.save_metrics("p1", "telegram", "b1", {"likes": 2})
    latest = store.latest_metrics()
    assert len(latest) == 2                      # dedup per (post, platform)
    mock_row = next(r for r in latest if r["platform"] == "mock")
    assert mock_row["metrics"]["likes"] == 9     # most recent wins

    store.log_event("publish.ok", "published")
    events = store.list_events()
    assert events[0]["type"] == "publish.ok"


def test_post_roundtrip_json(store):
    post = Post(text="json", platforms=["a", "b"], media=["https://x/y.png"],
                recurrence={"type": "interval", "value": 60})
    store.save_post(post)
    loaded = store.get_post(post.id)
    assert loaded.recurrence == {"type": "interval", "value": 60}
    assert loaded.media == ["https://x/y.png"]
