from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str | None = None


class SmsProvider(Protocol):
    configured: bool

    def send(self, to: str, message: str) -> SendResult:
        ...


class EmailProvider(Protocol):
    configured: bool

    def send(self, to: str, subject: str, body: str) -> SendResult:
        ...
