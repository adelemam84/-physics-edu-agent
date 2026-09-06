# Physics Education AI Agent — v1.6.0 Multi-Engine Source Research

## Architecture
- Added a dedicated AI orchestration policy layer.
- The platform remains the workflow owner and final approval gate.
- Gemini Source Engine is a secondary advisory engine for PDF/source research.
- Question review and visual review always use exact source PDF pages.
- Broad source analysis may use Gemini File Search only when a trusted store is configured; otherwise it uses exact PDF pages.

## Guardrails
- Secondary AI cannot write directly to the question bank.
- Secondary AI cannot auto-approve questions or scientific content.
- Secondary AI cannot publish quizzes or exams.
- Question wording must remain verbatim when source questions are reviewed.
- Every response carries an integrity envelope with document/page provenance and advisory-only status.

## Admin/API
- `/admin/research-engine` provides the operator UI.
- `/api/research-engine/status` exposes safe public engine readiness.
- `/api/admin/research-engine/status` exposes detailed admin readiness.
- `/api/admin/research-engine/orchestrate` executes the routed source task.
- Existing `/api/admin/research-engine/query` is retained as a compatibility alias.

## Configuration
- `GEMINI_API_KEY` enables the secondary provider.
- `GEMINI_RESEARCH_MODEL` defaults to `gemini-3.8-flash`.
- `GEMINI_FILE_SEARCH_STORE` optionally enables persistent broad-source File Search.
- Inline PDF requests remain page- and byte-limited.

## Verification
- Added deterministic unit tests for orchestration routing and integrity guardrails.
- Production deployment depends on the Vercel build-rate limit clearing and on adding `GEMINI_API_KEY` for live Gemini calls.
