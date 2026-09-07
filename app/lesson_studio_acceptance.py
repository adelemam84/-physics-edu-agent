from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import _schema as lesson_schema, lesson_studio_status
from .science_reference_library import _schema as reference_schema
from .science_reference_curriculum_map import _map_schema
from .lesson_studio_reference_review import _reference_review_schema
from .lesson_studio_quality import _quality_schema


def _counts() -> dict:
    lesson_schema()
    reference_schema()
    _map_schema()
    _reference_review_schema()
    _quality_schema()
    with connect() as con:
        refs = con.execute("""SELECT
          count(*) FILTER (WHERE active=TRUE) active,
          count(*) FILTER (WHERE active=TRUE AND ingestion_status='ready') ingestion_ready,
          count(*) FILTER (WHERE active=TRUE AND curriculum_map IS NOT NULL) with_curriculum_map,
          count(*) FILTER (WHERE active=TRUE AND curriculum_map IS NOT NULL
            AND curriculum_map_source_hash IS NOT NULL) mapped
          FROM science_reference_documents""").fetchone()
        jobs = con.execute("""SELECT
          count(*) total,
          count(*) FILTER (WHERE structured_json IS NOT NULL) structured,
          count(*) FILTER (WHERE reference_review IS NOT NULL) reference_reviewed,
          count(*) FILTER (WHERE teacher_approved=TRUE) teacher_approved,
          count(*) FILTER (WHERE status='final_pdf_ready' AND pdf_object_key IS NOT NULL) final_pdf_ready
          FROM science_lesson_jobs""").fetchone()
        ocr = con.execute("""SELECT
          count(*) FILTER (WHERE requires_review=TRUE) unresolved,
          count(*) total
          FROM science_lesson_sources""").fetchone()
    return {
        'references': {k:int(refs[k] or 0) for k in ('active','ingestion_ready','with_curriculum_map','mapped')},
        'jobs': {k:int(jobs[k] or 0) for k in ('total','structured','reference_reviewed','teacher_approved','final_pdf_ready')},
        'ocr': {k:int(ocr[k] or 0) for k in ('unresolved','total')},
    }


def acceptance_snapshot() -> dict:
    status = lesson_studio_status()
    counts = _counts()
    refs = counts['references']
    jobs = counts['jobs']
    checks = [
        {
            'id':'runtime',
            'label':'بيئة Lesson Studio جاهزة',
            'ok':bool(status.get('gemini_configured') and status.get('storage_configured')),
            'detail':f"Gemini: {'جاهز' if status.get('gemini_configured') else 'غير مهيأ'} · التخزين: {'جاهز' if status.get('storage_configured') else 'غير مهيأ'}",
            'owner':'system',
        },
        {
            'id':'reference_pdf',
            'label':'مرجع علمي حقيقي تم إدخاله واستخراجه',
            'ok':refs['ingestion_ready'] > 0,
            'detail':f"{refs['ingestion_ready']} مرجع مكتمل الاستخراج من {refs['active']} مرجع نشط",
            'owner':'teacher',
        },
        {
            'id':'curriculum_map',
            'label':'Curriculum Map مبني من المرجع',
            'ok':refs['with_curriculum_map'] > 0,
            'detail':f"{refs['with_curriculum_map']} مرجع لديه خريطة منهج مصدرية",
            'owner':'teacher',
        },
        {
            'id':'handwritten_job',
            'label':'درس حقيقي تم نسخه وتنظيمه',
            'ok':jobs['structured'] > 0,
            'detail':f"{jobs['structured']} مشروع منظم من أصل {jobs['total']}",
            'owner':'teacher',
        },
        {
            'id':'ocr_review',
            'label':'مراجعة OCR محسومة',
            'ok':jobs['structured'] > 0 and counts['ocr']['unresolved'] == 0,
            'detail':f"{counts['ocr']['unresolved']} مصدر ما زال يحتاج مراجعة من {counts['ocr']['total']}",
            'owner':'teacher',
        },
        {
            'id':'reference_review',
            'label':'Scientific Reference Review تم تشغيله',
            'ok':jobs['reference_reviewed'] > 0,
            'detail':f"{jobs['reference_reviewed']} مشروع تمت مراجعته مقابل مرجع علمي",
            'owner':'teacher',
        },
        {
            'id':'teacher_approval',
            'label':'اعتماد المدرس النهائي موجود',
            'ok':jobs['teacher_approved'] > 0,
            'detail':f"{jobs['teacher_approved']} مشروع معتمد من المدرس",
            'owner':'teacher',
        },
        {
            'id':'final_pdf',
            'label':'Final PDF تم تصديره بعد بوابة الجودة',
            'ok':jobs['final_pdf_ready'] > 0,
            'detail':f"{jobs['final_pdf_ready']} ملف نهائي جاهز",
            'owner':'teacher',
        },
    ]
    blockers = [x for x in checks if not x['ok']]
    return {
        'version': app.version,
        'acceptance_ready': not blockers,
        'checks': checks,
        'blockers': blockers,
        'counts': counts,
        'runtime': {
            'ocr_provider': status.get('ocr_provider'),
            'dual_ocr_available': bool(status.get('dual_ocr_available')),
            'gemini_configured': bool(status.get('gemini_configured')),
            'mathpix_configured': bool(status.get('mathpix_configured')),
            'storage_configured': bool(status.get('storage_configured')),
        },
        'policy': 'no acceptance criterion may be satisfied by invented scientific content',
    }


@app.get('/api/admin/lesson-studio/acceptance', dependencies=[Depends(require_admin)])
def lesson_studio_acceptance():
    return acceptance_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>جاهزية Lesson Studio v1.8</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:980px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.item{padding:12px;border-bottom:1px solid #eee}.ok{color:#067647}.bad{color:#b42318}.muted{color:#667085}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.n{font-size:26px;font-weight:800}a{margin-left:10px}@media(max-width:650px){main{padding:10px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a><a href="/admin/lesson-studio">Lesson Studio</a><a href="/admin/lesson-studio/references">المراجع</a><a href="/admin/lesson-studio/workspace">مساحة العمل</a></div>
<div id=out class=box>جارٍ فحص جاهزية v1.8...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r=await fetch('/api/admin/lesson-studio/acceptance');if(r.status===401){location.href='/admin/login';return}let x=await r.json();let c=x.counts;out.innerHTML='<h1>Acceptance Gate — Lesson Studio v'+e(x.version)+'</h1><p class="'+(x.acceptance_ready?'ok':'bad')+'"><b>'+(x.acceptance_ready?'✅ جاهز لاختبار القبول الكامل':'⚠️ ما زالت هناك خطوات قبول بمصدر حقيقي')+'</b></p><div class=grid><div class=card><div class=muted>المراجع النشطة</div><div class=n>'+c.references.active+'</div></div><div class=card><div class=muted>خرائط المنهج</div><div class=n>'+c.references.with_curriculum_map+'</div></div><div class=card><div class=muted>مشاريع الدروس</div><div class=n>'+c.jobs.total+'</div></div><div class=card><div class=muted>PDF نهائي</div><div class=n>'+c.jobs.final_pdf_ready+'</div></div></div><h2>بوابات القبول</h2>'+x.checks.map(v=>'<div class="item '+(v.ok?'ok':'bad')+'">'+(v.ok?'✅ ':'⚠️ ')+e(v.label)+'<div class=muted>'+e(v.detail)+'</div></div>').join('')+'<h2>السياسة</h2><p class=muted>'+e(x.policy)+'</p>'}
load();
</script></main></html>'''


@app.get('/admin/lesson-studio/acceptance', response_class=HTMLResponse)
def lesson_studio_acceptance_page():
    return PAGE
