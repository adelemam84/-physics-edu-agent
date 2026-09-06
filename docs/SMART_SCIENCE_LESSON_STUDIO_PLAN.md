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
- Image preprocessing hooks: crop, rotate, contrast, perspective correction.
- Page ordering and source identifiers.

### Phase B — Dual OCR Verification
- Gemini multimodal transcription.
- Mathpix STEM OCR when configured.
- Consensus engine compares outputs line-by-line/block-by-block.
- Confidence map: green/high, yellow/review, red/uncertain.
- Conflict objects are reviewable and never auto-resolved silently.
- Equations, units and chemical notation receive stricter comparison rules.

### Phase C — Smart structuring
- Subject and grade aware organization.
- Headings, objectives, explanations, examples, equations, warnings, key terms, summary.
- Preserve-source mode and optional enhancement mode kept separate.
- Add provenance/source references to every organized section.

### Phase D — Scientific Diagram Engine
Deterministic SVG/programmatic renderers first.

Physics:
- simple circuits and component symbols
- resistor networks
- vectors/arrows
- graphs/axes
- rays, mirrors and lenses
- magnetic field direction diagrams
- experimental apparatus schematics

Chemistry:
- reaction flow diagrams
- apparatus layouts
- atom/electron-shell schematics
- bond/molecule schematics where deterministic description is sufficient
- tables/comparisons
- balanced-equation presentation

Preparatory Science:
- process/cycle diagrams
- classification trees
- anatomy block diagrams
- laboratory setups
- ecosystems/food chains
- system-component diagrams

Rule: generative imagery may be used only for illustrative/decorative visuals that do not encode precise scientific facts unless reviewed.

### Phase E — Smart Diagram Detection
- Detect where a diagram improves comprehension.
- Produce a typed diagram specification, not a freeform image request.
- Route each spec to the correct deterministic renderer or a review-required fallback.

### Phase F — Formula and Chemistry notation engine
- Normalize equations without changing meaning.
- Preserve ambiguous symbols for review.
- Render math/physics equations professionally.
- Render chemical equations, charges, subscripts and states cleanly.

### Phase G — Original vs Organized review UI
- Side-by-side source and organized content.
- Clicking a paragraph reveals its source page/image reference.
- Confidence badges and conflict filters.
- Approve/edit/reject at block level.
- Teacher approval gate before final PDF.

### Phase H — Smart Expansion (optional)
- Suggestions such as: add example, add diagram, define term, add common mistake.
- Never merged automatically into source-derived content.
- Distinct provenance: teacher_source vs ai_suggestion vs teacher_approved_addition.

### Phase I — Grade-aware explanation
- Adjust wording depth for grade/level while preserving teacher meaning.
- Keep source-derived facts unchanged.
- Allow separate student edition and teacher edition from same source project.

### Phase J — Teacher Style Profile
- Reusable style profile: heading hierarchy, callout types, example layout, summary style, preferred vocabulary and visual density.
- Style preferences must not alter scientific meaning.

### Phase K — Professional PDF composition
- Arabic RTL typography.
- cover/title page
- headers/footers/page numbers
- consistent callouts for law/definition/example/warning
- equation blocks
- embedded SVG diagrams
- table of contents for long lessons
- print-friendly A4 and mobile-reading variants
- teacher/student/revision editions

### Phase L — Multi-model quality architecture
Primary roles:
- Gemini: multimodal page understanding, layout, handwriting context, organization.
- Mathpix: optional specialist STEM OCR for handwriting, equations and chemistry.
- OpenAI reviewer: optional second scientific/structural review and conflict adjudication support; never auto-publishes.
- Deterministic code: scientific diagrams, rendering, validation and publication gates.

### Phase M — Quality gates
- source preserved
- transcript available
- unresolved OCR conflicts count
- unclear segments count
- scientific review flags count
- diagram specs validated
- all generated scientific diagrams deterministic or explicitly reviewed
- final teacher approval
- PDF preflight

## Quality targets
- zero silent scientific corrections
- zero hidden unresolved OCR conflicts
- 100% source provenance for transformed sections
- deterministic rendering for precise scientific diagrams whenever renderer exists
- mobile-first admin workflow
- export reproducibility from saved structured JSON

## Current implementation status
- Core Smart Science Lesson Studio: implemented.
- Gemini OCR/organization: implemented.
- Optional Mathpix configuration: scaffolded.
- Source storage and PDF export baseline: implemented.
- Dual OCR consensus: in implementation.
- Scientific Diagram Engine: in implementation.
- Confidence map / review UX / smart expansion / style profile: pending in roadmap and will be implemented sequentially.
