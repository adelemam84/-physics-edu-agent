# Science Education Platform v1.8.0 — Release Candidate

## Focus
v1.8.0 turns Smart Science Lesson Studio into a source-preserving, multi-model workflow for converting handwritten science teaching notes into reviewed educational material and professional PDF output.

## Supported subjects
- Physics
- Chemistry
- Preparatory / General Science

## Source policy
- Teacher handwriting / uploaded lesson source remains the authoring source.
- Scientific reference PDFs are validation and curriculum-context sources only.
- No AI provider may silently overwrite scientific content.
- Any unresolved OCR, notation, diagram or required reference-review issue blocks final approval.
- Teacher approval remains the final publication gate.

## Handwriting and OCR
- Multi-image/PDF lesson intake.
- Original bytes preserved.
- OCR-safe preprocessing derivative: EXIF orientation, resize, grayscale, autocontrast, mild sharpening.
- Manual crop, rotation and perspective correction to a derivative only.
- Gemini multimodal OCR.
- Optional Mathpix STEM OCR.
- Dual OCR consensus and confidence bands.
- Scientific symbols, operators, coefficients, units and reaction arrows receive stricter conflict handling.

## Lesson structuring
- Grade- and subject-aware organization.
- Objectives, sections, key terms, equations/rules, diagrams, warnings and summary.
- Source provenance per transformed section.
- Smart Expansion suggestions remain advisory until explicit teacher approval.
- Teacher Style Profile.
- Teacher, student-simple and quick-revision editions.

## Scientific Reference Library
- Upload one or more reference PDFs per subject/grade/year.
- Text PDFs are indexed page by page.
- Scanned PDFs can be OCRed in small Gemini batches while preserving page numbers.
- Reference context ranks relevant pages for each lesson.
- Scientific Reference Review compares the current lesson only against selected reference pages.
- Findings retain reference document and page evidence.
- `not_covered` is not treated as automatically incorrect.
- Optional strict gate via `LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW=true`.

## Curriculum Map from references
- Builds a page-grounded hierarchy: units -> lessons -> topics.
- Each topic retains source page numbers.
- Pages that cannot be mapped confidently remain in `unmapped_pages`.
- No general-knowledge lesson names or topics may be invented.
- Map freshness is tied to a hash of current extracted reference pages.

## Scientific Diagram Engine
Deterministic base renderers:
- simple circuits
- graphs/axes
- vectors
- process diagrams
- classifications
- cycles
- food chains
- atom shells
- anatomy blocks
- optical-ray shells
- apparatus/comparison shells

Advanced review-required renderers:
- resistor networks
- mixed series/parallel circuits
- magnetic field around a conductor
- solenoid field shell
- molecule/bond structure shell
- chemistry lab preparation setup

All relationship-sensitive diagrams remain teacher-review-required even when deterministic SVG is available.

## Professional PDF
- Multi-page A4 output.
- Mobile reading preset.
- Automatic contents section for longer lessons.
- Page numbering and document header stamp.
- Separate presentation behavior for teacher/student/revision modes.
- Visual callouts for definition, law, example, warning/note and experiment sections.
- Equation cards and embedded deterministic SVG diagrams.
- Final export protected by quality gate.

## Multi-model architecture
- Gemini: handwriting/page understanding, organization, scanned-reference OCR, curriculum map, reference alignment.
- Mathpix: optional specialist STEM OCR.
- OpenAI GPT-5.6 Sol: optional independent second reviewer; advisory only.
- Deterministic code: OCR comparison, diagram rendering, notation classification, integrity hashes, PDF composition and publication gates.

## Admin surfaces
- `/admin/lesson-studio`
- `/admin/lesson-studio/review`
- `/admin/lesson-studio/source-editor`
- `/admin/lesson-studio/workspace`
- `/admin/lesson-studio/tools`
- `/admin/lesson-studio/references`
- `/admin/lesson-studio/reference-workspace`
- `/admin/lesson-studio/acceptance`
- `/admin/lesson-studio/release-readiness`
- `/admin/completion-audit`

## Important production configuration
Already supported:
- `GEMINI_API_KEY`
- `LESSON_STUDIO_GEMINI_MODEL`
- `MATHPIX_APP_ID`
- `MATHPIX_APP_KEY`
- `OPENAI_API_KEY`
- `LESSON_STUDIO_REVIEW_MODEL`
- `LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW`

Secrets must be set in deployment environment variables and never committed.

## Release gate
Before production promotion:
1. GitHub CI must be green on the exact release commit.
2. Vercel build-rate-limit must be cleared.
3. Deploy latest `main` once.
4. Verify `/health` reports `1.8.0`.
5. Verify Lesson Studio admin routes load after authentication.
6. Run a real handwritten lesson acceptance test.
7. Upload one real scientific reference PDF and verify page extraction/OCR.
8. Build its curriculum map and verify page grounding.
9. Run reference alignment against the lesson.
10. Export A4 and mobile PDF and visually inspect diagrams, Arabic layout and page numbering.

## Current deployment status
v1.8.0 is deployed to Vercel production and the automated deployment gate is operational.

### Automated production verification — 2026-09-07
- Vercel build-rate-limit cleared and Git deployments are building again.
- GitHub CI passed on the production release line.
- Production deployment completed successfully.
- `/health` returned HTTP 200 with `version: 1.8.0`.
- `/api/next-release/status` returned HTTP 200 with `version: 1.8.0`.
- `/api/research-engine/status` returned HTTP 200 with Gemini configured and the orchestrator active.
- A Vercel-entrypoint import regression test is now part of the `unittest` CI suite.
- `/admin/lesson-studio/acceptance` now provides a single acceptance gate for runtime, reference ingestion, curriculum mapping, handwritten lesson processing, OCR review, reference review, teacher approval, and final PDF export.

### Completion audit
- Acceptance now requires fresh curriculum maps, fresh scientific-reference review evidence, and a final PDF generated from the current content hash.
- `/admin/completion-audit` separates remaining code/runtime defects from external-source and human-review work.

### Acceptance work that still requires real source material / authenticated teacher review
- Verify Lesson Studio admin routes in an authenticated teacher session.
- Run a real handwritten lesson through the full workflow.
- Upload a real scientific reference PDF and verify page extraction/OCR.
- Build and inspect its source-grounded curriculum map.
- Run reference alignment against the handwritten lesson.
- Export A4 and mobile PDFs and visually inspect Arabic layout, diagrams and page numbering.
