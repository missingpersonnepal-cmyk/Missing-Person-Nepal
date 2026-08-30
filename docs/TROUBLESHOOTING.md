# Troubleshooting

## Site does not start

Check Python dependencies, environment configuration, port conflicts, and application logs. Do not print `.env`. Verify `DATABASE_URL` is present without displaying its value.

## `/health` works but `/ready` fails

The web process is alive but the database is unavailable. Check Supabase project status, network/DNS, connection pooler mode, SSL requirements, credentials rotation, and SQLAlchemy/psycopg compatibility.

## Discovery returns no results

Confirm the event locations and dates, provider configuration/quota, and public network access. Try generated searches, tracked source accounts, and manual public URL intake. Empty discovery does not mean no people are missing.

## AI Prefill is unavailable or fails

Confirm server-side OpenAI configuration and quota without exposing the key. The source must be Relevant. Use the manual prepared-prompt fallback, then verify every field.

## Duplicate warning appears

The operational warning now requires an exact normalized name match to an active published case. Open the published case and compare supporting details. Attach the source only when it is the same person; otherwise restore as a separate review.

## Image is missing

Check whether the source exposed a public image, whether download validation accepted it, and whether the media file exists in persistent storage. A neutral placeholder is expected when no usable image exists.

## Changes are not visible

Confirm the latest commit is deployed, restart the application if hot reload is disabled, and hard-refresh static assets. Verify the process listening on the expected host and port.

## Safe incident response

Preserve logs and audit records, restrict access, avoid destructive database commands, and use a test database to reproduce the issue. Escalate suspected data exposure immediately.

