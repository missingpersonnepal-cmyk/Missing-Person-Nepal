from __future__ import annotations

from ...config import settings
from .providers.base import EmailProvider
from .providers.disabled import DisabledEmailProvider


def get_email_provider() -> EmailProvider:
    if settings.email_provider == "disabled":
        return DisabledEmailProvider()
    return DisabledEmailProvider()
