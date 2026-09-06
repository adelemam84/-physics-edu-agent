# Physics Education AI Agent — v1.1 Corpus QA

Post-v1 production hardening release.

## Added
- Persistent QA reasons for unapproved source questions.
- Admin QA summary and review-note APIs.
- Approval gate now blocks questions with unresolved QA notes.
- Release metrics report open/critical/resolved QA counts.
- DB startup migration creates QA structures idempotently.

## Corpus state at implementation
- 94 real-source questions registered.
- 65 approved.
- 29 held for review with explicit reasons.
- Source-answer anomalies are preserved, never silently corrected.
