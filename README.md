# Physics Edu Agent

وكيل تعليمي للفيزياء للثانوية العامة المصرية، مبني على FastAPI + Neon PostgreSQL + Neon Object Storage + Vercel.

## مبادئ المحتوى

- مصدر الأسئلة: PDF فقط.
- السؤال يُحفظ `verbatim` كما ورد في المصدر.
- لا يتم توليد أسئلة داخل المسار الأساسي لبنك الأسئلة.
- كل سؤال يحتفظ باسم المصدر ورقم الصفحة.
- الأسئلة تبدأ غير معتمدة وتدخل قائمة مراجعة قبل استخدامها في الاختبارات.

## البنية

- FastAPI API وواجهات الإدارة.
- Neon PostgreSQL للبيانات والـmetadata.
- Neon Object Storage لملفات PDF وصور الصفحات.
- Vercel للنشر.

## متغيرات البيئة المطلوبة

راجع `.env.example`. لا تُرفع أي أسرار حقيقية إلى GitHub.

## التشغيل المحلي

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

ثم افتح:

- `/` لوحة المتابعة
- `/admin` لوحة الإدارة والمراجعة
- `/docs` توثيق API

## Production

يجب ضبط `DATABASE_URL` و`ADMIN_API_KEY` ومتغيرات Neon Object Storage في Vercel كـ Secrets.

### Deployment source

الفرع `main` في هذا المستودع هو المصدر الأساسي للنشر إلى مشروع Vercel `physics-edu-agent`. أي تعديل إنتاجي يجب أن يمر عبر GitHub بدل إعادة نشر حزمة قديمة يدويًا.


## v1.2 Production
- Source-aware tolerant grading for numeric/scientific answers.
- QA-clear text questions can be used without artificial image-asset requirements.
- Publication gate validates source grounding, approval, answer coverage and QA state.
- Diagnostic quizzes are generated only from approved source-backed questions.


## v1.3.0 Production
- Active third-secondary Physics curriculum context: 2026/2027.
- Current 2026 final-review PDF is registered as an image-only Google Drive source and is not silently OCR-invented.
- Page-level visual review queue separates question pages from covers, indexes and worked-solution pages.
- Student portal labels legacy 2020 diagnostics explicitly instead of presenting them as current curriculum.
- Cookie-authenticated admin mutations are same-origin protected; production responses include baseline security headers.
- Bulk visual-asset ZIP ingestion closes diagram QA only after durable images are stored and other quality gates pass.
- Current-source progress is available from `/api/current-curriculum/status`.


## AI Governance & Operations

- `/admin/ai-operations` is the secret-free model/task control plane.
- Gemini 3.8 Flash owns source-grounded PDF, multimodal and visual/OCR assistance.
- GPT-5.6 Sol is reserved for independent high-stakes scientific review.
- Mathpix is an optional second OCR verifier for STEM notation.
- Grading, adaptive question selection and validated scientific diagram rendering remain deterministic.
- No generative provider can write directly to the question bank, auto-approve scientific content, or publish it.
- Model names and review reasoning effort remain environment-configurable without code edits.
- Transient provider failures use bounded retries against the same provider only; model roles never fail over across scientific responsibilities.
- Provider resource creation/upload calls are not auto-replayed, avoiding duplicate durable resources.
- OpenAI scientific review requests set `store=false`; only privacy-preserving aggregate telemetry is persisted by this application.


## Lesson Pack Studio (v1.8.5)

- `/admin/lesson-pack-studio` accepts standalone lesson PDF or scan files without opening official curriculum ingestion.
- PDF files are rasterized page-by-page so OCR, review, and citations preserve exact source-page provenance.
- OCR runs incrementally per page to avoid long serverless requests on large scanned lessons.
- Gemini creates source-grounded explanations, examples, deterministic diagram specifications, and clearly labeled generated practice.
- Every generated practice question is explicitly barred from the official question bank and requires teacher review.
- GPT-5.6 Sol can perform the independent advisory scientific review before teacher approval.
- Final export is blocked until OCR review, page provenance validation, scientific review (when configured), and teacher approval are complete.
- Two final editions are available: Student PDF without answers and Teacher PDF with answers and explanations.
- `LESSON_PACK_INGESTION_ENABLED` controls this auxiliary workspace independently from `CONTENT_INGESTION_ENABLED`.
