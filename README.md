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
