# PROJECT ISSUE BACKLOG

This file records non-blocking or deferred issues discovered during implementation. Keep shipping safe work; resolve these in a dedicated hardening pass.

## Open

### EDU-001 — Dedicated theory/textbook source is not yet approved
- Status: external source / human approval required; not a code blocker
- Current production has a fully mapped legacy-2020 question source plus a registered 2026 final-review source from Google Drive.
- The 2026/2027 academic hierarchy is present and active.
- Student lesson reading remains source-grounded and will not invent explanations when no approved textbook/lesson page range is linked.
- Remaining prerequisite: add an approved explanatory PDF (`lesson`, `explanation`, `textbook`, or `notes`) and review its lesson page mappings.

### EDU-002 — Lesson-source workflow consolidation
- Status: resolved
- `app/lesson_sources.py` uses the production `lesson_source_mappings` table.
- The legacy `lesson_source_ranges` table is not present in production.
- The module is registered by `index.py`, and mapping/approval gates use one schema only.

### EDU-003 — Visual transcription review queue
- Status: human source review required; AI-assisted source transcription is now available, but final approval remains human-only
- Source-backed visual assets are already attached to the current 2026/2027 candidates.
- Phase-2 manual source review increased current-curriculum approvals from 41 to 71.
- 50 source-image candidates still have `visual_transcription_required`; they remain deliberately unapproved until their exact question text, answer, academic mapping, concept, skill and difficulty are verified from the source image.
- One additional candidate remains blocked as `source_candidate_mismatch` and must not be silently converted into a question.
- No missing visual asset is currently being treated as permission to recreate or invent a diagram.

### EDU-004 — Broad-quiz legacy quality-check SQL
- Status: resolved
- The broad-quiz `quiz_quality_check` query now explicitly casts both nullable lesson placeholders to `bigint`.
- PostgreSQL can therefore resolve the parameter type even when a quiz has no single `lesson_id`.
- The existing source/QA/composition publication gates remain unchanged.

## Policy
- Scientific lesson content and questions must remain grounded in user-provided/approved source PDFs.
- Do not silently substitute model knowledge when source material is missing.
- Visual questions must preserve the authoritative source image/diagram.
- Do not close transcription QA merely because an image asset exists; text, answer and academic classification must be independently reviewed.
- Record newly discovered non-blocking problems here and continue implementation when safe.
