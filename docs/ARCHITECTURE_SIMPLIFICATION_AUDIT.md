# Architecture Simplification Audit — Phase 1

Baseline: `728556c585e0e1eb47c88f8c530b496add3b6c6f`

## Guardrails

- No curriculum/question ingestion in this refactor.
- Keep `content_ingestion=locked`.
- Keep free-only AI policy.
- Do not change Farida AI Agent.
- No new release/readiness layer unless a real regression requires it.
- Refactor incrementally behind CI + production smoke; do not mass-delete modules.

## Findings

### Application shape
- 318 Python files currently exist in the repository.
- `index.py` registers a very large number of features through import side effects.
- `app/main.py` still owns middleware, models, data access, document ingestion and routes directly.
- This creates import-order coupling and makes route ownership difficult to trace.

### Workflow shape
12 GitHub Actions workflows currently exist:
- ci
- execute-edu001-edu003
- final-technical-readiness
- performance-readiness
- production-release
- production-rollback
- production-smoke
- rollback-preflight
- security-audit
- self-hosted-production-release
- self-hosted-runner-diagnostics
- self-hosted-runner-repair

The repository is temporarily Public and routine work is expected to use GitHub-hosted `ubuntu-latest`, so the self-hosted diagnostic/repair path is a retirement candidate.

### Content state
Content remains intentionally incomplete. EDU-001 and EDU-003 remain human/source-gated. This refactor must not be used to bypass those gates.

## Target architecture

```
app/
  main.py
  routers/
    student/
    admin/
    exams/
    content/
    integrations/
  services/
  repositories/
  models/
  security/
```

Route modules should expose `APIRouter` objects. `main.py`/an application factory should include routers explicitly rather than depending on `from app.main import app` import side effects.

## Classification policy

Every Python module will be classified as:
- KEEP — clear runtime responsibility and appropriate boundary.
- MIGRATE — active feature that should move to an APIRouter/service/repository boundary.
- MERGE — active but too fragmented; merge into an adjacent cohesive module.
- DELETE — proven unused/obsolete only after import, route, test, DB/migration and production-contract checks.

Small file size alone is never deletion evidence.

## Initial candidates

- `phase2_admin.py`: MERGE/MIGRATE candidate; inspect callers/routes/tests before changing.
- `release_hardening.py`: KEEP until release contracts are mapped; do not weaken current safety gates.
- `acceptance_work_queue.py`: KEEP/MIGRATE while EDU human-review workflow remains.
- `project_closure.py`: MERGE candidate after handoff/reporting dependencies are mapped.
- self-hosted runner diagnostic/repair workflows: RETIRE candidates while the Public/hosted-runner policy remains active.

## Execution sequence

1. Freeze new hardening/readiness features unless fixing a demonstrated regression.
2. Build route/import ownership inventory.
3. Introduce router package and migrate a low-risk feature first.
4. Run CI/security/smoke; preserve API contracts.
5. Repeat by domain: student -> admin -> exams -> content -> integrations.
6. Consolidate redundant workflow orchestration after route migration is stable.
7. Remove dead modules only with evidence.
8. Add student-facing value after simplification: lesson-video links, then PWA Lite.
9. Keep admin RBAC deferred until multiple admin users are actually required.
10. EDU-001/EDU-003 remain a separate content-acceptance phase.

## Acceptance criteria

- No route disappears or changes authentication semantics.
- Anonymous admin APIs remain denied.
- Student session behavior remains unchanged.
- Production health/readiness remain green.
- Content intake remains locked.
- CI/security/smoke stay green.
- `index.py` import-side-effect list shrinks progressively.
- Workflow count is reduced without losing deploy/rollback safety.
