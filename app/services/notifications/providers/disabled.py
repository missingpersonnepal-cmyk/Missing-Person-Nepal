from __future__ import annotations

from .base import SendResult


class DisabledSmsProvider:
    configured = False

    def send(self, to: str, message: str) -> SendResult:
        raise RuntimeError("SMS provider is disabled")


class DisabledEmailProvider:
    configured = False

    def send(self, to: str, subject: str, body: str) -> SendResult:
        raise RuntimeError("Email provider is disabled")
