# Final Technical Readiness Gate

This gate is a read-only production contract for the Physics Education AI Agent. It intentionally does not upload, mutate, approve, or publish curriculum/question content.

## What it verifies

- Public liveness and readiness return their expected contracts.
- Production security headers remain present, including HSTS, CSP, frame denial, content-type protection, referrer policy, and permissions policy.
- Readiness and student-session identity responses remain non-cacheable.
- Anonymous requests cannot read a protected admin AI operations API.
- Anonymous student session inspection remains unauthenticated and does not create a cookie.
- The research engine remains source-only and cannot auto-publish.
- The release plane remains runtime-ready even while content ingestion is explicitly deferred.
- Public responses are checked for sensitive-looking key names.
- Each checked endpoint must remain within a bounded latency ceiling, with one retry for transient cold-start/network variance.

## Evidence

The **Final Technical Readiness** GitHub Actions workflow runs on relevant main-branch changes, manual dispatch, and once daily. It uploads `technical-readiness-results.json` for 30 days and writes a compact run summary.

This gate complements, rather than replaces:

- deterministic unit/contract CI,
- dependency CVE audit,
- bounded production performance readiness,
- six-hour production smoke monitoring,
- controlled production release and rollback workflows.

## Database recovery note

Neon currently reports no automatic snapshot schedule and rejected creation of an additional snapshot with `snapshots limit exceeded`. It also rejected protecting the production branch because the current plan's protected-branch limit is already reached. A fresh no-compute baseline (`pre-content-technical-complete-2026-09-16-v2`) now captures the current production HEAD, alongside the older recovery branch and manual provider snapshot. These plan limits are operational constraints, not content blockers; do not delete existing recovery assets merely to make room without an explicit recovery-plan decision.\n\nProduction content intake is additionally fail-closed by default. `CONTENT_INGESTION_ENABLED=true` is required to open source uploads deliberately; the technical readiness phase does not need or perform curriculum uploads.

Content ingestion remains deferred until the technical platform is deliberately handed over for that phase.
