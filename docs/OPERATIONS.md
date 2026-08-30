# V0 Operations

## Initial setup with the existing Supabase PostgreSQL database

1. Obtain the existing Supabase PostgreSQL connection string from the authorized environment.
2. Configure `DATABASE_URL`; the app will normalize plain PostgreSQL URLs to the SQLAlchemy psycopg driver.
3. Set a strong `SESSION_SECRET` and initial admin credentials.
4. Run `alembic upgrade head`.
5. Start the FastAPI application.
6. Confirm `/health` returns `{"status":"ok"}`.
7. Confirm `/ready` returns `{"status":"ok","database":"up"}` once the database is reachable.
8. Log in to `/admin/login`.
9. Create the active disaster and affected locations.

No additional database service is required.

## Disaster activation checklist

1. Create/confirm event code and start date.
2. Add affected districts, municipalities, settlements, projects, roads, rivers, and common spelling variants as separate location lines.
3. Open Discovery Bot and inspect generated Facebook queries. Confirm new direct reports show an affected-area match or review the exception manually.
4. Run a limited bot pass.
5. Open important generated Google searches manually.
6. Add high-value public Facebook group/page URLs manually when discovered.
7. Triage To Review sources, then use one-click AI Prefill only from Relevant.
8. Resolve the Possible Duplicates queue using the linked published case.
9. Review every extracted field before saving or publication.
10. Prefer attaching source links to an existing person only after identity is confirmed.
11. Publish only the information needed for identification/search.
12. Keep reporter private contact data out of public fields.

## Recommended shift procedure

1. Record starting queue counts from the Admin Dashboard.
2. Run bounded discovery and review provider warnings.
3. Clear urgent To Review items and move valid reports to Relevant.
4. Use AI Prefill from Relevant and verify all people named in each source.
5. Clear Possible Duplicates and Pending Submissions.
6. Review unpublished and resolved cases.
7. Produce an authorized event export and record ending queue counts.

## Export workflow

Only an authenticated admin can export. Use the event-specific XLSX for authority handoff because it separates master people and source URLs into different sheets.

Every export generates an audit-log entry. The export may include admin-only residential/private contact fields and must therefore be handled as restricted operational data, not published as a public download.

## Backup

For the review-stage V0, rely on the existing Supabase backup policy plus a periodic admin export for operational portability. Before public production, define tested database restore and media/object-storage backup procedures.

## Current filesystem storage caveat

Photos are stored on the application filesystem in V0. Raw upload storage is not publicly mounted: pending/rejected photos are admin-only and published case photos are served through a case authorization check. Filesystem storage is acceptable for local/review use but must be replaced by persistent object storage before horizontally scaled or ephemeral production deployment.

## Security before live use

V0 is intentionally not declared production-ready. Before exposing it publicly, add or validate:

- `COOKIE_SECURE=true` with HTTPS-only deployment;
- CSRF protection;
- public form rate limiting;
- abuse/spam protections;
- image malware/content validation as appropriate;
- admin MFA/role separation if required;
- privacy retention/deletion policy;
- monitoring and alerting;
- security testing;
- persistent media storage.
