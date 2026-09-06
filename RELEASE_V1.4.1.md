# Physics Education AI Agent — v1.4.1 Corpus Expansion

## 2026/2027 production corpus
- Active source remains the 42-page `كتاب التفوق فيزياء | مراجعة نهائية 2026.pdf` corpus.
- 122 source-backed question candidates remain registered against exact source pages.
- Approved current-curriculum questions increased from 35 to 41.
- Open QA items decreased from 87 to 81; resolved QA items increased to 41.
- Six additional text-self-sufficient questions were manually transcribed from the source and scientifically reviewed:
  - three semiconductor/doping questions from source page 18;
  - three Coolidge-tube/X-ray questions from source page 27.
- Each newly approved question is academically mapped to its lesson/unit, concept, skill and difficulty.
- Visual-only candidates remain blocked until a durable question asset is available; no image-only question is silently invented or published as text.

## Student assessment expansion
- A second current-curriculum diagnostic was published: `اختبار 2026/2027 — الكهرباء والفيزياء الحديثة`.
- The new diagnostic contains 15 approved, source-linked, QA-clear, text-self-sufficient questions.
- Duration: 25 minutes.
- Attempts: 2, score policy: highest.
- Production now exposes 2 published quizzes for the active 2026/2027 curriculum.

## Production verification
`/api/current-curriculum/status` reports:
- `total_questions=122`
- `approved_questions=41`
- `qa_open=81`
- `qa_resolved=41`
- `published_quizzes=2`
- `status=partial_bank_ready`

## Integrity rule
The PDF source remains authoritative. Questions requiring a diagram, graph or source image stay unapproved until the visual asset is durably stored and linked.
