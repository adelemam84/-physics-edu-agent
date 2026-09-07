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
from .services.lesson_integrity import review_source_hash
from .science_reference_curriculum_map import _pages_hash


def _counts() -> dict:
    lesson_schema()
    reference_schema()
    _map_schema()
    _reference_review_schema()
    _quality_schema()
    with connect() as con:
        ref_rows = list(con.execute("""SELECT id,active,ingestion_status,curriculum_map,curriculum_map_source_hash
          FROM science_reference_documents""").fetchall())
        page_rows = list(con.execute("""SELECT document_id,page_number,page_text
          FROM science_reference_pages WHERE btrim(page_text)<>'' ORDER BY document_id,page_number""").fetchall())
        job_rows = list(con.execute("""SELECT id,raw_transcript,structured_json,reference_review,
          reference_review_hash,teacher_approved,status,pdf_object_key,pdf_source_hash
          FROM science_lesson_jobs""").fetchall())
        ocr = con.execute("""SELECT
          count(*) FILTER (WHERE requires_review=TRUE) unresolved,
          count(*) total
          FROM science_lesson_sources""").fetchone()

    pages_by_doc: dict[str, list[dict]] = {}
    for row in page_rows:
        pages_by_doc.setdefault(str(row['document_id']), []).append(dict(row))

    refs = {'active':0,'ingestion_ready':0,'with_curriculum_map':0,'mapped':0,'fresh_curriculum_map':0}
    for row in ref_rows:
        if not row.get('active'):
            continue
        refs['active'] += 1
        if row.get('ingestion_status') == 'ready':
            refs['ingestion_ready'] += 1
        if row.get('curriculum_map'):
            refs['with_curriculum_map'] += 1
        if row.get('curriculum_map') and row.get('curriculum_map_source_hash'):
            refs['mapped'] += 1
            current = _pages_hash(pages_by_doc.get(str(row['id']), []))
            if current == row.get('curriculum_map_source_hash'):
                refs['fresh_curriculum_map'] += 1

    jobs = {'total':0,'structured':0,'reference_reviewed':0,'fresh_reference_reviewed':0,
            'teacher_approved':0,'final_pdf_ready':0,'fresh_final_pdf_ready':0}
    for row in job_rows:
        jobs['total'] += 1
        structured = dict(row.get('structured_json') or {})
        if structured:
            jobs['structured'] += 1
        current_hash = review_source_hash(str(row.get('raw_transcript') or ''), structured)
        if row.get('reference_review'):
            jobs['reference_reviewed'] += 1
            if row.get('reference_review_hash') == current_hash:
                jobs['fresh_reference_reviewed'] += 1
        if row.get('teacher_approved'):
            jobs['teacher_approved'] += 1
        if row.get('status') == 'final_pdf_ready' and row.get('pdf_object_key'):
            jobs['final_pdf_ready'] += 1
            if row.get('pdf_source_hash') == current_hash:
                jobs['fresh_final_pdf_ready'] += 1

    return {
        'references': refs,
        'jobs': jobs,
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
            'ok':refs['fresh_curriculum_map'] > 0,
            'detail':f"{refs['fresh_curriculum_map']} خريطة حديثة من {refs['with_curriculum_map']} خريطة موجودة",
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
            'ok':jobs['fresh_reference_reviewed'] > 0,
            'detail':f"{jobs['fresh_reference_reviewed']} مراجعة حديثة من {jobs['reference_reviewed']} مراجعة موجودة",
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
            'ok':jobs['fresh_final_pdf_ready'] > 0,
            'detail':f"{jobs['fresh_final_pdf_ready']} PDF حديث من {jobs['final_pdf_ready']} ملف موجود",
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
async function load(){let r=await fetch('/api/admin/lesson-studio/acceptance');if(r.status===401){location.href='/admin/login';return}let x=await r.json();let c=x.counts;out.innerHTML='<h1>Acceptance Gate — Lesson Studio v'+e(x.version)+'</h1><p class="'+(x.acceptance_ready?'ok':'bad')+'"><b>'+(x.acceptance_ready?'✅ جاهز لاختبار القبول الكامل':'⚠️ ما زالت هناك خطوات قبول بمصدر حقيقي')+'</b></p><div class=grid><div class=card><div class=muted>المراجع النشطة</div><div class=n>'+c.references.active+'</div></div><div class=card><div class=muted>خرائط المنهج</div><div class=n>'+c.references.fresh_curriculum_map+'</div></div><div class=card><div class=muted>مشاريع الدروس</div><div class=n>'+c.jobs.total+'</div></div><div class=card><div class=muted>PDF نهائي</div><div class=n>'+c.jobs.fresh_final_pdf_ready+'</div></div></div><h2>بوابات القبول</h2>'+x.checks.map(v=>'<div class="item '+(v.ok?'ok':'bad')+'">'+(v.ok?'✅ ':'⚠️ ')+e(v.label)+'<div class=muted>'+e(v.detail)+'</div></div>').join('')+'<h2>السياسة</h2><p class=muted>'+e(x.policy)+'</p>'}
load();
</script></main></html>'''


@app.get('/admin/lesson-studio/acceptance', response_class=HTMLResponse)
def lesson_studio_acceptance_page():
    return PAGE
