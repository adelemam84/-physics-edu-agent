# Physics Education AI Agent — v1.2.1 Stable

## Production acceptance

- 94 questions from the real legacy-2020 physics source are registered.
- 75 source-backed questions are approved and usable.
- 19 genuinely diagram/graph-dependent questions remain deliberately isolated in QA until durable visual assets are attached.
- No critical QA issues remain.
- Six diagnostic exams are published: five chapter diagnostics plus one comprehensive diagnostic.
- Student quiz APIs have been smoke-tested in production.
- Numeric grading supports scientific notation, fractions, radicals, tolerance, multi-part answers, and qualitative anchors.
- Open QA notes automatically exclude questions from student quizzes and adaptive practice.
- Quiz publication requires source grounding, approval, answer coverage, academic mapping and QA-clear status.
- GitHub CI compiles all Python and runs deterministic grading tests on every main push and pull request.

- External/Google Drive question sources can now receive direct JPG/PNG/WEBP Question Asset uploads from the admin workflow.
- The lesson-source workflow is consolidated on the production `lesson_source_mappings` schema and reads only approved mappings.
- Three false-positive visual blockers were reviewed against the source and safely cleared; they are now approved text-self-sufficient questions.
