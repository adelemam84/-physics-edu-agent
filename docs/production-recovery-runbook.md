# Production Recovery Runbook

This runbook covers technical recovery only. Question/content ingestion is intentionally outside this procedure.

## Recovery objectives

- Restore public service before diagnosis when production is unhealthy.
- Never combine application rollback with an automatic destructive database rollback.
- Prefer a previously verified Vercel production deployment whose `/health` and `/health/ready` contracts both pass.
- Keep database recovery explicit because an older application may still be compatible with additive schema changes, while destructive database rewinds can lose newer durable data.

## Rollback preflight

Before an actual traffic rollback, run the **Production Rollback Preflight** workflow against the intended Vercel deployment. It performs read-only checks only and does not change production traffic. It verifies `/health`, `/health/ready`, runtime-version consistency, the locked content-ingestion boundary, and captures research/next-release status evidence.

Only proceed to **Controlled Production Rollback** when an incident actually requires a traffic change and the candidate has passed preflight.

## Application rollback

Use the **Controlled Production Rollback** GitHub Actions workflow.

1. Choose a known-good generated deployment URL or deployment ID from Vercel.
2. Run the workflow with that target and the exact confirmation value `ROLLBACK`.
3. The workflow verifies the target's `/health` and `/health/ready` before changing production traffic.
4. Vercel rollback is requested only after those gates pass.
5. Canonical production health/readiness are checked again after rollback.

The workflow shares the same production concurrency group as releases, so a release and rollback cannot intentionally run at the same time.

## Database recovery

Current Neon production project: `Physics-Edu-Agent-DB`, default branch `production`.

Provider capabilities observed on 2026-09-16:

- Point-in-time history retention: 6 hours.
- Automatic snapshot schedules are not enabled for the current project/plan.
- Protected branches are not available within the current plan limit.
- A provider snapshot exists from the earlier corpus work.
- The plan currently rejects both another protected branch and another provider snapshot (`maximum number of protected branches` / `snapshots limit exceeded`).\n- A fresh no-compute recovery branch named `pre-content-technical-complete-2026-09-16-v2` was created directly from the current production HEAD after the v1.8.2 technical release. Its parent is the production branch and its recorded parent timestamp is `2026-09-15T23:39:38Z`.\n- Keep the earlier `backup-technical-hardening-2026-09-16` recovery branch as an additional older checkpoint until a deliberate cleanup decision.

Do not delete or reset production automatically. If database recovery is required, first determine whether the incident is application-only. Prefer application rollback when the database is healthy. A database restore must be treated as a separate operator decision with loss-window review.

## Before schema-risky changes

The normal production bootstrap is additive/idempotent. Before any future destructive or data-rewriting migration:

1. Create a fresh Neon snapshot or no-compute recovery branch.
2. Record the production commit and database recovery point.
3. Test the migration on a temporary branch.
4. Require explicit approval before applying destructive SQL to production.
5. Keep content ingestion deferred until the technical platform is stable.

## Post-recovery verification

After any recovery action:

- `/health` returns HTTP 200 and `status=ok`.
- `/health/ready` returns HTTP 200 and `status=ready`.
- Vercel shows no new runtime error cluster.
- Neon has no stalled queries or blocking locks.
- Production deployment provenance is recorded.
\n\n## Pre-content intake lock\n\nProduction source uploads are fail-closed while the curriculum phase is deferred. `CONTENT_INGESTION_ENABLED` must be explicitly set to `true` before PDF/Drive/reference/question-asset/Lesson-Studio source intake is allowed. Local and CI execution remain usable by default so technical regression tests do not depend on production content state.\n