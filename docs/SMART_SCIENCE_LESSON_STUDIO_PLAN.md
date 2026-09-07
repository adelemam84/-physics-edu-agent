# Smart Science Lesson Studio — Master Implementation Plan

## Mission
حوّل الشرح المكتوب بخط اليد إلى مذكرة تعليمية احترافية قابلة للمراجعة والتصدير إلى PDF، مع الحفاظ على الأصل، ومنع التصحيح العلمي الصامت، ودعم الفيزياء والكيمياء والعلوم للمرحلة الإعدادية.

## Non-negotiable policies
1. Preserve the original upload and transcript.
2. Never silently correct scientific content.
3. Mark uncertainty explicitly instead of guessing.
4. AI-generated additions are suggestions only until approved.
5. Scientific diagrams that encode facts must be deterministic/programmatic when possible.
6. Every transformed block must retain provenance to its source page/image.
7. Teacher review remains the final publication gate.
8. A second-review result is valid only for the exact content hash it reviewed.
9. Scientific reference PDFs are validation/coverage context, not an automatic authoring source.
10. A reference finding may flag a contradiction or missing coverage, but never rewrites teacher content automatically.

## Product modes
- teacher_notes — مذكرة مدرس منظمة
- student_simple — شرح مبسط للطالب
- quick_revision — مراجعة سريعة

## Subjects
- Physics
- Chemistry
- General Science / Preparatory Science
- Extensible later: Biology, Mathematics

## Full roadmap

### Phase A — Source intake and preservation
- Mobile-first multi-image/PDF upload.
- Original source retention in object storage.
- OCR image derivative with EXIF orientation, conservative resize, grayscale, autocontrast and mild sharpening.
- Original bytes are never replaced by preprocessing.
- Page ordering and source identifiers.
- Manual crop, 90/180/270 rotation and four-point perspective correction implemented as a separate derivative workflow.
- Adjusted source can be re-OCRed while the original remains untouched.

### Phase B — Dual OCR Verification
- Gemini multimodal transcription.
- Mathpix STEM OCR when configured.
- Consensus engine compares outputs line-by-line/block-by-block.
- Confidence map: green/high, yellow/review, red/uncertain.
- Conflict objects are reviewable and never auto-resolved silently.
- Equations, units and chemical notation receive stricter comparison rules.
- A changed operator, denominator, coefficient or reaction arrow is a critical conflict.

### Phase C — Smart structuring
- Subject and grade aware organization.
- Headings, objectives, explanations, examples, equations, warnings, key terms, summary.
- Preserve-source mode and optional enhancement mode kept separate.
- Add provenance/source references to every organized section.

### Phase D — Scientific Diagram Engine
Deterministic SVG/programmatic renderers first.

Implemented renderer families:
- simple circuits and basic component symbols
- resistor-network review shells
- magnetic-field review shells
- vectors/arrows
- graph axes
- process/flow diagrams
- classification trees
- cycle diagrams
- food-chain shells
- anatomy block schematics
- atom/electron-shell schematics
- molecule/bond review shells
- ray-diagram shells
- comparison/apparatus safe layout shells

Safety rule:
- relationship-sensitive scientific diagrams remain teacher-review-required even when a deterministic SVG can be rendered.
- generative imagery may be used only for illustrative/decorative visuals that do not encode precise scientific facts unless explicitly reviewed.

Further renderer depth:
- validated arbitrary resistor topology from structured circuit specifications
- precise magnetic direction conventions from validated input
- precise optical ray paths after validated geometry inputs
- chemistry bond-order/charge geometry from explicit molecular specifications
- more laboratory apparatus components

### Phase E — Smart Diagram Detection
- Detect where a diagram improves comprehension.
- Produce a typed diagram specification, not a freeform image request.
- Conservative intent router recognizes circuit, resistor-network, magnetic-field, molecule/bond, graph, process, classification, cycle, food-chain, atom-shell, anatomy, apparatus, vector and optical-ray intents.
- Unknown intents stay unsupported/review-required instead of being guessed.

### Phase F — Formula and Chemistry notation engine
- Classify equations without semantic rewriting.
- Preserve ambiguous symbols for review.
- Detect physics/math equations, quantities with units, chemical formula candidates and chemical reactions including stoichiometric coefficients.
- Teacher can approve/correct a notation item explicitly; the original expression is retained in review metadata.
- Advanced PDF notation typography is implemented as presentation-only markup: explicit chemical subscripts, explicit charges, explicit matter states and explicit caret exponents, while preserving the raw source expression unchanged.

### Phase G — Original vs Organized review UI
- Unified mobile-responsive workspace at `/admin/lesson-studio/workspace`.
- Shows original source image beside OCR and organized content.
- Primary and alternate OCR are visible when dual OCR is available.
- Confidence badges and conflict details.
- Teacher can approve OCR, resolve uncertain items, approve notation and approve deterministic diagrams.
- Quality gate and final export are visible in the same workspace.
- Manual source correction UI at `/admin/lesson-studio/source-editor`.

### Phase H — Smart Expansion
- Suggestions such as: add example, add diagram, define term, add common mistake.
- Never merged automatically into source-derived content.
- Distinct provenance: teacher_source vs ai_suggestion vs teacher_approved_addition.
- Approving an AI suggestion invalidates any previous final approval / second review for safety.

### Phase I — Grade-aware explanation
- Separate editions can be generated from the reviewed transcript.
- Supported output modes: teacher notes, simplified student explanation, quick revision.
- Grade label can be changed per edition.
- Source-derived facts remain protected from silent scientific rewriting.

### Phase J — Teacher Style Profile
- Reusable profile implemented for heading hierarchy, example style, summary style, visual density, language tone, preferred callouts and custom notes.
- Style preferences are presentation/pedagogy settings only and must not alter scientific meaning.

### Phase K — Professional PDF composition
- Multi-page A4 flow using PyMuPDF Story.
- Dedicated mobile-reading PDF preset.
- Arabic RTL document structure.
- Cover/title block.
- Objectives and section hierarchy.
- Automatic contents section for longer lessons.
- Source provenance under organized sections.
- Equation blocks.
- Embedded deterministic SVG diagrams where available.
- Teacher warnings in teacher edition.
- Summary and footer.
- Page header + page numbering after rendering.
- Long lessons flow across pages rather than being compressed onto one page.
- Final PDF routes are protected by the strict quality gate.

Further composition upgrades:
- richer Arabic font handling/typographic tuning
- richer printed table-of-contents page-number mapping
- branded templates/themes without changing scientific content — implemented with Classic Academic, Modern Classroom and Exam Revision themes, configurable brand name/tagline, and identical scientific content across themes.

### Phase L — Multi-model quality architecture
Roles implemented/scaffolded:
- Gemini: multimodal page understanding, handwriting transcription context, lesson organization and scanned-reference page OCR.
- Mathpix: optional specialist STEM OCR for handwriting/equations/chemistry; activates when credentials are configured.
- OpenAI GPT-5.6 Sol: optional independent second reviewer via Responses API; advisory only, cannot modify, approve or publish.
- Deterministic code: OCR conflict comparison, reference-page matching, diagram rendering, notation classification, integrity hashes, PDF rendering and publication gates.

Second-review integrity:
- review is bound to SHA-256 of transcript + structured lesson.
- any later content change makes the prior review stale automatically.
- when OpenAI reviewer is configured, a fresh clear review becomes part of the pre-approval quality gate.

### Phase M — Scientific Reference Library
- Per-subject / per-grade reference PDFs.
- Admin surface: `/admin/lesson-studio/references`.
- Original reference PDF retained when object storage is configured.
- Native PDF text is extracted page-by-page and page numbers are preserved.
- Scanned/image-only pages are marked `ocr_required` or `partial_ocr` instead of being rejected.
- Scanned pages can be OCRed via Gemini in small serverless-safe batches of 1–5 pages.
- Reference context selects relevant pages with deterministic hybrid retrieval (BM25 + query coverage + phrase order + term density + adjacent-page continuity) before sending evidence to the AI reviewer; exact document/page provenance is preserved.
- Reference alignment review compares teacher transcript + organized lesson only against selected reference excerpts.
- Findings must retain reference document/page provenance.
- `not_covered` means the reference did not cover a statement; it is not automatically treated as scientifically wrong.
- Reference review is advisory by default and can be promoted to an export quality gate with `LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW=true`.

### Phase N — Quality gates
Implemented checks:
- source preserved
- OCR review clear
- structured content ready
- uncertain items clear
- scientific notation review clear
- diagram review clear
- section provenance present
- scientific reference alignment status (optional or required by configuration)
- fresh independent second review when reviewer provider is configured
- final teacher approval
- final PDF export blocked until all applicable gates pass

### Phase O — Version History & Audit Trail
- Immutable pre-change lesson snapshots with sequential version numbers and SHA-256 content hashes.
- Snapshots are created before structured-content edits, OCR transcript rebuilds and approved AI-suggestion merges.
- Version history is visible inside the unified Lesson Studio workspace.
- Restoring a prior version preserves original source uploads but invalidates teacher approval, independent review, scientific reference review, cached quality state and prior final PDF.
- Restored content must pass the full current quality gate again before export.

### Phase P — Lesson Diff & Change Review
- Read-only comparison between any saved version and the current lesson, or between two saved versions.
- Structured differences are grouped into transcript, sections, equations, diagrams, core fields and approved additions.
- Diff output shows before/after values without inferring whether a scientific change is correct.
- Comparison never approves, restores or mutates source files.
- Version history UI exposes a one-click compare-to-current view before restore decisions.

### Phase Q — Change Impact & Re-approval Matrix
- Deterministic mapping from lesson differences to the exact review gates that must be rerun.
- Transcript changes require OCR + notation + scientific reference + independent review before teacher approval.
- Equation changes require notation + scientific reference + independent review.
- Diagram changes require diagram + scientific reference + independent review.
- Section/approved-addition/science-sensitive field changes require scientific reference + independent review.
- Title-only changes require teacher approval and final PDF regeneration without unnecessarily forcing OCR/reference review.
- The workspace shows severity and required gates next to each version comparison; the matrix never infers scientific correctness.

### Phase R — Approval State Engine
- Gate state is persisted per lesson content hash, so historical approval state cannot be mistaken for the current version.
- Gates expose `complete`, `pending`, `blocked`, or `not_required` states.
- Current state covers OCR, notation, diagrams, scientific-reference review, independent review, teacher approval, and final PDF export.
- Final PDFs are bound to the exact content hash used to generate them; a stale PDF never counts as complete after a content change.
- The unified workspace displays the current gate state alongside the quality checks.

## Admin surfaces
- `/admin/lesson-studio` — create/upload a lesson project.
- `/admin/lesson-studio/review` — focused OCR review.
- `/admin/lesson-studio/workspace` — unified Original vs Organized review, diagrams and final quality.
- `/admin/lesson-studio/source-editor` — crop/rotate/perspective correction derivative and re-OCR.
- `/admin/lesson-studio/tools` — teacher style, Smart Expansion, independent reviewer and grade/output editions.
- `/admin/lesson-studio/references` — per-subject scientific reference library + scanned-PDF OCR controls.

## Provider configuration
Already supported by code:
- `GEMINI_API_KEY`
- `LESSON_STUDIO_GEMINI_MODEL`
- `MATHPIX_APP_ID`
- `MATHPIX_APP_KEY`
- `OPENAI_API_KEY`
- `LESSON_STUDIO_REVIEW_MODEL`
- `LESSON_STUDIO_REQUIRE_REFERENCE_REVIEW`
- image preprocessing controls.

Secrets must be configured through production environment variables, never committed to the repository.

## Quality targets
- zero silent scientific corrections
- zero hidden unresolved OCR conflicts
- 100% source provenance for transformed sections before final approval
- page-level provenance for scientific reference findings
- deterministic rendering for precise scientific diagrams whenever a validated renderer exists
- mobile-first admin workflow
- export reproducibility from saved structured JSON
- stale external AI reviews automatically rejected after content changes

## Current implementation status — 2026-09-07
### Implemented
- Core Smart Science Lesson Studio.
- Physics, Chemistry and Preparatory Science scopes.
- Multi-image/PDF source upload and original preservation.
- Gemini handwriting OCR and organization.
- Optional Mathpix STEM OCR integration.
- Dual OCR consensus + confidence bands + critical scientific-symbol conflicts.
- Automatic OCR image preprocessing derivative.
- Manual crop/rotation/perspective correction derivative + re-OCR flow.
- Source vs OCR review UI.
- Unified Original vs Organized workspace.
- Scientific Diagram Engine with deterministic SVG primitives and advanced review-required shells.
- Smart Diagram intent routing.
- Non-destructive science notation classification and teacher approval path.
- Smart Expansion suggestions with explicit teacher approval.
- Grade/output-specific editions.
- Teacher Style Profile.
- Independent OpenAI second reviewer architecture with content-hash freshness protection.
- Scientific Reference Library and page-level reference alignment review.
- Native-text and scanned-reference ingestion paths.
- Strict configurable quality/teacher approval gate.
- Professional multi-page A4 + mobile PDF renderer with TOC and page numbering.
- Application version advanced to 1.8.0 for this accumulated release line.
- Deterministic CI test coverage for OCR, diagrams, notation, integrity, image preprocessing, reference matching and PDF rendering.

### External activation still required
- Mathpix dual OCR becomes active only after `MATHPIX_APP_ID` + `MATHPIX_APP_KEY` are configured in production.
- OpenAI second reviewer becomes active only after `OPENAI_API_KEY` is configured in production.
- Scientific reference alignment can already use Gemini once the new build is deployed and the Gemini key is present.
- Latest modules are not considered production-live until Vercel can build/deploy the accumulated `main` branch and live acceptance passes.

### Remaining enhancement depth (not blockers for the first usable release)
- richer Arabic typography and branded lesson templates
- more precise parameterized circuit/optics/molecular renderers
- optional Biology/Mathematics subject expansion when desired
- optional embeddings/File Search can later be layered on top of deterministic hybrid retrieval, but only if exact page provenance and source-only evidence constraints remain enforced
