# V0 Build Status

## Current verification

- FastAPI backend: implemented.
- Server-rendered public/admin frontend: implemented.
- Supabase PostgreSQL-ready SQLAlchemy/psycopg + Alembic layer: implemented.
- Public/direct missing-person intake: implemented.
- Admin review and publication: implemented.
- Multi-source master person records: implemented.
- Duplicate suggestions and human-controlled master-case consolidation: implemented.
- Public Facebook/social discovery adapter: implemented using bounded public web search plus manual URL fallback.
- One social-list post can create several person submissions while preserving the same source URL: implemented.
- Affected-area match warning: implemented.
- Admin-only CSV/XLSX export: implemented.
- Public JSON API privacy boundary: implemented.
- Raw pending uploads are not publicly mounted; only published case photos are publicly served: implemented.
- Social share-card generation: implemented.
- Audit logging: implemented.

## Automated verification

The project includes automated workflow, privacy, discovery, duplicate, database-readiness, export, image, and end-to-end tests. Run `pytest` for the authoritative current count. Health endpoints are `/health` and `/ready`.

## Current integration status

The repository is connected to GitHub and application changes are pushed through the normal Git workflow. Shared persistence uses Supabase PostgreSQL through server-side `DATABASE_URL`. Secrets remain environment-only. Automated tests use isolated SQLite databases and do not mutate Supabase.
