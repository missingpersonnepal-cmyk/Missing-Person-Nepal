# Search and Discovery Guide

## Discovery methods

The system combines four complementary methods:

1. **Standard discovery**: bounded public-index queries using event locations and missing-person terms.
2. **Wide discovery**: broader Facebook-focused queries through the configured search provider.
3. **Tracked sources**: operator-added public pages, groups, profiles, or handles reused in future searches.
4. **Manual intake**: a public URL and available text supplied when indexing missed a post.

No method logs into a social platform or accesses private content.

## Preparing an event

Add districts, municipalities, villages, roads, rivers, projects, shelters, and common English/Nepali spelling variants to the event's affected locations. Search quality depends heavily on this list.

## Search tags

The system generates event queries automatically. Add a custom tag only when a phrase is missing, for example a local spelling, project name, hashtag, or Nepali phrase used by reporters. Prefer short phrases over full sentences.

## Tracked source accounts

Add a public page, group, or repeat sharer when it consistently publishes relevant reports. Use its canonical public URL or handle. Tracking is a search hint, not a trust decision; every result still requires review.

## Candidate triage

Mark Relevant only when the public evidence explicitly reports a missing or out-of-contact person in the event context. Rescue updates, fundraising, generic disaster news, and unrelated historic posts belong in Irrelevant.

## Duplicate-source isolation

When an explicitly detected name exactly matches an active published case, the candidate is routed to Possible Duplicates. Similar spellings do not trigger this route. Compare location, age, image, contact and source text before attaching the source.

## Known limitations

- Public search indexes can lag or omit Facebook posts.
- Public metadata may be truncated.
- OCR quality depends on poster resolution and language support.
- A post may mention several people; each must be reviewed separately.
- AI extraction can omit or misassign fields and must be verified.

Manual public URL intake remains the reliable fallback.

