"""Platform integration tests using a fake HTTP session (no network)."""
import pytest

from socialbot.http import HttpClient
from socialbot.models import Post
from socialbot.platforms import PlatformError, create_platform, platform_meta, platform_names

from conftest import FakeResponse, FakeSession


# ------------------------------------------------------------------ registry
def test_registry_has_all_platforms():
    names = platform_names()
    for expected in ["mock", "mastodon", "bluesky", "reddit", "twitter", "telegram",
                     "discord", "slack", "linkedin", "facebook", "instagram", "threads",
                     "pinterest"]:
        assert expected in names


def test_platform_meta_complete():
    for meta in platform_meta():
        assert meta["name"] and meta["display_name"] and meta["color"]
        assert "post" in meta["capabilities"] or meta["name"] == "base"


def test_unknown_platform_raises():
    with pytest.raises(PlatformError):
        create_platform("friendster")


def test_is_configured():
    mastodon = create_platform("mastodon", {})
    assert mastodon.is_configured() is False
    assert set(mastodon.missing_fields()) == {"instance", "access_token"}

    mastodon = create_platform("mastodon", {"instance": "https://m.social",
                                            "access_token": "tok"})
    assert mastodon.is_configured() is True


# ------------------------------------------------------------------- mastodon
def test_mastodon_publish():
    session = FakeSession(routes={
        ("POST", "/api/v1/statuses"): FakeResponse(200, {"id": "42", "url": "https://m/42"})})
    mastodon = create_platform("mastodon", {"instance": "https://m.social",
                                            "access_token": "tok"},
                               HttpClient(session=session, retries=0))
    result = mastodon.publish(Post(text="hello #bots"))
    assert result.ok and result.remote_id == "42"
    call = session.last("POST", "/statuses")
    assert call["json"]["status"] == "hello #bots"
    assert call["headers"]["Authorization"] == "Bearer tok"


def test_mastodon_search_like_follow():
    session = FakeSession(routes={
        ("GET", "/api/v2/search"): FakeResponse(200, {"statuses": [
            {"id": "1", "url": "u", "account": {"id": "9", "acct": "a"}}]}),
        ("POST", "/favourite"): FakeResponse(200, {"id": "1"}),
        ("POST", "/accounts/9/follow"): FakeResponse(200, {}),
    })
    mastodon = create_platform("mastodon", {"instance": "https://m.social",
                                            "access_token": "t"},
                               HttpClient(session=session, retries=0))
    items = mastodon.search("#python")
    assert items[0]["id"] == "1" and items[0]["author_id"] == "9"
    assert mastodon.like(items[0]) is True
    assert mastodon.follow(items[0]) is True


def test_mastodon_metrics():
    session = FakeSession(routes={
        ("GET", "/api/v1/statuses/42"): FakeResponse(
            200, {"favourites_count": 3, "reblogs_count": 1, "replies_count": 2})})
    mastodon = create_platform("mastodon", {"instance": "https://m.social", "access_token": "t"},
                               HttpClient(session=session, retries=0))
    assert mastodon.get_metrics("42") == {"likes": 3, "shares": 1, "comments": 2}


# -------------------------------------------------------------------- bluesky
def test_bluesky_publish_with_login():
    session = FakeSession(routes={
        ("POST", "createSession"): FakeResponse(
            200, {"accessJwt": "jwt", "did": "did:plc:x", "handle": "me.bsky.social"}),
        ("POST", "createRecord"): FakeResponse(
            200, {"uri": "at://did:plc:x/app.bsky.feed.post/3k", "cid": "c"}),
    })
    bluesky = create_platform("bluesky", {"identifier": "me.bsky.social", "password": "pw"},
                              HttpClient(session=session, retries=0))
    result = bluesky.publish(Post(text="hello #atproto"))
    assert result.ok
    assert result.url == "https://bsky.app/profile/me.bsky.social/post/3k"
    record = session.last("POST", "createRecord")["json"]["record"]
    assert record["text"] == "hello #atproto"
    assert record["facets"][0]["features"][0]["tag"] == "atproto"


def test_bluesky_truncates_long_text():
    session = FakeSession(routes={
        ("POST", "createSession"): FakeResponse(200, {"accessJwt": "j", "did": "d", "handle": "h"}),
        ("POST", "createRecord"): FakeResponse(200, {"uri": "at://d/x/1"})})
    bluesky = create_platform("bluesky", {"identifier": "h", "password": "p"},
                              HttpClient(session=session, retries=0))
    result = bluesky.publish(Post(text="x" * 400))
    assert len(result.ok and session.last("POST", "createRecord")["json"]["record"]["text"]) <= 300


def test_bluesky_repo_uses_did_after_login():
    """Repo must be the DID (not the handle) once a session exists (regression fix)."""
    session = FakeSession(routes={
        ("POST", "createSession"): FakeResponse(200, {"accessJwt": "j", "did": "did:plc:xyz",
                                                      "handle": "me.bsky.social"}),
        ("POST", "createRecord"): FakeResponse(200, {"uri": "at://did:plc:xyz/x/1"}),
    })
    bluesky = create_platform("bluesky", {"identifier": "me.bsky.social", "password": "p"},
                              HttpClient(session=session, retries=0))
    bluesky.like({"id": "at://did:plc:xyz/x/1", "cid": "c1"})
    record = session.last("POST", "createRecord")
    assert record["json"]["repo"] == "did:plc:xyz"


def test_slack_media_blocks():
    session = FakeSession(default=FakeResponse(200, text="ok"))
    slack = create_platform("slack", {"webhook_url": "https://hooks.slack.com/x"},
                            HttpClient(session=session, retries=0))
    result = slack.publish(Post(text="check this", media=["https://img.example.com/a.png"]))
    assert result.ok
    payload = session.last("POST", "hooks.slack.com")["json"]
    assert payload["blocks"][0] == {"type": "image", "image_url": "https://img.example.com/a.png",
                                    "alt_text": "attachment"}


# ---------------------------------------------------------------------- reddit
def test_reddit_auth_and_submit():
    session = FakeSession(routes={
        ("POST", "access_token"): FakeResponse(200, {"access_token": "T"}),
        ("POST", "/api/submit"): FakeResponse(
            200, {"json": {"errors": [], "data": {"id": "abc", "url": "https://redd.it/abc"}}}),
    })
    reddit = create_platform("reddit", {"client_id": "ci", "client_secret": "cs",
                                        "username": "u", "password": "p",
                                        "subreddit": "test"},
                             HttpClient(session=session, retries=0))
    result = reddit.publish(Post(text="My title\n\nBody text here"))
    assert result.ok and result.remote_id == "abc"
    submit = session.last("POST", "/submit")
    assert submit["data"]["title"] == "My title"
    assert submit["data"]["kind"] == "self"
    assert submit["data"]["sr"] == "test"
    assert submit["headers"]["Authorization"] == "bearer T"


def test_reddit_requires_subreddit():
    reddit = create_platform("reddit", {"client_id": "ci", "client_secret": "cs",
                                        "username": "u", "password": "p"})
    with pytest.raises(PlatformError):
        reddit.publish(Post(text="t"))


# ---------------------------------------------------------------------- twitter
def test_twitter_publish():
    session = FakeSession(routes={
        ("POST", "/2/tweets"): FakeResponse(200, {"data": {"id": "999"}})})
    twitter = create_platform("twitter", {"access_token": "tok"},
                              HttpClient(session=session, retries=0))
    result = twitter.publish(Post(text="hello X"))
    assert result.ok and result.remote_id == "999"
    assert session.last("POST", "/tweets")["json"] == {"text": "hello X"}


# --------------------------------------------------------------------- telegram
def test_telegram_publish_text():
    session = FakeSession(routes={
        ("POST", "sendMessage"): FakeResponse(
            200, {"ok": True, "result": {"message_id": 5, "chat": {"username": "news"}}})})
    telegram = create_platform("telegram", {"bot_token": "b", "chat_id": "1"},
                               HttpClient(session=session, retries=0))
    result = telegram.publish(Post(text="hello"))
    assert result.ok and result.remote_id == "5"
    assert result.url == "https://t.me/news/5"


def test_telegram_api_error_wrapped():
    session = FakeSession(default=FakeResponse(400, {"ok": False, "description": "chat not found"}))
    telegram = create_platform("telegram", {"bot_token": "b", "chat_id": "1"},
                               HttpClient(session=session, retries=0))
    with pytest.raises(PlatformError, match="chat not found"):
        telegram.publish(Post(text="hello"))


def test_telegram_local_file_upload_keeps_fields(tmp_path):
    """Local file uploads must still send chat_id + caption (regression fix)."""
    photo = tmp_path / "pic.jpg"
    photo.write_bytes(b"jpeg-bytes")
    session = FakeSession(routes={
        ("POST", "sendPhoto"): FakeResponse(
            200, {"ok": True, "result": {"message_id": 7, "chat": {"username": "news"}}})})
    telegram = create_platform("telegram", {"bot_token": "b", "chat_id": "1"},
                               HttpClient(session=session, retries=0))
    result = telegram.publish(Post(text="caption", media=[str(photo)]))
    assert result.ok and result.remote_id == "7"
    call = session.last("POST", "sendPhoto")
    assert call["data"]["chat_id"] == "1"
    assert call["data"]["caption"] == "caption"
    assert call["files"] is not None


# ------------------------------------------------------------------ linkedin
def test_linkedin_publish():
    session = FakeSession(routes={
        ("POST", "/ugcPosts"): FakeResponse(200, {"id": "urn:li:share:1"})})
    linkedin = create_platform("linkedin", {"access_token": "t", "member_id": "abc"},
                               HttpClient(session=session, retries=0))
    result = linkedin.publish(Post(text="professional"))
    assert result.ok and result.remote_id == "urn:li:share:1"
    body = session.last("POST", "/ugcPosts")["json"]
    assert body["author"] == "urn:li:person:abc"


# -------------------------------------------------------------------- threads
def test_threads_two_step_publish():
    session = FakeSession(routes={
        ("POST", "threads_publish"): FakeResponse(200, {"id": "t1"}),
        ("POST", "/threads"): FakeResponse(200, {"id": "c1"})})
    threads = create_platform("threads", {"user_id": "u", "access_token": "t"},
                              HttpClient(session=session, retries=0))
    result = threads.publish(Post(text="thread it"))
    assert result.ok and result.remote_id == "t1"
    assert session.last("POST", "threads_publish")["params"] == {"creation_id": "c1"}


# ------------------------------------------------------------------ instagram
def test_instagram_requires_image():
    instagram = create_platform("instagram", {"user_id": "u", "access_token": "t"})
    with pytest.raises(PlatformError, match="image URL"):
        instagram.publish(Post(text="no media"))


# -------------------------------------------------------------- mock platform
def test_mock_platform_full_cycle():
    mock = create_platform("mock", {})
    result = mock.publish(Post(text="demo"))
    assert result.ok
    metrics = mock.get_metrics(result.remote_id)
    assert set(metrics) == {"likes", "shares", "comments", "impressions"}
    assert mock.like({"id": "x"}) is True
    assert len(mock.search("python")) > 0
