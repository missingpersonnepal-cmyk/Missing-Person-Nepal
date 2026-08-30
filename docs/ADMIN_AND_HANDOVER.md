# Administration and Handover Guide

## Configuration ownership

Production requires securely managed values for `DATABASE_URL`, `SESSION_SECRET`, admin credentials, cookie settings, search provider keys, and optional OpenAI configuration. Never place secrets in source control, screenshots, tickets, or handover documents.

## Deployment checklist

1. Confirm the intended Supabase project and connection mode.
2. Back up or confirm the provider backup policy.
3. Review pending Alembic migrations; apply only approved migrations.
4. Set `AUTO_CREATE_TABLES=false` for shared PostgreSQL.
5. Set a strong `SESSION_SECRET`, HTTPS, and secure cookies.
6. Start the service and verify `/health` and `/ready`.
7. Verify admin login, public search, a test-database workflow, and export permissions.
8. Confirm persistent media storage; local filesystem uploads are not suitable for ephemeral multi-instance hosting.

## Supabase rules

- The application connects through SQLAlchemy/psycopg; it does not expose credentials to the browser.
- Use migrations for schema changes and review generated SQL before application.
- Do not reset, truncate, or experiment against production-like data.
- Tables use the `mp_` prefix.
- If tables are exposed through Supabase Data API, review grants and enable suitable RLS. The current application does not require browser-side Data API access.

## Shift handover

Record the active event, queue counts, discovery run time, provider failures, urgent unreviewed sources, unresolved duplicate sources, pending submissions, unpublished cases, and exports delivered. Do not include secrets or unnecessary private personal data.

## Backup and restore

Use the Supabase backup policy for database recovery and a separate persistent-media backup for uploaded images. Test restoration in an isolated environment. Event exports support operational portability but are not a complete database/media backup.

## New administrator onboarding

Provide this order: `SERVICE_CATALOG.md`, `USER_MANUAL.md`, `SEARCH_AND_DISCOVERY.md`, `OPERATIONS.md`, then `ARCHITECTURE.md`. Conduct a supervised exercise in a test database covering triage, AI Prefill, duplicate attachment, publication, resolution, and export.

