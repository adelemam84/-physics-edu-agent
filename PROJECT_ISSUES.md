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
- Later treatment: build/administer PDF lesson-source ingestion, academic tagging, lesson/page mapping, extraction review, and approval workflow.

## Policy
- Scientific lesson content and questions must remain grounded in user-provided/approved source PDFs.
- Do not silently substitute model knowledge when source material is missing.
- Record newly discovered non-blocking problems here and continue implementation when safe.
