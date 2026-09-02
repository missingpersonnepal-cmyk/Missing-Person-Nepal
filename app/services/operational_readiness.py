from __future__ import annotations

from dataclasses import dataclass
import os

from sqlalchemy import text

from ..config import settings
from ..database import SessionLocal
from .notifications.email import get_email_provider
from .notifications.sms import get_sms_provider


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


def _database_check() -> ReadinessCheck:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return ReadinessCheck("Database", "ready", "PostgreSQL connection verified.")
    except Exception:
        return ReadinessCheck("Database", "blocked", "Database connection could not be verified.")


def operational_readiness() -> list[ReadinessCheck]:
    """Return non-secret deployment checks for the restricted operations page."""
    storage_configured = all(
        (
            settings.supabase_url,
            settings.supabase_service_role_key,
            settings.supabase_storage_bucket,
        )
    )
    sms_configured = get_sms_provider().configured
    email_configured = get_email_provider().configured
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    serper_configured = bool(os.getenv("SERPER_API_KEY"))
    return [
        _database_check(),
        ReadinessCheck(
            "Media storage",
            "follow_up",
            (
                "Supabase Storage credentials are present, but this release still serves media from the local "
                "application filesystem. Complete the storage migration before relying on an ephemeral or scaled service."
                if storage_configured
                else "Photos are stored on the local application filesystem. Configure and migrate to private object storage before public production."
            ),
        ),
        ReadinessCheck(
            "SMS authority delivery",
            "ready" if sms_configured else "follow_up",
            "An SMS provider is configured; perform an authorized live delivery test."
            if sms_configured
            else "No active SMS adapter is configured. Alerts remain in the audited outbox until an approved authority SMS provider is integrated.",
        ),
        ReadinessCheck(
            "Email authority delivery",
            "ready" if email_configured else "follow_up",
            "An email provider is configured; perform an authorized live delivery test."
            if email_configured
            else "No active email adapter is configured. Alerts remain in the audited outbox until an approved authority email provider is integrated.",
        ),
        ReadinessCheck(
            "AI prefill",
            "ready" if openai_configured else "follow_up",
            "API key is available; reviewers must still verify every extracted field before publication."
            if openai_configured
            else "No OpenAI key is configured, so only the manual extraction fallback is available.",
        ),
        ReadinessCheck(
            "Wide discovery search",
            "ready" if serper_configured else "follow_up",
            "Search provider key is available. Use bounded runs and review sources before publication."
            if serper_configured
            else "No Serper key is configured, so the generated manual Google search plan remains the fallback.",
        ),
    ]
