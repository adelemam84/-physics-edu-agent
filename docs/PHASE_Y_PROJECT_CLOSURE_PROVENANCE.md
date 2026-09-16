# Phase Y — Project Closure Consistency & Deployment Provenance

## Goal

Make the final project closure manifest distinguish three independent facts:

1. whether the software/runtime is code-complete,
2. which Vercel deployment is actually executing the closure code,
3. whether scientific/content and teacher-owned gates are complete.

The phase reuses the strict Phase X Lesson Studio acceptance result instead of treating internal release status as proof that all scientific release gates are complete.

## Implemented contract

- `code_complete` requires both Completion Audit code readiness and zero Phase X system blockers.
- `content_complete` requires no Completion Audit external/human gates and a fully ready Phase X acceptance path.
- `production_runtime_verified` means the current runtime self-reports as a Vercel Production deployment built from `main` with an available Git commit SHA.
- The closure response exposes Vercel environment, ref, deployment id, production URL and deployed commit SHA when system metadata is available.
- The runtime never claims that its commit equals the latest GitHub `main` commit. `latest_main_match` remains unknown inside the application and requires external deployment verification.
- Preview deployments can never satisfy the Production-main runtime check.
- Teacher/source gates remain separate from software defects.

## Deployment provenance

Vercel system environment variables are used only as local runtime metadata:

- `VERCEL`
- `VERCEL_ENV`
- `VERCEL_TARGET_ENV`
- `VERCEL_GIT_COMMIT_REF`
- `VERCEL_GIT_COMMIT_SHA`
- `VERCEL_DEPLOYMENT_ID`
- `VERCEL_PROJECT_PRODUCTION_URL`

No GitHub or Vercel API call is made from the closure endpoint. Matching the deployed SHA to the repository's latest `main` remains an external deployment-monitoring responsibility.

## Closure states

- `programmatic_attention_required` — a software/runtime or Phase X system blocker exists.
- `production_deployment_verification_required` — code is ready but the executing runtime cannot prove it is a Production deployment from `main`.
- `production_code_complete_external_gates_open` — code and deployment are healthy, but source/teacher/scientific gates remain.
- `production_and_content_complete` — code, executing Production-main deployment metadata, and all content/teacher gates are complete.

## Safety invariants

1. Deployment metadata never closes a scientific gate.
2. Missing theory/reference material is never filled from model memory.
3. Human review queues are never converted into code defects merely to obtain a green closure state.
4. A Preview deployment never impersonates Production.
5. The application reports only its own deployed SHA; latest-main equality is verified externally.
6. Phase X hash-bound teacher approval and PDF freshness remain the authoritative Lesson Studio acceptance contract.

## Pre-content handoff baseline — 2026-09-17

The repository now carries a machine-readable closure artifact at `.release/pre-content-baseline.json`. It is deliberately stricter than a prose status note:

- `technical_complete=true` while `content_complete=false`.
- `content_ingestion=locked` and `content_phase=deferred`.
- The artifact records the requested code SHA, release-marker SHA, production deployment id/URL, release evidence run ids, and the Neon recovery checkpoint.
- Contract tests fail if the baseline claims content completion, if intake is not locked, if the release marker drifts from the requested code SHA, or if the recovery checkpoint is not a ready no-compute handoff branch.
- The current unresolved work is limited to the external/human content gates `EDU-001` and `EDU-003`; there are zero open technical issues in the handoff manifest.

This baseline does not approve any source, lesson, question, diagram, answer, mapping, or scientific correction. It only records the verified technical state from which the future content phase may begin.
