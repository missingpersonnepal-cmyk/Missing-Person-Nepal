# Nepal Disaster Missing Persons Hub

V0 is a deliberately lean disaster-time missing-person aggregation system. It collects public reports and direct submissions, keeps original source links, warns admins about likely duplicate people, publishes a searchable public list, and allows administrators to export consolidated data.

The project is designed to use an existing **Supabase PostgreSQL** database through `DATABASE_URL`. It does not require a paid Meta, search, AI, SMS, hosting, or authentication API for development.

## V0 mission

**Find / receive → review → deduplicate → centralize → publish → export.**

The system is not a police complaint system and does not make an official determination that a person is missing. Social-media links prove where a report came from, not that the report is officially verified.

## What V0 includes

- Disaster/event setup with affected-location terms.
- Public missing-person report form.
- Public search and case detail pages.
- Private reporter/contact fields separated from public fields.
- One master missing-person record with multiple evidence/source links.
- Duplicate suggestions using name, location, age, and phone similarity.
- Human-controlled approval, duplicate attachment, and duplicate master-case consolidation.
- Public Facebook/web discovery bot based on zero-cost public search indexing and disaster-time/location targeting.
- Manual Facebook/social URL intake as a permanent fallback.
- Admin-only CSV and XLSX export.
- Social share-card generation.
- Audit trail for key admin actions.
- Public JSON API for future integrations.
- Alembic database migration.
- Automated tests and GitHub Actions CI.

## What V0 intentionally does not include

- Closed/private Facebook group access.
- Facebook login/session automation.
- Paid Meta API dependency.
- Automated official verification.
- Found/hospital/deceased workflows.
- Police, NDRRMA, BIPAD, or Red Cross integration.
- Facial recognition.
- Public bulk export.
- SMS/mobile apps.
- Production-grade social publishing.

## Architecture

```text
Public web/social indexes ──┐
Manual public post URL ─────┤
Direct public report ───────┤
                            ▼
                      Pending report
                            │
                      Admin review
                            │
                    Duplicate warning
                      ↙           ↘
              Attach source       New master person
                      \           /
                       Master record
                            │
                  ┌─────────┼──────────┐
                  ▼         ▼          ▼
             Public search  Sources   Admin export
```

A social post is a **source**, not the person record itself. One source post may also mention multiple people, so the database allows the same source URL to be attached to different master people while preventing the same URL from being attached twice to the same person.

## Stack

- Python 3.12+
- FastAPI
- SQLAlchemy 2
- PostgreSQL / Supabase PostgreSQL
- Jinja2 + plain HTML/CSS
- Alembic
- openpyxl
- Pillow
- httpx + BeautifulSoup for public search discovery
- Pytest

The frontend is intentionally basic and server-rendered. V0 spends engineering time on information capture, deduplication, source preservation, and review rather than UI decoration.

## Configuration

Copy `.env.example` to `.env` and set values. The application reads environment variables directly; use your normal environment loader/shell in development.

The important setting is:

```bash
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/defaultdb?sslmode=require
```

For the existing Supabase database, use the project connection string in `DATABASE_URL` and let the app normalize plain `postgresql://` URLs to SQLAlchemy's `postgresql+psycopg://` driver. Never commit the URI or credentials.

Other important settings:

```bash
SESSION_SECRET=<long random value>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong initial password>
AUTO_CREATE_TABLES=false
```

Use `AUTO_CREATE_TABLES=true` only for quick local development. With Supabase/PostgreSQL, prefer Alembic migrations.

## Database setup

Run the migration against the configured database:

```bash
alembic upgrade head
```

All database tables use the `mp_` prefix so V0 can safely share the existing main PostgreSQL database without colliding with unrelated project tables.

Current core tables:

- `mp_disasters`
- `mp_missing_people`
- `mp_sources`
- `mp_submissions`
- `mp_discovery_candidates`
- `mp_admins`
- `mp_audit_logs`

## Run locally

Install the project:

```bash
python -m pip install -e ".[dev]"
```

Start the server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

The first admin account is created only when `ADMIN_PASSWORD` is set and no account with `ADMIN_USERNAME` exists.

## Basic workflow

1. Admin logs in.
2. Admin creates an event such as `Rasuwa Flood` and lists affected locations one per line.
3. Admin opens **Discovery Bot**.
4. The system generates Facebook/web searches using affected locations and Nepali/English missing-person keywords.
5. Admin can run the limited zero-cost public-search bot or open the generated Google searches manually.
6. Candidate public posts are reviewed by an admin; direct reports are flagged when the last-seen location does not match configured affected-area terms.
7. Admin extracts the visible person details into a pending submission.
8. The review page shows likely existing people.
9. Admin either attaches the new source to an existing person or creates a new master record.
10. Admin publishes the master record.
11. The public can search it and submit corrections/additional information.
12. Admin can export the event to XLSX/CSV.

## Facebook/public-social bot

V0's bot is intentionally narrow:

- searches only public web indexes;
- targets `site:facebook.com` plus affected location and missing-person terms;
- never logs in to Facebook;
- never attempts closed/private group access;
- never bypasses access controls;
- stores only candidate public URLs/titles/snippets;
- requires admin review before a case is created or published.

The bot uses DuckDuckGo's public HTML search as its zero-cost automated provider. The admin interface also generates Google search links with an event-date window. Search indexing can miss recent Facebook posts, so **manual public-post URL intake is a first-class feature, not an emergency workaround**.

The same discovery engine can be run from the command line for later scheduling:

```bash
python -m app.bot_runner --event RF --platform facebook
```

See `docs/BOT.md` for the bot contract and limitations.

## Duplicate handling

V0 calculates suggestions from:

- normalized name similarity;
- last-seen location similarity;
- exact/near age;
- normalized phone match.

The software never automatically merges people. An admin decides whether a new report is the same person.

Current V0 thresholds:

- under 45: not surfaced;
- 45–69: possible;
- 70+: strong review candidate.

A future version can add Nepali/English transliteration dictionaries, poster perceptual hashes, and stronger entity matching without changing the person/source model.

## Public API

Read-only public endpoints:

```text
GET /api/v1/events
GET /api/v1/people
GET /api/v1/people/{case_number}
```

Private fields such as residential address and reporter phone are never serialized by these endpoints.

## Admin-only exports

Authenticated admins can export:

```text
/admin/export/xlsx?disaster_id=<id>
/admin/export/csv?disaster_id=<id>
```

XLSX contains:

- Missing People (including admin-only address/private contact fields)
- Sources
- Metadata

Because exports can contain restricted information, they remain admin-only and every export is written to the audit log.

The public site has no bulk-export route.

## Tests

Run:

```bash
pytest
```

The suite covers:

- phone and URL normalization;
- duplicate suggestions;
- disaster/social query generation;
- public report → admin review → publication → search → export;
- public export denial;
- source URL duplication rules;
- public API privacy boundaries;
- duplicate master-case consolidation;
- affected-area matching;
- image validation/metadata stripping;
- discovery provider and candidate persistence.

## Production review gate

Before any public deployment, review and harden at least:

- HTTPS-only secure session cookies;
- CSRF protection;
- public rate limiting / CAPTCHA where required;
- object storage for uploaded photos;
- backup and disaster recovery;
- privacy/retention policy;
- admin role separation;
- security/penetration testing;
- platform terms for any expanded social automation;
- monitoring/logging;
- legal basis for public contact/photo publication.

V0 is an operational proof of concept, not yet a national production service.

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/BOT.md`
- `docs/OPERATIONS.md`
- `docs/SERVICE_CATALOG.md`
- `docs/USER_MANUAL.md`
- `docs/SEARCH_AND_DISCOVERY.md`
- `docs/ADMIN_AND_HANDOVER.md`
- `docs/TROUBLESHOOTING.md`
