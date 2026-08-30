# V0 Architecture

## Design goals

V0 optimizes for speed, zero paid development dependencies, a small code surface, clear provenance, and future interoperability.

The application is a single FastAPI service with a server-rendered frontend. This is intentional. Splitting the frontend and backend into separate deployables would add deployment and authentication complexity without improving the V0 mission. Route modules are separated into `app/routes/public.py` and `app/routes/admin.py`, while public JSON integration endpoints live in `app/api.py`.

## Logical components

### Public interface

- Search published active people.
- View one master case.
- Submit a missing-person report.
- Submit additional information or a source URL.

### Admin interface

- Create disaster events and affected-location terms.
- Review public/direct submissions.
- Review discovery candidates.
- Add external source URLs.
- See duplicate suggestions.
- Create or edit master people.
- Publish/unpublish/archive cases.
- Export CSV/XLSX (admin-only, with restricted fields clearly labelled).
- Generate social share cards.

### Discovery service

`app/services/discovery.py` generates location/keyword/site-filter queries and optionally sends a small number through a zero-cost public search provider.

The discovery service is an adapter. If a future approved Meta/search API becomes available, a new provider can be added without changing the case database. The same service powers both the admin button and `python -m app.bot_runner`, so later scheduling does not require rewriting the bot.

### Duplicate service

`app/services/duplicates.py` is deterministic and explainable. It intentionally recommends rather than decides.

### Persistence

SQLAlchemy uses `DATABASE_URL`. PostgreSQL is the intended shared database. SQLite remains useful for local tests and emergency development only.

Tables are prefixed `mp_` so the project can share an existing Supabase PostgreSQL database safely.

## Trust boundaries

### Public data

Can include name, photo, age, gender, last-seen information, identification details, chosen public contact number, and approved public source links.

### Restricted data

Reporter phone/name, exact residential address, pending-upload media, and internal admin/audit information stay server-side and are not exposed by the public API. Raw uploads are not mounted as a public directory; a public case photo is served only through a route that verifies the case is published and not archived.

### Social data

A public source URL records provenance. It does not elevate a report to official truth. Publication still requires admin review.

## Scaling path

The V0 data model supports scaling without replacing the core concepts:

1. PostgreSQL remains the system of record.
2. Uploaded files can move from local filesystem to object storage.
3. Discovery can gain API-backed providers.
4. Duplicate matching can gain transliteration/entity/image signals.
5. Admin roles can split into reviewer/authority/admin.
6. REST API can serve a richer frontend or government integrations.
7. Background discovery can move to a worker queue if workload demands it.

No V0 feature requires those later components today.
