# V0 Build Status

## Current verification

- FastAPI backend: implemented.
- Server-rendered public/admin frontend: implemented.
- Aiven/PostgreSQL-ready SQLAlchemy + Alembic layer: implemented.
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

The current working build passes 25 automated tests, a clean Alembic migration smoke test, and Python compile checks. A live HTTP smoke test confirms `/health` and the server-rendered homepage respond correctly.

## External connection blockers

The application code is complete enough for V0 review, but two external connections are required before repository/database integration can be finalized:

1. GitHub repository metadata reports collaborator push permission, but the connected GitHub integration currently returns HTTP 403 for repository-content writes. No workaround/fork is used.
2. The Aiven connector currently cannot connect to the account, so no production/shared PostgreSQL schema has been modified.

Until those connections are fixed, the tested build is preserved as a portable project archive and remains database-credential-free.
