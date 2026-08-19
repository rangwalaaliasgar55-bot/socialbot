"""Quickstart example: drive SocialBot from Python.

Run:  python examples/quickstart.py
"""
import os
import tempfile
from datetime import timedelta

os.environ.setdefault("SOCIALBOT_DB", os.path.join(tempfile.mkdtemp(), "quickstart.db"))

from socialbot.models import Post, PostStatus, iso, utcnow  # noqa: E402
from socialbot.publisher import Publisher  # noqa: E402
from socialbot.storage import Store  # noqa: E402

store = Store()
store.save_account("mock", {"username": "demo"}, label="Demo")

# 1. post immediately
publisher = Publisher(store)
post = publisher.publish_now(Post(text="Hello from the Python API! 🐍", platforms=["mock"]))
print("published:", post.status, post.results)

# 2. schedule for later
later = Post(text="Scheduled from a script", platforms=["mock"],
             status=PostStatus.SCHEDULED.value,
             scheduled_at=iso(utcnow() + timedelta(minutes=5)), tag="scripted")
store.save_post(later)
print("scheduled:", later.id, "->", later.scheduled_at)

# 3. process everything that is due (normally done by `socialbot run`)
for processed in publisher.process_due():
    print("processed:", processed.id, processed.status)
