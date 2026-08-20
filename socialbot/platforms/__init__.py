"""All built-in platform integrations (importing registers them)."""
from .base import (  # noqa: F401
    Platform, PlatformError, create_platform, get_platform_class, platform_meta,
    platform_names, register,
)

# Import modules for their registration side effects.
from . import mock  # noqa: F401
from . import telegram  # noqa: F401
from . import twitter  # noqa: F401
from . import linkedin  # noqa: F401
from . import youtube  # noqa: F401

SUPPORTED = platform_names()
