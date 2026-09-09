# Final Curriculum Content Completion

## Goal

Finish the real-source curriculum layer without confusing software readiness with scientific/content approval.

The platform is already production-operational. This phase tracks and supports the remaining source and human-review work required before `content_complete` can become true.

## Completion contract

For the active third-secondary physics curriculum, content completion requires all of the following:

1. Every current lesson has at least one explicitly approved explanatory source mapping.
2. The mapping points to an allowed explanatory document kind: `lesson`, `explanation`, `textbook`, or `notes`.
3. The document and lesson academic contexts match exactly.
4. Every page in the mapping's inclusive `start_page`–`end_page` range exists in `document_pages` and has nonblank extracted source text. A partially extracted or blank range never counts as coverage.
5. No current-curriculum question QA note remains open.
6. Visual transcription and source-candidate mismatch queues are resolved by human source review.

A single approved mapping can never satisfy whole-curriculum source coverage, and an approved mapping with missing or blank source pages cannot satisfy even one lesson's coverage gate.

## Administrator workflow

`/admin/content-completion` is the canonical cockpit for this phase.

It provides:

- current lesson-by-lesson explanatory-source coverage;
- explicit Google Drive PDF import as `source_review_required` only;
- bounded page-text extraction while preserving original PDF page numbers;
- gap-aware extraction that resumes from the first missing page rather than assuming pages were processed in order;
- draft page-range mapping to a lesson;
- explicit manual mapping approval through the existing lesson-source approval gate;
- current visual-transcription and source-mismatch counts;
- access to the source-only visual suggestion workflow, which remains advisory and never auto-approves a question.

Large source files should use the Drive import path rather than browser file upload so the application does not depend on serverless inbound-body limits.

## Safety invariants

- The PDF is authoritative.
- Importing a PDF never approves it.
- Extracting PDF text never approves a mapping or question.
- Creating a lesson mapping creates a draft only.
- Mapping approval remains an explicit administrator/teacher action.
- Visual suggestions are drafts from exact source crops only.
- Missing or unreadable content is never filled from model memory.
- Blank or missing pages inside an approved range remain blocking and must not be silently treated as valid source pages.
- `content_complete` requires full current-curriculum coverage and zero open question QA.

## Production snapshot at phase start

The phase-start production audit for curriculum `2026/2027` showed:

- 10 current lessons;
- 0 lessons with an approved explanatory-source mapping;
- 50 open `visual_transcription_required` items;
- 1 open `source_candidate_mismatch` item.

These numbers are a point-in-time snapshot, not constants. The live cockpit always reads the current database state.
