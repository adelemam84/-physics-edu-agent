# Production Recovery Runbook

This runbook covers technical recovery only. Question/content ingestion is intentionally outside this procedure.

## Recovery objectives

- Restore public service before diagnosis when production is unhealthy.
- Never combine application rollback with an automatic destructive database rollback.
- Prefer a previously verified Vercel production deployment whose `/health` and `/health/ready` contracts both pass.
- Keep database recovery explicit because an older application may still be compatible with additive schema changes, while destructive database rewinds can lose newer durable data.

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
- A current no-compute recovery branch named `backup-technical-hardening-2026-09-16` was created from production after the technical-hardening baseline.

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
