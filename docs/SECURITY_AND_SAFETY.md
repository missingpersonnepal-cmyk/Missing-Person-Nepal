# Security and Data-Safety Operations

## Core rule

This system supports human review. It does not establish a person's identity, status, location, age, gender, relationship, or other personal attribute on its own.

AI prefill and discovery results are drafts from public written evidence. A reviewer must check the source before publication.

## Data classification

Public case data may include only approved case details, approved photos, a public contact method, and an approved source link.

Restricted data includes reporter details, residential address, pending uploads, audit history, notification destinations, and unreviewed submissions. Do not copy restricted data into public fields.

## Review before publication

1. Open the candidate or submission and inspect its source.
2. Confirm that each name is explicitly reported as missing or out of contact.
3. Confirm public phone numbers, photos, date, and location from evidence.
4. Keep uncertain details blank or mark the location as approximate.
5. Check possible duplicates. Never merge cases based on a name alone.
6. Record confidence and approval notes, then publish only when appropriate.

## Photo handling

- Upload only JPG, PNG, or WEBP files up to 10 MB.
- Upload processing strips metadata by re-encoding the image.
- Confirm consent and verification before using a photo publicly.
- Do not use visual appearance to infer personal attributes.

## Access control

- Use individual administrator accounts; never share the super-admin password.
- `read_only` users must not modify records.
- Restrict publishing, archiving, merging, user management, and infrastructure actions to `admin` or `super_admin` roles.
- Review audit logs during every operational handover.

## Secrets and deployment

- Keep `DATABASE_URL`, session secrets, OpenAI, Serper, and geo keys only in Render environment variables or a local ignored `.env` file.
- Rotate any key that was pasted into a chat, ticket, browser, or source file.
- Keep `COOKIE_SECURE=true`, `APP_ENV=production`, and `AUTO_CREATE_TABLES=false` in production.
- Run `alembic upgrade head` as part of every deployment.

## Backups and retention

- Take and test a PostgreSQL backup before schema changes and at least daily during active incidents.
- Export case and audit data for handover using the admin export workflow; store exports in an approved restricted location.
- Review pending submissions, source images, and reporter data against the authority's retention policy. Do not delete records needed for an active investigation.

## Free-hosting constraints

Render free web services can sleep and do not provide a durable background worker or persistent local upload disk. The database remains the system of record. For incident-critical production use, arrange an approved durable object store, verified backup process, and an authority-controlled notification provider.
