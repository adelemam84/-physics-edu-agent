# PROJECT ISSUE BACKLOG

This file records non-blocking or deferred issues discovered during implementation. Keep shipping safe work; resolve these in a dedicated hardening pass.

## Technical handoff status

- Open technical issues at the pre-content handoff baseline: **0**.
- Runtime: **1.8.27** with Production intake drift monitoring and exact runtime-version attestation enabled.
- Production content/source intake remains locked; this backlog must not be interpreted as permission to upload or auto-approve curriculum material.
- Controlled Production Release, Production Smoke, and Final Technical Readiness now fail closed on runtime-version drift; release/readiness also preserve the locked content-intake boundary.
- The machine-readable handoff record is `.release/pre-content-baseline.json`.

## Open

### EDU-001 — Dedicated theory/textbook source coverage is not yet approved
- Status: external source / human approval required; not a code blocker.
- Current production has a fully mapped legacy-2020 question source plus a registered 2026 final-review source from Google Drive.
- The 2026/2027 academic hierarchy is present and active.
- Student lesson reading remains source-grounded and will not invent explanations when no approved textbook/lesson page range is linked.
- Phase-start production snapshot: 10 current lessons and 0 lessons with an approved explanatory mapping.
- Completion now requires every current lesson to have at least one explicitly approved page range from an explanatory PDF (`lesson`, `explanation`, `textbook`, or `notes`). One approved mapping is not enough to close this gate.
- `/admin/content-completion` is the canonical workflow for Drive-source intake, bounded extraction, draft lesson mapping, and explicit mapping approval.

### EDU-002 — Lesson-source workflow consolidation
- Status: resolved.
- `app/lesson_sources.py` uses the production `lesson_source_mappings` table.
- The legacy `lesson_source_ranges` table is not present in production.
- The module is registered by `index.py`, and mapping/approval gates use one schema only.

### EDU-003 — Visual transcription review queue
- Status: human source review required; AI-assisted source transcription is available, but final approval remains human-only.
- Source-backed visual assets are already attached to the current 2026/2027 candidates.
- Phase-2 manual source review increased current-curriculum approvals from 41 to 71.
- Phase-start production snapshot: 50 source-image candidates still have `visual_transcription_required`; they remain deliberately unapproved until their exact question text, answer, academic mapping, concept, skill and difficulty are verified from the source image.
- One additional candidate remains blocked as `source_candidate_mismatch` and must not be silently converted into a question.
- Counts above are point-in-time values; `/admin/content-completion` reads the live database state.
- No missing visual asset is currently being treated as permission to recreate or invent a diagram.

### EDU-004 — Broad-quiz legacy quality-check SQL
- Status: resolved.
- The broad-quiz `quiz_quality_check` query now explicitly casts both nullable lesson placeholders to `bigint`.
- PostgreSQL can therefore resolve the parameter type even when a quiz has no single `lesson_id`.
- The existing source/QA/composition publication gates remain unchanged.

## Policy
- Scientific lesson content and questions must remain grounded in user-provided/approved source PDFs.
- Do not silently substitute model knowledge when source material is missing.
- Visual questions must preserve the authoritative source image/diagram.
- Do not close transcription QA merely because an image asset exists; text, answer and academic classification must be independently reviewed.
- Importing or extracting a source does not approve it; lesson mappings are draft until an explicit human approval action.
- Record newly discovered non-blocking problems here and continue implementation when safe.

## Final Curriculum Content Completion
- `/admin/content-completion` is the canonical live cockpit for the remaining content gates.
- `content_complete` requires full current-curriculum explanatory-source coverage and zero open question QA.
- Large Drive-hosted PDFs can be imported server-side by explicit URL selection, avoiding serverless browser-upload body limits while preserving the selected Drive URL as provenance.
- Page extraction is bounded and page-number preserving; blank/unreadable pages remain blocking rather than being guessed.
- Visual transcription assistance stays source-image-only and never auto-approves a question.

## Final Production Closure
- `/admin/project-closure` remains the canonical final handover view.
- Project code/runtime completion and curriculum/content completion are deliberately reported separately.
- Remaining EDU-001 and EDU-003 work stays external/human-gated until a real explanatory source and teacher review are supplied.
