# Lesson Studio — External Artifact Audit Registry

## Purpose
Every creative artifact produced by Canva, Google Slides, or Gemini Notebook Enterprise is bound to the exact Lesson Studio content hash that generated it.

## Data model
`science_lesson_external_artifacts` records:
- lesson job id
- provider
- SHA-256 source/content hash
- creation status
- external resource id/url when available
- secret-free provider metadata
- failure message when creation fails
- creation timestamp

## APIs
- `GET /api/admin/lesson-studio/jobs/{job_id}/external-artifacts`
- `POST /api/admin/lesson-studio/jobs/{job_id}/external-artifacts/{provider}`

Supported provider ids:
- `canva`
- `google_slides`
- `gemini_notebook_enterprise`

## Freshness rule
Artifact freshness is calculated against the current transcript + structured lesson hash. A successful external artifact remains in audit history after a lesson edit, but becomes `fresh_for_current_content=false` and must never be represented as the current visual/export artifact.

## Security and scientific integrity
- OAuth/access/refresh tokens are never stored in artifact metadata.
- Provider metadata is intentionally whitelisted.
- A failed external integration is recorded for diagnostics but does not change lesson approval state.
- External artifact creation never approves scientific content.
- Internal A4/mobile exports remain independent of external integration availability.
