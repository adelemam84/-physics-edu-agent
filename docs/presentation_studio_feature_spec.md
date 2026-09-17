# Lesson Presentation Studio — Feature Specification

## Purpose

Convert approved/source-grounded Lesson Pack content into teacher-ready presentations without opening the official Content Ingestion pipeline or writing to the Official Question Bank.

The system is **not** a prompt library. The 20 source cards are normalized into reusable product capabilities, presentation modes, and quality contracts.

## Non-negotiable policies

- Presentation generation consumes an existing Lesson Pack only.
- Every factual slide item must retain `source_refs` from the Lesson Pack.
- Generated practice remains `official_question_bank=false` and `question_bank_eligible=false`.
- No presentation action enables `CONTENT_INGESTION_ENABLED`.
- Student editions must never expose answers, explanations, or teacher speaker notes.
- Teacher editions may include answers, explanations, facilitation guidance, and speaker notes.
- Source visuals remain source visuals only when they originate from the source and were teacher-approved.
- AI/generated visuals must be explicitly labeled as generated and may never masquerade as original source images.
- Any content-affecting edit invalidates prior presentation approval and stale exports.
- Final export requires presentation preflight + teacher approval.

## 20 cards → product specifications

| # | Card intent | Product specification | Engine capability |
|---|---|---|---|
| 1 | Professional presentation | Generate a complete source-grounded deck with concise summary and key points. | `professional_overview` |
| 2 | Intro + practical activity | Add opening hook, learning path, and one practical/classroom activity. | `intro_activity` |
| 3 | Student-level educational deck | Adapt vocabulary, density, examples, and scaffolding to the selected grade/audience. | `student_teaching` |
| 4 | Attractive professional design | Apply reusable academic theme/layout presets without changing scientific meaning. | `visual_design` |
| 5 | Benefits/outcomes | Build outcome/impact slides only when supported by the Lesson Pack source. | `benefits_outcomes` |
| 6 | Steps/process | Convert source-supported processes into ordered step/sequence slides. | `process_steps` |
| 7 | Notes → presentation + mind map | Convert structured Lesson Pack notes into an outline and concept-map specification. | `notes_outline_map` |
| 8 | Summarize long PDF/article | Summarize the current Lesson Pack source into a compact deck; does not open official ingestion. | `source_summary` |
| 9 | Interactive activities | Add source-grounded checkpoints, classroom prompts, and non-official practice activities. | `interactive_class` |
| 10 | Audio-driven presentation | Reserved input adapter for teacher-owned audio/transcript; disabled until a separate reviewed audio pipeline exists. | `audio_adapter_reserved` |
| 11 | Images and diagrams | Reuse approved source visuals and emit generated-diagram specs separately/labeled. | `visual_assets` |
| 12 | Storytelling | Re-sequence supported concepts into hook → problem → idea → law → application → recap. | `storytelling` |
| 13 | Learning objectives → interactive assessment | Map each learning objective to slides and one or more non-official checkpoints. | `objective_assessment` |
| 14 | Multilingual | Arabic, English, or bilingual rendering while preserving the same source-grounded semantic units. | `bilingual` |
| 15 | Graphic symbols/logic | Generate concept-map, flow, relationship, comparison, cause/effect, and formula-relation diagram specs. | `smart_diagrams` |
| 16 | Professional tables | Convert supported comparisons/variables/values into structured table specs. | `smart_tables` |
| 17 | Key-point summary | Produce a short revision deck from summary, laws, mistakes, and quick revision. | `quick_revision` |
| 18 | Text → slides | Convert Lesson Pack textual sections into slide-sized semantic units. | `text_to_slides` |
| 19 | Speaker notes | Generate teacher-only notes, facilitation cues, common mistakes, and solution guidance. | `speaker_notes` |
| 20 | Professional branded design | Apply teacher/school/center identity and consistent academic deck presets. | `branding_themes` |

## Consolidated engines

The 20 capabilities are implemented through eight shared engines rather than 20 disconnected prompt buttons:

1. **Blueprint Engine** — deck outline, slide ordering, duration/length, audience.
2. **Mode Engine** — teaching, exam revision, quick revision, storytelling, process, interactive.
3. **Assessment Engine** — objective mapping, checkpoints, non-official questions.
4. **Visual Intelligence Engine** — approved source visuals, diagram specs, charts/tables.
5. **Language Engine** — Arabic / English / bilingual semantic rendering.
6. **Edition Engine** — Student vs Teacher, answers, explanations, speaker notes.
7. **Source Grounding Engine** — provenance and source reference enforcement.
8. **Quality & Release Engine** — preview, preflight, approval invalidation, immutable exports.

## Presentation request schema

```json
{
  "mode": "lesson_explanation",
  "audience": "student",
  "language": "ar",
  "length": "medium",
  "theme": "clean_academic",
  "include": {
    "examples": true,
    "laws": true,
    "visuals": true,
    "tables": true,
    "activities": true,
    "checkpoints": true,
    "speaker_notes": false
  }
}
```

Supported modes:

- `lesson_explanation`
- `exam_revision`
- `concept_summary`
- `quick_revision`
- `storytelling`
- `interactive_class`
- `process_steps`
- `question_driven`

Supported audience/edition concepts:

- `student`
- `teacher`
- `classroom`

Supported language profiles:

- `ar`
- `en`
- `bilingual`

Supported length presets:

- `short` (6–8 slides target)
- `medium` (10–15 slides target)
- `full` (15–25 slides target)

## Blueprint contract

Each blueprint contains:

- immutable `deck_id`
- `source_lesson_pack_id`
- mode/audience/language/theme/length
- ordered slides
- each slide has `slide_id`, `kind`, `title`, `content_blocks`, `source_refs`
- optional `visual_specs`, `table_specs`, `activity`, `checkpoint`
- teacher-only `speaker_notes`
- `objective_ids` linking slides/checkpoints to learning objectives
- `generated_content_policy`
- `approval_state`
- `revision`

## Default slide patterns

### Lesson explanation

Cover → objectives → hook → concepts → laws → worked example → visual/application → practice checkpoint → common mistakes → recap.

### Exam revision

Cover → exam focus → laws → high-yield concepts → worked examples → common traps → question checkpoints → final revision.

### Quick revision

Cover → summary → laws → quick concepts → mistakes → rapid questions → final checklist.

### Storytelling

Hook/problem → observation → concept → law → worked application → challenge → recap.

### Interactive class

Hook → think/pair/share → concept → mini activity → checkpoint → explanation → second checkpoint → recap.

### Question driven

Question → pause/attempt → teacher-only solution → concept extraction → next question → final map.

## Student / Teacher separation

Student deck:

- no answers
- no explanations revealing solutions
- no speaker notes
- checkpoints remain unsolved

Teacher deck:

- same slide ordering and question IDs
- answers/explanations allowed in teacher-only blocks
- speaker notes allowed
- facilitation cues and common mistakes allowed

## Objective coverage

Every `learning_objective` is assigned a stable objective ID and must map to at least one explanatory slide or checkpoint. The preflight reports uncovered objectives as blockers for teaching modes.

## Visual policy

- Approved original source visuals: may be attached to slides with provenance.
- Generated diagrams: represented as specs and clearly labeled generated.
- No silent substitution of AI imagery for a source figure.
- Visual crop/approval state from Lesson Pack is preserved.

## Quality preflight

Blocking checks:

- valid deck schema
- source grounding on factual content blocks
- no official-bank policy drift
- no answer/speaker-note leakage in Student edition
- objective coverage for teaching modes
- valid slide count for selected length profile
- no duplicate slide IDs
- no empty required title/content
- source visual provenance preserved
- bilingual slides keep paired semantic units

Warnings:

- high text density
- too many bullets
- missing optional visual opportunity
- repeated title
- presentation length outside soft target

## Release phases

### Phase A — Foundation

- feature registry for all 20 cards
- request/blueprint schemas
- deterministic blueprint generation from Lesson Pack
- modes, language profiles, student/teacher edition rules
- source provenance + policy preflight

### Phase B — Teacher workspace

- blueprint preview/edit/reorder
- objective coverage map
- source-visual placement review
- speaker-note review
- approval invalidation on edit

### Phase C — Render/export

- presentation PDF preview/export
- Student/Teacher deck exports
- page/slide navigation
- presentation preflight before export

### Phase D — Advanced editable output

- PPTX export
- advanced charts/diagram renderer
- template/theme packs
- optional audio transcript adapter after separate security/content review

## Current scope guard

This feature does **not** upload official curriculum/question files, does **not** unlock official Content Ingestion, and does **not** write generated presentation questions to the Official Question Bank.
