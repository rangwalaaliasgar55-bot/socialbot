"""All built-in platform integrations (importing registers them)."""
from .base import (  # noqa: F401
    Platform, PlatformError, create_platform, get_platform_class, platform_meta,
    platform_names, register,
)

# Import modules for their registration side effects.
from . import mock  # noqa: F401
from . import telegram  # noqa: F401
from . import discord  # noqa: F401
from . import slack  # noqa: F401
from . import mastodon  # noqa: F401
from . import bluesky  # noqa: F401
from . import reddit  # noqa: F401
from . import twitter  # noqa: F401
from . import linkedin  # noqa: F401
from . import facebook  # noqa: F401
from . import instagram  # noqa: F401
from . import threads  # noqa: F401
from . import pinterest  # noqa: F401
from . import youtube  # noqa: F401
from . import tiktok  # noqa: F401
from . import nostr  # noqa: F401
from . import lemmy  # noqa: F401

SUPPORTED = platform_names()
