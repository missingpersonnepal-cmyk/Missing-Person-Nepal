from __future__ import annotations

from ..models import MissingPerson, Submission


def _blank(value: object) -> bool:
    if value is None:
        return True

    if isinstance(value, str):
        stripped = value.strip()

        return (
            not stripped
            or stripped.casefold() == "unknown"
        )

    return False


def apply_submission_to_master(
    person: MissingPerson,
    submission: Submission,
) -> list[str]:
    """Fill blank Master fields from an approved submission.

    Existing admin-confirmed Master values are never overwritten.
    """
    mappings = [
        ("name_ne", "name_ne"),
        ("age", "age"),
        ("gender", "gender"),
        ("photo_path", "photo_path"),
        (
            "residential_address_private",
            "residential_address_private",
        ),
        ("last_seen_date", "last_seen_date"),
        ("last_seen_time", "last_seen_time"),
        ("last_seen_location", "last_seen_location"),
        ("clothing", "clothing"),
        (
            "identification_details",
            "identification_details",
        ),
        (
            "public_contact_number",
            "public_contact_number",
        ),
        (
            "private_contact_number",
            "reporter_phone_private",
        ),
    ]

    updated: list[str] = []

    for target_field, source_field in mappings:
        current = getattr(person, target_field)
        incoming = getattr(submission, source_field)

        if _blank(current) and not _blank(incoming):
            setattr(
                person,
                target_field,
                incoming,
            )

            updated.append(target_field)

    return updated
