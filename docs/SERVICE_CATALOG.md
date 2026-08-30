# Service Catalog

## Public services

- Search published missing-person cases by name and location.
- View a case, public contact information, image, and reviewed details.
- Submit a new missing-person report.
- Submit additional information for administrator review.
- Read the privacy-limited JSON API at `/api/v1`.

## Administrator services

- Configure disaster events and affected locations.
- Discover public reports through bounded search providers.
- Track important public source accounts and custom search tags.
- Add missed public post URLs manually.
- Triage source candidates into operational queues.
- Extract all explicitly named people with one-click AI Prefill.
- Detect exact published-name matches and isolate duplicate sources.
- Create, edit, publish, archive, merge, and resolve master cases.
- Attach multiple evidence sources to one person.
- Approve, attach, or reject pending submissions.
- Export event data to CSV/XLSX with audit logging.
- Generate share-card content for manual distribution.

## System services

- `/health`: process liveness.
- `/ready`: database connectivity readiness.
- SQLAlchemy persistence through `DATABASE_URL`.
- Alembic schema migrations.
- Audit records for sensitive administrative actions.
- Public-field serialization that excludes private reporter data.

## Explicit exclusions

The system does not provide official verification, police complaint registration, facial recognition, private social account access, automated social posting, public bulk export, or automatic identity merging.

