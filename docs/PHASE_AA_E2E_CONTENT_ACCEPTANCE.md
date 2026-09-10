# Phase AA — End-to-End Content Acceptance Matrix

## Goal

Provide one final, read-only acceptance view that joins the two independent release truths of the science education platform:

1. the active curriculum is complete from approved real source material; and
2. Lesson Studio has at least one coherent, current, source-grounded path through scientific review, teacher approval, and final PDF export.

Neither side can impersonate final readiness on its own.

## Canonical endpoints

- Admin page: `/admin/e2e-content-acceptance`
- Admin API: `/api/admin/e2e-content-acceptance`

Both are protected by the existing administrator authentication gate.

## Matrix stages

The matrix checks, in visible workflow order:

1. active current curriculum;
2. real explanatory document registered;
3. full page-complete approved explanatory coverage for every current lesson;
4. zero open current-curriculum question QA;
5. Lesson Studio system/runtime readiness;
6. real Lesson Studio reference PDF ingestion;
7. fresh curriculum map derived from the current reference;
8. structured real-source lesson;
9. resolved and bound OCR sources;
10. current non-blocking scientific reference review;
11. teacher approval bound to the current content and diagram manifest;
12. at least one complete current final-PDF release path.

## Decision contract

`overall_ready` is true only when:

- `content_complete` is true for the current curriculum;
- Lesson Studio `acceptance_ready` is true; and
- every matrix stage is currently passing.

System-owned blockers are selected as `next_action` before teacher/human work. Missing upstream Lesson Studio checks fail closed rather than being treated as success.

## Safety invariants

- The dashboard is diagnostic/read-only.
- It performs no approval action.
- It creates no PDF and mutates no source, question, lesson, mapping, or release state.
- It never synthesizes teacher approval.
- It never fills missing scientific content from model memory.
- Existing human approval and scientific review gates remain authoritative.
- Curriculum completion and Lesson Studio acceptance must both pass independently.

## Relationship to prior phases

Phase X protects strict Lesson Studio production acceptance. Final Curriculum Content Completion protects whole-curriculum explanatory coverage and question QA. Phase AA composes those contracts without weakening either one, giving the administrator a single final acceptance matrix and next-action pointer.
