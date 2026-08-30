from __future__ import annotations

from ...config import settings
from .providers.base import SmsProvider
from .providers.disabled import DisabledSmsProvider


def get_sms_provider() -> SmsProvider:
    if settings.sms_provider == "disabled":
        return DisabledSmsProvider()
    return DisabledSmsProvider()
