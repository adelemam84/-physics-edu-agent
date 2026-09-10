# Phase AB — Human Acceptance Evidence Queue

## Goal

Turn the strict Phase AA acceptance result into a concrete, ordered work queue based only on current source and review evidence. The queue tells an administrator what remains, who owns it, why it is blocked, and where to resolve it without performing any approval action itself.

## Canonical endpoints

- Admin page: `/admin/acceptance-work-queue`
- Admin API: `/api/admin/acceptance-work-queue`

Both routes are independently protected by the existing administrator authentication gate.

## Evidence sources

The queue composes three read-only contracts:

- `content_completion_snapshot()` for active-curriculum lesson coverage and question QA;
- `acceptance_snapshot()` for Lesson Studio system and teacher checks;
- `e2e_content_acceptance_snapshot()` as an independent final consistency guard.

No historical hard-coded counts are used as current state.

## Queue model

Each item includes:

- stable `id`;
- `category`;
- numeric `priority`;
- `owner` (`system` or `teacher`);
- human-readable `title` and `detail`;
- the admin `path` where the work belongs;
- bounded `evidence` supporting the task.

Priority order is:

1. `0` — system/runtime/diagnostic integrity blockers;
2. `1` — current-curriculum explanatory source coverage;
3. `2` — question/source QA review;
4. `3` — Lesson Studio teacher/scientific/release gates.

System-owned blockers therefore appear before human work.

## Fail-closed behavior

- Missing expected Lesson Studio checks become explicit system tasks.
- Malformed lesson, QA, or Studio-check lists become system blockers rather than being treated as empty.
- An inactive current curriculum becomes an explicit setup task.
- If Phase AA reports final readiness while concrete evidence tasks remain, the queue creates an inconsistency blocker and refuses to report ready.

## Safety invariants

- The queue is diagnostic/read-only.
- It contains no POST/write action.
- It never approves a source mapping or question.
- It never synthesizes teacher approval.
- It never creates a final PDF.
- It never invents missing scientific text, answers, mappings, diagrams, or classifications.
- The live database/source evidence remains authoritative.
- Existing teacher and scientific review gates remain the only way to close human-owned tasks.
