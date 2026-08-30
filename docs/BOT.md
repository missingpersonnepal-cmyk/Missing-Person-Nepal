# Public Facebook / Social Discovery Bot

## Purpose

The V0 bot exists to surface **candidate public missing-person reports** during a disaster. It is not a general Facebook crawler and it does not decide that a person is missing.

## Scope

Allowed V0 discovery:

- publicly indexed Facebook posts/pages/open-group URLs;
- public Instagram/TikTok/X/Reddit/web search results where indexed;
- manual public URL intake by an admin;
- generated Google search links for human-assisted discovery.

Explicitly excluded:

- private/closed Facebook group access;
- Facebook credentials/session automation;
- login-wall bypasses;
- CAPTCHA bypasses;
- anti-bot evasion;
- WhatsApp/Messenger access;
- hidden/private profile data.

## Query generation

Queries combine:

1. platform site filter;
2. configured affected location;
3. Nepali or English missing-person terminology;
4. Nepal/disaster context and disaster year.

The admin-generated Google links additionally apply an `after:` / `before:` window starting on the configured disaster date.

Examples:

```text
site:facebook.com "Rasuwa" "missing person" 2026
site:facebook.com "Timure" "सम्पर्कविहीन" 2026
site:facebook.com "Rasuwagadhi" "बेपत्ता" 2026
```

Seed keywords include:

### Nepali

- सम्पर्कविहीन
- सम्पर्क विहीन
- बेपत्ता
- हराएको
- हराइरहेको
- खोजिदिनुहोला
- सम्पर्क गर्नुहोला

### English

- missing person
- missing
- out of contact
- unaccounted for
- please help find
- last seen

## Automated provider

V0 uses a small, rate-limited public DuckDuckGo HTML search helper because it requires no paid API key.

Defaults:

- max 12 queries per run;
- max 8 results per query;
- 1 second delay between queries;
- 15 second request timeout.

All are environment-configurable.

The provider is deliberately fail-soft. If a search engine blocks or changes markup, discovery returns fewer/no candidates and the rest of the application continues working.

## Manual fallback

Manual URL intake is mandatory even when the automated provider works. Facebook indexing is incomplete and can lag behind recent public posts, especially group content.

The expected disaster workflow is therefore hybrid:

```text
Bot discovery + generated searches + volunteers/admins watching public groups
                              ↓
                         Candidate URLs
                              ↓
                         Admin review
```

## Candidate lifecycle

```text
new → reviewed → submission review → attach existing / create new master case
```

A single candidate post may describe multiple missing people. Admins may extract more than one submission from the same candidate URL if required. The candidate remains reviewable after each extraction so a public list post can feed several unique master cases while retaining the same original source URL.

## Current operational queues

- `new` / `needs_ai`: To Review triage.
- `relevant`: confirmed source, ready for one-click AI Prefill.
- `possible_duplicate`: an explicitly detected name exactly matched a published case; compare and attach or restore.
- `irrelevant` / `rejected`: excluded source archive.
- `reviewed`: all people in the source have been handled.

A source can mention multiple people and remains Relevant until each explicitly named person is handled. Similar names alone are not automatically isolated as duplicates.

## Future providers

The bot interface can later add approved providers such as:

- official Meta public-content access where eligibility/permissions permit;
- commercial search APIs;
- X API;
- approved TikTok research/public-content interfaces;
- government/NGO feeds.

The database does not depend on any one provider.

## CLI / scheduler entry point

One bounded discovery cycle can run without the web UI:

```bash
python -m app.bot_runner --event RF --platform facebook
```

This is intentionally a single-cycle command. A scheduler can call it later, but V0 does not introduce a paid queue, cron service, or always-on worker.
