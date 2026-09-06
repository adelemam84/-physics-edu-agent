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
- Manual crop / perspective correction remains an enhancement item; automatic perspective guessing is intentionally not used because it can distort scientific figures.

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
- vectors/arrows
- graph axes
- process/flow diagrams
- classification trees
- cycle diagrams
- food-chain shells
- anatomy block schematics
- atom/electron-shell schematics
- ray-diagram shells
- comparison/apparatus safe layout shells

Safety rule:
- relationship-sensitive scientific diagrams remain teacher-review-required even when a deterministic SVG can be rendered.
- generative imagery may be used only for illustrative/decorative visuals that do not encode precise scientific facts unless explicitly reviewed.

Planned renderer depth expansions:
- complex resistor networks
- magnetic field diagrams
- precise optical ray paths after validated geometry inputs
- chemistry bond/molecule renderers
- more laboratory apparatus components

### Phase E — Smart Diagram Detection
- Detect where a diagram improves comprehension.
- Produce a typed diagram specification, not a freeform image request.
- Conservative intent router recognizes circuit, graph, process, classification, cycle, food-chain, atom-shell, anatomy, apparatus, vector and optical-ray intents.
- Unknown intents stay unsupported/review-required instead of being guessed.

### Phase F — Formula and Chemistry notation engine
- Classify equations without semantic rewriting.
- Preserve ambiguous symbols for review.
- Detect physics/math equations, quantities with units, chemical formula candidates and chemical reactions including stoichiometric coefficients.
- Teacher can approve/correct a notation item explicitly; the original expression is retained in review metadata.
- Further typography work for subscripts, charges and states can be layered into the PDF renderer without altering source text.

### Phase G — Original vs Organized review UI
- Unified mobile-responsive workspace at `/admin/lesson-studio/workspace`.
- Shows original source image beside OCR and organized content.
- Primary and alternate OCR are visible when dual OCR is available.
- Confidence badges and conflict details.
- Teacher can approve OCR, resolve uncertain items, approve notation and approve deterministic diagrams.
- Quality gate and final export are visible in the same workspace.

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
- Arabic RTL document structure.
- Cover/title block.
- Objectives and section hierarchy.
- Source provenance under organized sections.
- Equation blocks.
- Embedded deterministic SVG diagrams where available.
- Teacher warnings in teacher edition.
- Summary and footer.
- Long lessons flow across pages rather than being compressed onto one page.
- Final PDF route is protected by the strict quality gate.

Future composition upgrades:
- richer Arabic font handling/typographic tuning
- generated table of contents for long lessons
- dedicated mobile-reading PDF preset in addition to A4

### Phase L — Multi-model quality architecture
Roles implemented/scaffolded:
- Gemini: multimodal page understanding, handwriting transcription context and lesson organization.
- Mathpix: optional specialist STEM OCR for handwriting/equations/chemistry; activates when credentials are configured.
- OpenAI GPT-5.6 Sol: optional independent second reviewer via Responses API; advisory only, cannot modify, approve or publish.
- Deterministic code: OCR conflict comparison, diagram rendering, notation classification, integrity hashes, PDF rendering and publication gates.

Second-review integrity:
- review is bound to SHA-256 of transcript + structured lesson.
- any later content change makes the prior review stale automatically.
- when OpenAI reviewer is configured, a fresh clear review becomes part of the pre-approval quality gate.

### Phase M — Quality gates
Implemented checks:
- source preserved
- OCR review clear
- structured content ready
- uncertain items clear
- scientific notation review clear
- diagram review clear
- section provenance present
- fresh independent second review when reviewer provider is configured
- final teacher approval
- final PDF export blocked until all applicable gates pass

## Admin surfaces
- `/admin/lesson-studio` — create/upload a lesson project.
- `/admin/lesson-studio/review` — focused OCR review.
- `/admin/lesson-studio/workspace` — unified Original vs Organized review, diagrams and final quality.
- `/admin/lesson-studio/tools` — teacher style, Smart Expansion, independent reviewer and grade/output editions.

## Provider configuration
Already supported by code:
- `GEMINI_API_KEY`
- `LESSON_STUDIO_GEMINI_MODEL`
- `MATHPIX_APP_ID`
- `MATHPIX_APP_KEY`
- `OPENAI_API_KEY`
- `LESSON_STUDIO_REVIEW_MODEL`
- image preprocessing controls.

Secrets must be configured through production environment variables, never committed to the repository.

## Quality targets
- zero silent scientific corrections
- zero hidden unresolved OCR conflicts
- 100% source provenance for transformed sections before final approval
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
- OCR image preprocessing derivative.
- Source vs OCR review UI.
- Unified Original vs Organized workspace.
- Scientific Diagram Engine with multiple deterministic SVG primitives.
- Smart Diagram intent routing.
- Non-destructive science notation classification and teacher approval path.
- Smart Expansion suggestions with explicit teacher approval.
- Grade/output-specific editions.
- Teacher Style Profile.
- Independent OpenAI second reviewer architecture with content-hash freshness protection.
- Strict quality/teacher approval gate.
- Professional multi-page A4 PDF renderer.
- Deterministic CI test coverage for OCR, diagrams, notation, integrity, image preprocessing and PDF rendering.

### External activation still required
- Mathpix dual OCR becomes active only after `MATHPIX_APP_ID` + `MATHPIX_APP_KEY` are configured in production.
- OpenAI second reviewer becomes active only after `OPENAI_API_KEY` is configured in production.
- Latest module is not considered production-live until Vercel can build/deploy the accumulated `main` branch and live acceptance passes.

### Remaining enhancement depth (not blockers for the first usable release)
- manual crop/perspective correction UI
- deeper physics/chemistry deterministic diagram libraries
- table of contents and dedicated mobile-PDF preset
- broader subject expansion to Biology/Mathematics when desired
