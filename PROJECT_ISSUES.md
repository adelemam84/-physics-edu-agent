# PROJECT ISSUE BACKLOG

This file records non-blocking or deferred issues discovered during implementation. Keep shipping safe work; resolve these in a dedicated hardening pass.

## Open

### EDU-001 — Dedicated theory/textbook source is not yet approved
- Status: non-blocking content expansion
- Current production has a fully mapped legacy-2020 question source plus a registered 2026 final-review source from Google Drive.
- The 2026/2027 academic hierarchy is now present and marked active.
- Student lesson reading remains source-grounded and will not invent explanations when no approved textbook/lesson page range is linked.
- Remaining prerequisite: add an approved explanatory PDF (`lesson`, `explanation`, `textbook`, or `notes`) and review its lesson page mappings.

## Policy
- Scientific lesson content and questions must remain grounded in user-provided/approved source PDFs.
- Do not silently substitute model knowledge when source material is missing.
- Record newly discovered non-blocking problems here and continue implementation when safe.


### EDU-002 — Lesson-source workflow consolidation
- Status: resolved
- `app/lesson_sources.py` now uses the production `lesson_source_mappings` table.
- The legacy `lesson_source_ranges` table is not present in production.
- The module is registered by `index.py`, and mapping/approval gates use one schema only.


### EDU-003 — Visual source crops
- Status: operational review queue
- 19 diagram/graph-dependent questions remain intentionally unapproved until a durable question-asset copy is stored.
- The platform is fully operational without publishing those questions; text-self-sufficient questions are no longer blocked by an unnecessary asset requirement.
- Generated crop coordinates/images for the remaining 19 visual questions have been verified locally from the real PDF source. The admin now supports direct JPG/PNG/WEBP upload for external/Google Drive sources; persistent image upload remains a content-operations task, not a release blocker.
