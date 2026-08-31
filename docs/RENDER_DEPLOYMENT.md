# Render Deployment Guide

This repository is prepared for deployment on Render as a single Docker-based web service named `Missing-Person-Nepal`.

Account note:
- Use the Render account `missingpersonnepal@gmail.com` when connecting the repository and filling environment variables.

## Prerequisites

1. Push the repository to GitHub.
2. Connect the GitHub account that owns or can access the repo to Render.
3. Prepare a Supabase PostgreSQL database connection string.
4. Generate a long random `SESSION_SECRET`.

## Connecting the repository

1. Sign in to Render.
2. Connect the GitHub account that has access to the repository.
3. Choose the repository `Missing-Person-Nepal`.
4. Use the `main` branch.
5. Keep the root directory blank because the Dockerfile is at the repository root.

## Blueprint deployment

This repo includes `render.yaml` at the root. Use Render Blueprint deployment and let Render read the file from `main`.

If you prefer manual setup, create a Web Service with:
- Runtime: Docker
- Branch: `main`
- Region: Singapore
- Root directory: blank
- Health check path: `/health`

## Required environment variables

Set these in Render as secret environment variables unless the Blueprint already sets a fixed value:

- `DATABASE_URL`
- `SESSION_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `PUBLIC_BASE_URL`

## Recommended production values

- `APP_ENV=production`
- `AUTO_CREATE_TABLES=false`
- `COOKIE_SECURE=true`
- `UPLOAD_DIR=uploads`
- `EXPORT_DIR=exports`
- `DISCOVERY_MAX_QUERIES_PER_RUN=12`
- `DISCOVERY_RESULTS_PER_QUERY=8`
- `DISCOVERY_REQUEST_DELAY_SECONDS=1.0`
- `DISCOVERY_TIMEOUT_SECONDS=15`
- `SMS_PROVIDER=disabled`
- `EMAIL_PROVIDER=disabled`

## Generating `SESSION_SECRET`

Use a long random value. Example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Supabase PostgreSQL

Use the Supabase PostgreSQL connection string for `DATABASE_URL`.

The app supports standard `postgresql://` and `postgres://` URLs and normalizes them to `postgresql+psycopg://`.

## Database initialization and migrations

The project uses Alembic migrations. Run them once against the target database before or after the first deploy, depending on how you prefer to prepare the schema:

```bash
alembic upgrade head
```

If the database already exists outside Alembic, make sure the schema matches the current models before setting `AUTO_CREATE_TABLES=false`.

## Health endpoint

Render should check:

```text
GET /health
```

This is a lightweight liveness check and does not touch the database.

## First deployment

1. Commit `render.yaml` and push it to `main`.
2. Open the Render Blueprint flow.
3. Review the service settings.
4. Fill the secret environment variables.
5. Deploy.

## Finding the Render URL

After the first deploy, Render assigns an `onrender.com` URL in the service dashboard. Copy that URL into `PUBLIC_BASE_URL`.

Then redeploy so admin links and generated absolute URLs point to the live domain.

## Verifying the deployment

Check these in order:

1. `/health` returns `200`.
2. `/ready` returns `200` when the database is reachable.
3. The homepage loads over the Render URL.
4. Admin login works with the configured admin credentials.
5. The discovery and submission pages load for authenticated admins.

## AI-disabled mode

The app remains usable without AI credentials. Optional OpenAI support is controlled by:

- `OPENAI_API_KEY`
- `OPENAI_PREFILL_MODEL`
- `OPENAI_PREFILL_TIMEOUT_SECONDS`

If these are absent, the manual review and copy/paste paths remain available.

## Uploads and exports

Render filesystem storage is ephemeral. The `uploads/` and `exports/` directories are safe for temporary runtime files, but they are not durable storage.

If you need permanence for case evidence or exports, use a persistent storage plan or external object storage later.

## Rollback

If a deploy fails, roll back from the Render dashboard to the previous live deploy.

## Render Environment Variables

| Variable | Required? | Secret? | Recommended production value | Purpose |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` | Yes | Yes | Supabase PostgreSQL URL | Primary database connection |
| `SESSION_SECRET` | Yes | Yes | Long random secret | Cookie/session signing |
| `ADMIN_USERNAME` | Yes | Yes | Your admin username | First admin account seed |
| `ADMIN_PASSWORD` | Yes | Yes | Strong password | First admin account seed |
| `PUBLIC_BASE_URL` | Yes | Yes | Live Render URL | Absolute links in the app |
| `APP_ENV` | Yes | No | `production` | Production mode toggle |
| `AUTO_CREATE_TABLES` | Yes | No | `false` | Prevents table auto-creation |
| `COOKIE_SECURE` | Yes | No | `true` | Secure cookies behind HTTPS |
| `UPLOAD_DIR` | Yes | No | `uploads` | Local upload path |
| `EXPORT_DIR` | Yes | No | `exports` | Local export path |
| `DISCOVERY_MAX_QUERIES_PER_RUN` | Yes | No | `12` | Discovery rate limit |
| `DISCOVERY_RESULTS_PER_QUERY` | Yes | No | `8` | Discovery result cap |
| `DISCOVERY_REQUEST_DELAY_SECONDS` | Yes | No | `1.0` | Discovery pacing |
| `DISCOVERY_TIMEOUT_SECONDS` | Yes | No | `15` | Discovery timeout |
| `SMS_PROVIDER` | Yes | No | `disabled` | Notification provider toggle |
| `EMAIL_PROVIDER` | Yes | No | `disabled` | Notification provider toggle |
| `OPENAI_API_KEY` | No | Yes | blank unless AI enabled | Optional AI prefill |
| `OPENAI_PREFILL_MODEL` | No | No | `gpt-5-mini` | Optional AI model selection |
| `OPENAI_PREFILL_TIMEOUT_SECONDS` | No | No | `45` | Optional AI timeout |
