"""Platform integration tests using a fake HTTP session (no network)."""
import pytest

from socialbot.http import HttpClient
from socialbot.models import Post
from socialbot.platforms import PlatformError, create_platform, platform_meta, platform_names

from conftest import FakeResponse, FakeSession


# ------------------------------------------------------------------ registry
def test_registry_has_all_platforms():
    names = platform_names()
    for expected in ["mock", "telegram", "twitter", "linkedin", "youtube"]:
        assert expected in names


def test_platform_meta_complete():
    for meta in platform_meta():
        assert meta["name"] and meta["display_name"] and meta["color"]
        assert "post" in meta["capabilities"] or meta["name"] == "base"


def test_unknown_platform_raises():
    with pytest.raises(PlatformError):
        create_platform("friendster")


def test_is_configured():
    telegram = create_platform("telegram", {})
    assert telegram.is_configured() is False
    assert set(telegram.missing_fields()) == {"bot_token", "chat_id"}

    telegram = create_platform("telegram", {"bot_token": "b", "chat_id": "1"})
    assert telegram.is_configured() is True


# -------------------------------------------------------------------- twitter
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


# -------------------------------------------------------------------- youtube
def test_youtube_requires_oauth():
    youtube = create_platform("youtube", {})
    assert youtube.is_configured() is False
    assert "access_token" in youtube.missing_fields()


# -------------------------------------------------------------- mock platform
def test_mock_platform_full_cycle():
    mock = create_platform("mock", {})
    result = mock.publish(Post(text="demo"))
    assert result.ok
    metrics = mock.get_metrics(result.remote_id)
    assert set(metrics) == {"likes", "shares", "comments", "impressions"}
    assert mock.like({"id": "x"}) is True
    assert len(mock.search("python")) > 0