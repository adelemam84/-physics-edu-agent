# Lesson Studio — External Creative Integrations Control Center

## Phase X status
Implemented on the v1.8 production line.

## Goal
Provide one admin surface for optional creative integrations without allowing an external provider to become a scientific source, approval authority, or release blocker for internal Lesson Studio exports.

## Admin surface
- `/admin/lesson-studio/integrations`
- API: `/api/admin/lesson-studio/integrations/summary`

## Canva
The production contract uses the configured Canva source (master design by default, optional Brand Template override) and exposes:
- client configuration readiness
- OAuth authorization state
- requested/granted/missing scope readiness
- stable production callback status
- expected master autofill field count
- optional live dataset diagnostics
- source-grounded Visual Summary creation for a selected Lesson Studio job

Master design contract:
- design id: `DAHUkN3i5p4`
- title: `Physics Edu Agent — Light Scientific Autofill Master`
- 38 source-grounded text fields

Fields unsupported by the uploaded lesson remain blank. The Canva layer must never invent examples, exam tips, misconceptions, answers, equations, or scientific facts.

## Google Slides
The same control center exposes the existing PPTX-to-Google-Slides integration when its service-account and destination-folder configuration is present.

## Gemini Notebook Enterprise
The same control center exposes the existing source-upload Notebook workflow only when the required Google project configuration is present.

## Safety / integrity rules
1. External integrations are optional presentation layers.
2. Source-grounded payloads only.
3. External provider failure does not block A4/mobile internal exports.
4. No OAuth token, refresh token, client secret, or service-account secret is returned to the browser.
5. Canva Autofill cannot approve scientific content.
6. Teacher approval and Lesson Studio quality gates remain authoritative.
7. Reauthorization is explicit when Canva scopes change; stale grants are not silently treated as sufficient.

## Verification
CI must import the Vercel entrypoint and assert registration of both the control-center page and its protected summary API before production promotion.
