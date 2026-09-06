# Physics Education AI Agent — v1.5.0 Advanced Learning Suite

## Seven professional learning upgrades

1. **Source-grounded tutor context**
   - Identifies the student's weakest lesson from real attempt data.
   - Uses only an approved `lesson_source_mappings` explanatory PDF range.
   - If no approved explanatory source exists, the tutor explicitly refuses to invent a replacement explanation.

2. **Personal study plan**
   - Builds a prioritized study plan from measured lesson mastery.
   - Targets the weakest lessons first, followed by approved adaptive practice.

3. **Spaced review queue**
   - Re-surfaces previously missed, approved source-backed questions.
   - Excludes questions with open QA notes.
   - Prioritizes repeated errors and recent mistakes.

4. **Mock exam recommendation**
   - Selects an available published quiz from the active curriculum.
   - Prefers unattempted assessments before repeated ones.

5. **Exam readiness score**
   - Combines recent assessment average, performance trend, and weak/developing lesson penalties.
   - Produces an interpretable readiness level rather than an opaque AI score.

6. **Smart progress report**
   - Returns current readiness, study priorities, review load, and generation timestamp in one report object.

7. **Achievements and motivation**
   - Awards deterministic badges from verified attempts and correct-answer counts.
   - Does not use generated academic content.

## New student endpoints

- `/student/learning-suite`
- `/api/student/learning-suite?student_code=...`
- `/api/student/review-queue?student_code=...`
- `/api/student/exam-readiness?student_code=...`

## Integrity guarantees

- Questions remain `approved_pdf_only`.
- Scientific explanation remains `approved_explanatory_pdf_only`.
- Generated questions remain disabled.
- Open-QA questions are excluded from review recommendations.

## Compatibility

The suite is additive and uses the existing production schema, attempts, approved questions, lesson mappings, quizzes and source governance. No existing API contract was removed or replaced.
