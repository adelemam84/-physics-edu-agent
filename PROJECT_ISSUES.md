# PROJECT ISSUE BACKLOG

This file records non-blocking or deferred issues discovered during implementation. Keep shipping safe work; resolve these in a dedicated hardening pass.

## Open

### EDU-001 — No approved lesson/explanation source is ingested yet
- Status: deferred / data prerequisite
- Observed: production database currently has one document only: `تجريبى 23.pdf`.
- Current document kind: `questions`.
- Current document status: `extraction_review_required`.
- Academic metadata on that document is not assigned.
- There are currently no lesson rows / approved question-to-lesson mappings available for source-grounded lesson reading.
- Impact: the student lesson page correctly falls back to “no source content linked” rather than generating unsupported scientific explanations.
- Guard added: lesson reading accepts only approved explanatory kinds (`lesson`, `explanation`, `textbook`, `notes`) and approved/ready/processed documents.
- Progress: upload now accepts explanatory source kinds; reviewed lesson/page mapping APIs and approval gates are implemented.
- Remaining prerequisite: ingest actual user-provided lesson/explanation PDFs and create the academic hierarchy/lesson rows, then review and approve their page ranges.

## Policy
- Scientific lesson content and questions must remain grounded in user-provided/approved source PDFs.
- Do not silently substitute model knowledge when source material is missing.
- Record newly discovered non-blocking problems here and continue implementation when safe.


### EDU-002 — Duplicate lesson-source schema/workflow discovered
- Status: deferred / compatibility hardening
- Observed: repository already contains `app/lesson_sources.py` built around a legacy table named `lesson_source_ranges`, while the new production migration adds `lesson_source_mappings`.
- Risk: registering or using the legacy module unchanged would target a different schema and can fail or create two competing workflows.
- Immediate decision: do not register the legacy module yet; keep the new table isolated until the workflow is consolidated.
- Later treatment: migrate/replace the legacy module to `lesson_source_mappings`, then remove or compatibility-map `lesson_source_ranges` only after checking production data and references.
