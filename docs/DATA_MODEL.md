# Data Model

## Core rule

**Person != report != source.**

A master person represents one unique human case within one disaster. A report is a claim/submission about that person. A source is the public URL or publication evidence behind a claim.

## `mp_disasters`

Defines one event and its affected-location terms. V0 stores locations as newline-separated text because the discovery/search requirement is primarily lexical. GIS geometry can be added later without breaking records.

## `mp_missing_people`

One row per master person/case.

Important public fields include name, Nepali name, age, gender, last seen, clothing, identifying features, selected public contact number, and published/archive state.

Sensitive fields include residential address and private contact details.

## `mp_sources`

Stores evidence/provenance URLs for a master person. The uniqueness rule is `(person_id, url)`, not global URL uniqueness, because one Facebook list post may legitimately mention several different missing people.

## `mp_submissions`

Staging queue for direct public reports, additional information, and extracted discovery reports. A submission is not public by default.

## `mp_discovery_candidates`

Stores URLs/snippets discovered by the bot or manually added by an admin. A candidate is not yet a missing-person case. Candidate URL uniqueness is scoped to a disaster event, so one public source can legitimately be reviewed under two separate events without collapsing their provenance.

## `mp_admins`

Local V0 admin users. Passwords are PBKDF2-SHA256 hashes with per-password random salts.

## `mp_audit_logs`

Records important administrative actions such as login, publication, archival, source addition, exports, and discovery runs.

## Case numbers

Case numbers are generated as:

```text
NP-{YEAR}-{EVENT_CODE}-{SEQUENCE}
```

Example:

```text
NP-2026-RF-00001
```

They are stable human-facing identifiers and are never reused.
