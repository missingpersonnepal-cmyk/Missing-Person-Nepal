# Operator User Manual

## Purpose

This hub consolidates public missing-person reports during a disaster. It does not make an official determination that a person is missing. Every published case must remain traceable to one or more sources.

## Daily workflow

1. Log in at `/admin/login` and open the Dashboard.
2. Work through the numbered dashboard steps from left to right.
3. In **To Review**, classify each source as Relevant or Not relevant.
4. In **Relevant**, use **AI Prefill** to open the source and extract all explicitly named people.
5. Verify names, age, location, dates, contact details, image, and source text. AI output is a suggestion.
6. If an exact published name exists, compare the published case and place the source in **Possible Duplicates**.
7. Attach a repeated source to the existing person, or restore it as a separate review when it is genuinely another person.
8. Approve pending submissions or attach them to an existing master record.
9. Publish only reviewed cases. Update resolved cases to Found or Identified promptly.
10. Export the active event at shift end for authorized handover.

## Queue meanings

| Queue | Meaning | Expected action |
|---|---|---|
| To Review | Newly discovered public sources | Relevant or Not relevant |
| Relevant | Sources likely containing missing-person reports | AI Prefill, verify, save |
| Possible Duplicates | Exact detected-name matches to published cases | Compare and attach or restore |
| Irrelevant | Sources intentionally excluded | Restore only if classification was wrong |
| Done Posts | Source review is complete | Reopen only when information was missed |
| Pending Submissions | Reports not yet master cases | Approve new, attach existing, or reject |

## Publishing checklist

- Name is copied accurately from the source.
- Last-seen location belongs to the selected disaster context.
- Date, age, phone and clothing are not guessed.
- The public contact number is intentionally public.
- The image belongs to the report and does not expose unnecessary private information.
- Existing exact-name cases and pending submissions were reviewed.
- At least one source URL is retained.

## Corrections and resolved cases

Use **Edit** on a case for factual corrections. Use Found or Identified status instead of deleting a resolved case. Archive/Delete is reserved for records that should no longer exist, such as confirmed erroneous duplicates.

## Safety rules

- Never use facial recognition or infer identity from appearance.
- Never publish private reporter contact details or residential addresses.
- Never treat a social-media post as official verification.
- Never access private groups, bypass login walls, or evade platform controls.
- Keep exports restricted because they may include private operational fields.

