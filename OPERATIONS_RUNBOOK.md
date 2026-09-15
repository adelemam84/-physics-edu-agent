# Physics Education AI Agent — Production Operations Runbook

## Scope

This runbook covers the technical production runtime only. Question/source content ingestion remains a separate controlled phase and is intentionally not required for technical runtime readiness.

## Current production contracts

- Canonical service: `https://physics-edu-agent.vercel.app`
- Liveness: `GET /health` must return HTTP 200 with `status=ok`.
- Readiness: `GET /health/ready` must return HTTP 200 with `status=ready` and `Cache-Control: no-store`.
- Research engine public status must remain source-only and must not auto-publish.
- Controlled production releases stage and verify a deployment before promotion.
- Controlled rollback requires an explicit known-good Vercel deployment and a `ROLLBACK` confirmation.

## Automated safety checks

- Production smoke: every 6 hours, read-only, evidence retained for 14 days.
- Final technical readiness: daily, read-only, evidence retained for 30 days.
- Python dependency CVE audit: on push/PR and weekly.
- CI regression suite: on push/PR.

## Incident sequence

1. Check `/health` and `/health/ready`.
2. Check Vercel runtime errors for the active deployment, not only historical project errors.
3. Check Neon for stalled queries and locks.
4. If the application deployment is faulty while the database is healthy, use the Controlled Production Rollback workflow with a previously verified deployment.
5. Do not use a database restore to solve an application-only incident.
6. Database recovery is a separate operator action and must be restored to a separate branch first for verification whenever possible.

## Database recovery evidence — 2026-09-16

A non-destructive recovery drill successfully restored snapshot `before-current-corpus-batch-2` (`snap-withered-dew-a5q7bh6e`) to a separate Neon branch and verified that database `physics_agent` was readable. Representative restored counts were 216 questions, 7 quizzes, 3 documents and 17 lessons. Production was not modified.

### Current Neon backup limitation

At the time of the drill:

- A new manual snapshot could not be created because the project snapshot limit was reached.
- Automatic backup schedule creation was rejected because backup scheduling is not enabled for this Neon project.
- The existing manual snapshot must therefore not be deleted until a newer recovery point can be created under an upgraded/changed Neon backup entitlement or another approved backup mechanism.

This limitation is operational, not a runtime-readiness failure, but it increases recovery-point age. Re-evaluate before loading material amounts of production student/content data.

## Database recovery procedure

1. Never restore directly over the production branch as the first recovery action.
2. Restore the selected snapshot to a new recovery branch.
3. Verify the expected database exists and run read-only integrity/count checks.
4. Compare the recovery point with the incident time and required RPO.
5. Only after explicit operator approval should production traffic/database pointers be changed or an existing production branch be replaced.
6. Remove temporary recovery branches after the drill when explicitly authorized.

## Performance baseline

The bounded production performance probe uses 100 read-only requests at concurrency 10. The post-hardening baseline achieved 100/100 successes, 0% error rate, overall p95 below 1 second and throughput above 22 requests/second. Performance tests must remain read-only unless a separate load-test environment is used.

## Security boundaries

- Admin and student authentication use signed HttpOnly cookies; admin cookie mutations require same-origin when using browser session authentication.
- Login and expensive operations are rate-limited using database-backed counters.
- Rate-limit subjects are keyed with HMAC-derived identifiers rather than storing raw subjects.
- Forwarded client IP headers are trusted automatically only on Vercel; other reverse proxies must explicitly opt in after they are configured to overwrite client-supplied forwarding headers.
- Browser-session mutations require an exact scheme/host/effective-port origin match, and explicit cross-site Fetch Metadata is rejected.
- Meta WhatsApp POST callbacks require the Meta HMAC signature and enforce a bounded request body.
- AI provider operations are governed by task policy, telemetry, budget controls and bounded retry rules; stateful provider mutations are not blindly replayed.
- Secrets must stay in Vercel/GitHub/managed provider secret stores and must never be committed to the repository.

## Release / rollback separation

Application rollback changes Vercel production traffic only. Database recovery is deliberately separate. A successful rollback must always be followed by canonical `/health` and `/health/ready` smoke checks.
