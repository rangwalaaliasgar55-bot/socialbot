"""Publisher tests: fan-out, partial failure, retry, recurrence, webhooks."""
from unittest.mock import patch

from socialbot.models import Post, PostStatus, iso, utcnow
from socialbot.publisher import Publisher
from socialbot.webhooks import fire_webhook


def _setup(store):
    store.save_account("mock", {})
    store.save_account("telegram", {"bot_token": "t", "chat_id": "1"})
    return Publisher(store)


def test_publish_now_success(store):
    publisher = _setup(store)
    post = Post(text="hi", platforms=["mock"])
    result = publisher.publish_now(post)
    assert result.status == PostStatus.PUBLISHED.value
    assert result.results["mock"]["ok"] is True
    assert result.published_at


def test_publish_partial_failure(store):
    publisher = _setup(store)
    # telegram credentials are fake but present -> request fails -> partial
    post = Post(text="hi", platforms=["mock", "telegram"])
    with patch("socialbot.platforms.telegram.Telegram._call") as call:
        call.side_effect = Exception("boom")
        result = publisher.publish_now(post)
    assert result.status == PostStatus.PARTIAL.value
    assert result.results["mock"]["ok"] is True
    assert result.results["telegram"]["ok"] is False
    assert "telegram" in result.error


def test_publish_all_fail(store):
    publisher = _setup(store)
    post = Post(text="hi", platforms=["telegram"])
    with patch("socialbot.platforms.telegram.Telegram._call") as call:
        call.side_effect = Exception("no network")
        result = publisher.publish_now(post)
    assert result.status == PostStatus.FAILED.value
    assert result.error


def test_effective_text_signature(store):
    publisher = _setup(store)
    store.save_account("mock", {"signature": "— the team"})
    post = Post(text="body", platforms=["mock"])
    assert post.effective_text() == "body"                 # no override, no account sig passed
    assert post.effective_text(account_signature="— team") == "body\n\n— team"
    post.signature = "— override"
    assert post.effective_text() == "body\n\n— override"


def test_retry_failed_platforms(store):
    publisher = _setup(store)
    post = Post(text="hi", platforms=["mock", "telegram"])
    with patch("socialbot.platforms.telegram.Telegram._call") as call:
        call.side_effect = Exception("down")
        publisher.publish_now(post)
        assert post.status == PostStatus.PARTIAL.value

        # telegram "fixed": retry only touches the failed platform
        call.side_effect = None
        post = publisher.retry(post.id)
        assert post.status == PostStatus.PUBLISHED.value
        assert list(post.results.keys()) == ["telegram"]


def test_recurrence_interval_clones_next(store):
    publisher = _setup(store)
    post = Post(text="daily", platforms=["mock"], status=PostStatus.SCHEDULED.value,
                scheduled_at=iso(utcnow()), recurrence={"type": "interval", "value": 3600})
    store.save_post(post)
    publisher.publish_now(post)
    scheduled = [p for p in store.list_posts(status="scheduled")]
    assert len(scheduled) == 1
    assert scheduled[0].recurrence == {"type": "interval", "value": 3600}
    assert scheduled[0].text == "daily"


def test_process_due_publishes_when_time(store):
    publisher = _setup(store)
    store.save_post(Post(text="due now", platforms=["mock"],
                         status=PostStatus.SCHEDULED.value, scheduled_at=iso(utcnow())))
    processed = publisher.process_due()
    assert len(processed) == 1
    assert processed[0].status == PostStatus.PUBLISHED.value
    # second run: nothing pending
    assert publisher.process_due() == []


def test_cron_recurrence(store):
    publisher = _setup(store)
    post = Post(text="cron", platforms=["mock"], status=PostStatus.SCHEDULED.value,
                scheduled_at=iso(utcnow()), recurrence={"type": "cron", "value": "0 9 * * *"})
    store.save_post(post)
    clone = publisher.schedule_next_occurrence(post)
    assert clone is not None
    assert clone.scheduled_at is not None
    assert clone.status == PostStatus.SCHEDULED.value


def test_webhook_fire():
    post = Post(text="hooked", platforms=["mock"], status="published",
                published_at="2026-01-01T00:00:00+00:00")
    with patch("socialbot.webhooks.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok = fire_webhook("https://hooks.example/x", post)
    assert ok is True
    payload = mock_post.call_args.kwargs
    assert '"post.published"' in payload["data"]


def test_webhook_no_url_is_noop():
    import os
    saved = os.environ.pop("SOCIALBOT_WEBHOOK_URL", None)
    try:
        assert fire_webhook(None, Post(text="x")) is False
    finally:
        if saved:
            os.environ["SOCIALBOT_WEBHOOK_URL"] = saved
