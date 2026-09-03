# Science Education Platform — Execution Blueprint

## Product direction
The project is no longer a physics-only tool. It is a multi-subject science education platform for Physics, Chemistry, and Preparatory Science, with source-grounded assessment, student analytics, parent communication, and teacher operations.

## Non-negotiable content rule
Scientific questions, accepted answers, source solutions, figures, and diagrams used for assessment must remain traceable to approved source material. AI may classify, organize, summarize analytics, and assist workflow, but it must not silently replace approved scientific source content.

## Academic hierarchy
Stage → Grade → Academic Year / Curriculum Version → Term → Subject → Unit → Chapter / Lesson → Concept → Question.

## Core question metadata
Every production question should ultimately support:
- subject
- grade
- curriculum version
- term
- unit
- lesson
- concept
- source document + page
- source asset / crop
- exact question text
- question type
- skill / cognitive demand
- difficulty
- accepted answer
- source solution
- diagram / experiment linkage
- approval state
- usage analytics

## Execution phases

### Phase 1 — Multi-subject foundation
1. Add subjects: Physics, Chemistry, Science.
2. Add grade levels and curriculum versions.
3. Add terms, units, and concepts.
4. Link lessons, documents, questions, and quizzes to the academic hierarchy.
5. Preserve backward compatibility with the existing physics data.
6. Add curriculum coverage queries.
7. Rename internal product language from Physics-only to Science Education Platform where safe.

### Phase 2 — Professional question bank
8. Add skill/cognitive classification: recall, understanding, direct application, multi-step application, inference, graph interpretation, experiment interpretation, comparison, reasoning.
9. Add rich scientific content metadata for diagrams, equations, and experiments.
10. Add duplicate / near-duplicate review.
11. Add question quality analytics: usage count, success rate, average response time, empirical difficulty, discrimination proxy.
12. Add teacher review flags for suspicious questions.

### Phase 3 — Assessment engine
13. Balanced exam blueprints by subject, unit, lesson, skill, and difficulty.
14. A/B/C equivalent exam versions.
15. Printable student version + separate answer key.
16. Homework assignments with deadlines and completion state.
17. Live quiz mode.
18. QR launch links.
19. Exam analytics and item analysis.

### Phase 4 — Student intelligence
20. Student knowledge map by concept.
21. Error notebook.
22. Error-type classification.
23. Adaptive practice using approved questions only.
24. Spaced revision queue.
25. Practice mode and exam mode separation.
26. Progress timeline.
27. Strength / weakness reports.

### Phase 5 — Teacher operations
28. Classes / groups.
29. Assign quizzes and homework to groups.
30. Curriculum coverage dashboard.
31. Alerts for weak concepts, declining students, abnormal question failure rates.
32. Role-based access: Admin, Teacher, Assistant, Student, Parent.

### Phase 6 — Parent experience
33. Parent WhatsApp result notification.
34. Low-score alert.
35. Weekly summary.
36. Parent portal.
37. Missing-homework notifications.
38. Trend, strongest lesson, weakest lesson, and sustained-decline alerts.

### Phase 7 — Scientific rendering
39. Equation and symbol rendering.
40. Physics diagrams.
41. Chemistry formulas, apparatus, reactions, ions, states of matter.
42. Preparatory science diagrams and experiments.
43. Experiment entities: apparatus, steps, observation, conclusion, source figure.

### Phase 8 — Engagement and reporting
44. Controlled gamification: points, badges, streaks.
45. Group ranking with privacy-safe display options.
46. PDF reports for students, groups, exams, answer sheets, and item analysis.
47. Teacher-in-the-loop marking for open responses.

## Architecture principles
- Source first.
- Multi-subject by design.
- Mobile-first admin and student interfaces.
- No final question approval without valid source page and asset.
- No published quiz with missing accepted answers.
- Parent notifications require opt-in.
- Auditable status transitions.
- Backward-compatible schema migrations.
- New features should use explicit foreign keys and indexes.
- AI-generated classifications are suggestions until confirmed where academically material.

## Immediate implementation order
1. Multi-subject schema.
2. Seed Physics, Chemistry, Science plus preparatory grades.
3. Academic taxonomy APIs and admin selectors.
4. Update question workflow and bank filters.
5. Curriculum coverage dashboard.
6. Skill taxonomy and question analytics.
7. Balanced assessment blueprints.
8. Groups, homework, portals, adaptive revision, scientific renderers, and advanced reporting.
