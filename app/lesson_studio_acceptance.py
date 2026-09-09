from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin
from .science_lesson_studio import lesson_studio_status
from .science_reference_curriculum_map import _pages_hash
from .services.lesson_diagram_integrity import diagram_manifest
from .services.lesson_integrity import review_source_hash


_REQUIRED_TABLES = (
    'science_lesson_jobs',
    'science_lesson_sources',
    'science_lesson_gate_state',
    'science_lesson_versions',
    'science_reference_documents',
    'science_reference_pages',
)
_REQUIRED_JOB_COLUMNS = (
    'teacher_approved',
    'teacher_approval_source_hash',
    'teacher_approval_diagram_hash',
    'reference_review',
    'reference_review_hash',
    'pdf_object_key',
    'pdf_source_hash',
    'pdf_diagram_manifest_hash',
)


def _schema_snapshot(con) -> dict:
    """Inspect acceptance-critical persistence without creating or altering database objects."""
    tables = {
        str(row['table_name'])
        for row in con.execute(
            '''SELECT table_name FROM information_schema.tables
               WHERE table_schema=current_schema() AND table_name = ANY(%s)''',
            (list(_REQUIRED_TABLES),),
        ).fetchall()
    }
    columns = {
        str(row['column_name'])
        for row in con.execute(
            '''SELECT column_name FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name='science_lesson_jobs'
                 AND column_name = ANY(%s)''',
            (list(_REQUIRED_JOB_COLUMNS),),
        ).fetchall()
    }
    missing_tables = sorted(set(_REQUIRED_TABLES) - tables)
    missing_columns = sorted(set(_REQUIRED_JOB_COLUMNS) - columns)
    return {
        'ready': not missing_tables and not missing_columns,
        'missing_tables': missing_tables,
        'missing_job_columns': missing_columns,
        'required_tables': len(_REQUIRED_TABLES),
        'required_job_columns': len(_REQUIRED_JOB_COLUMNS),
    }


def _job_binding_summary(row: dict, *, pending_sources: int, total_sources: int) -> dict:
    """Evaluate one lesson's release bindings against its exact current content and diagram identities."""
    structured = dict(row.get('structured_json') or {})
    content_hash = review_source_hash(str(row.get('raw_transcript') or ''), structured)
    diagram_hash = diagram_manifest(structured)['hash']
    structured_ready = bool(structured)
    sources_bound = total_sources > 0 and int(row.get('source_count') or 0) == total_sources
    ocr_clear = sources_bound and pending_sources == 0

    reference_recorded = bool(row.get('reference_review'))
    reference_fresh = bool(
        reference_recorded
        and row.get('reference_review_hash') == content_hash
    )

    teacher_recorded = bool(row.get('teacher_approved'))
    teacher_fresh = bool(
        teacher_recorded
        and row.get('teacher_approval_source_hash') == content_hash
        and row.get('teacher_approval_diagram_hash') == diagram_hash
    )

    pdf_key = str(row.get('pdf_object_key') or '')
    pdf_recorded = bool(pdf_key)
    pdf_hash_fresh = bool(
        pdf_recorded
        and row.get('pdf_source_hash') == content_hash
        and row.get('pdf_diagram_manifest_hash') == diagram_hash
    )
    pdf_fresh = bool(pdf_hash_fresh and row.get('status') == 'final_pdf_ready')

    return {
        'structured_ready': structured_ready,
        'sources_bound': sources_bound,
        'ocr_clear': ocr_clear,
        'reference_recorded': reference_recorded,
        'reference_fresh': reference_fresh,
        'teacher_recorded': teacher_recorded,
        'teacher_fresh': teacher_fresh,
        'pdf_recorded': pdf_recorded,
        'pdf_fresh': pdf_fresh,
        'content_hash': content_hash,
        'diagram_manifest_hash': diagram_hash,
        'complete_release': bool(
            structured_ready
            and ocr_clear
            and reference_fresh
            and teacher_fresh
            and pdf_fresh
        ),
    }


def _empty_counts(schema: dict) -> dict:
    """Return a stable diagnostic shape when startup schema is incomplete."""
    return {
        'schema': schema,
        'references': {
            'active': 0,
            'ingestion_ready': 0,
            'with_curriculum_map': 0,
            'fresh_curriculum_map': 0,
        },
        'jobs': {
            'total': 0,
            'structured': 0,
            'ocr_clear_structured': 0,
            'reference_reviewed': 0,
            'fresh_reference_reviewed': 0,
            'teacher_approved': 0,
            'fresh_teacher_approved': 0,
            'final_pdf_ready': 0,
            'fresh_final_pdf_ready': 0,
            'complete_release_jobs': 0,
        },
        'integrity': {
            'stale_teacher_approval_bindings': 0,
            'stale_pdf_bindings': 0,
            'orphan_teacher_hashes': 0,
            'orphan_pdf_hashes': 0,
        },
        'ocr': {'unresolved': 0, 'total': 0},
    }


def _counts() -> dict:
    """Read production acceptance facts without DDL, cache writes, approvals, or object mutations."""
    with connect() as con:
        schema = _schema_snapshot(con)
        if not schema['ready']:
            return _empty_counts(schema)

        ref_rows = list(con.execute(
            '''SELECT id,active,ingestion_status,curriculum_map,curriculum_map_source_hash
               FROM science_reference_documents'''
        ).fetchall())
        page_rows = list(con.execute(
            '''SELECT document_id,page_number,page_text FROM science_reference_pages
               WHERE btrim(page_text)<>'' ORDER BY document_id,page_number'''
        ).fetchall())
        job_rows = list(con.execute(
            '''SELECT id,source_count,raw_transcript,structured_json,reference_review,
                      reference_review_hash,teacher_approved,teacher_approval_source_hash,
                      teacher_approval_diagram_hash,status,pdf_object_key,pdf_source_hash,
                      pdf_diagram_manifest_hash
               FROM science_lesson_jobs'''
        ).fetchall())
        source_rows = list(con.execute(
            '''SELECT job_id,requires_review FROM science_lesson_sources'''
        ).fetchall())

    pages_by_doc: dict[str, list[dict]] = {}
    for row in page_rows:
        pages_by_doc.setdefault(str(row['document_id']), []).append(dict(row))

    refs = {
        'active': 0,
        'ingestion_ready': 0,
        'with_curriculum_map': 0,
        'fresh_curriculum_map': 0,
    }
    for raw in ref_rows:
        row = dict(raw)
        if not row.get('active'):
            continue
        refs['active'] += 1
        if row.get('ingestion_status') == 'ready':
            refs['ingestion_ready'] += 1
        if row.get('curriculum_map'):
            refs['with_curriculum_map'] += 1
            current_pages_hash = _pages_hash(pages_by_doc.get(str(row['id']), []))
            if row.get('curriculum_map_source_hash') == current_pages_hash:
                refs['fresh_curriculum_map'] += 1

    source_totals: dict[str, int] = {}
    source_pending: dict[str, int] = {}
    for raw in source_rows:
        row = dict(raw)
        key = str(row['job_id'])
        source_totals[key] = source_totals.get(key, 0) + 1
        if row.get('requires_review'):
            source_pending[key] = source_pending.get(key, 0) + 1

    jobs = {
        'total': 0,
        'structured': 0,
        'ocr_clear_structured': 0,
        'reference_reviewed': 0,
        'fresh_reference_reviewed': 0,
        'teacher_approved': 0,
        'fresh_teacher_approved': 0,
        'final_pdf_ready': 0,
        'fresh_final_pdf_ready': 0,
        'complete_release_jobs': 0,
    }
    integrity = {
        'stale_teacher_approval_bindings': 0,
        'stale_pdf_bindings': 0,
        'orphan_teacher_hashes': 0,
        'orphan_pdf_hashes': 0,
    }

    for raw in job_rows:
        row = dict(raw)
        key = str(row['id'])
        state = _job_binding_summary(
            row,
            pending_sources=source_pending.get(key, 0),
            total_sources=source_totals.get(key, 0),
        )
        jobs['total'] += 1
        if state['structured_ready']:
            jobs['structured'] += 1
            if state['ocr_clear']:
                jobs['ocr_clear_structured'] += 1
        if state['reference_recorded']:
            jobs['reference_reviewed'] += 1
        if state['reference_fresh']:
            jobs['fresh_reference_reviewed'] += 1
        if state['teacher_recorded']:
            jobs['teacher_approved'] += 1
            if not state['teacher_fresh']:
                integrity['stale_teacher_approval_bindings'] += 1
        if state['teacher_fresh']:
            jobs['fresh_teacher_approved'] += 1
        if state['pdf_recorded']:
            jobs['final_pdf_ready'] += 1
            if not state['pdf_fresh']:
                integrity['stale_pdf_bindings'] += 1
        if state['pdf_fresh']:
            jobs['fresh_final_pdf_ready'] += 1
        if state['complete_release']:
            jobs['complete_release_jobs'] += 1

        if not state['teacher_recorded'] and (
            row.get('teacher_approval_source_hash') or row.get('teacher_approval_diagram_hash')
        ):
            integrity['orphan_teacher_hashes'] += 1
        if not state['pdf_recorded'] and (
            row.get('pdf_source_hash') or row.get('pdf_diagram_manifest_hash')
        ):
            integrity['orphan_pdf_hashes'] += 1

    return {
        'schema': schema,
        'references': refs,
        'jobs': jobs,
        'integrity': integrity,
        'ocr': {
            'unresolved': sum(source_pending.values()),
            'total': sum(source_totals.values()),
        },
    }


def acceptance_snapshot() -> dict:
    """Return strict production acceptance without satisfying any gate by model inference or mutation."""
    status = lesson_studio_status()
    counts = _counts()
    refs = counts['references']
    jobs = counts['jobs']
    integrity = counts['integrity']
    binding_integrity_ok = (
        integrity['stale_teacher_approval_bindings'] == 0
        and integrity['stale_pdf_bindings'] == 0
    )
    checks = [
        {
            'id': 'schema',
            'label': 'مخطط Lesson Studio للإنتاج مكتمل',
            'ok': bool(counts['schema']['ready']),
            'detail': (
                'الجداول والأعمدة المطلوبة موجودة'
                if counts['schema']['ready']
                else f"جداول ناقصة: {counts['schema']['missing_tables']} · أعمدة ناقصة: {counts['schema']['missing_job_columns']}"
            ),
            'owner': 'system',
        },
        {
            'id': 'runtime',
            'label': 'بيئة Lesson Studio جاهزة',
            'ok': bool(status.get('gemini_configured') and status.get('storage_configured')),
            'detail': f"Gemini: {'جاهز' if status.get('gemini_configured') else 'غير مهيأ'} · التخزين: {'جاهز' if status.get('storage_configured') else 'غير مهيأ'}",
            'owner': 'system',
        },
        {
            'id': 'release_binding_integrity',
            'label': 'روابط الاعتماد وPDF متطابقة مع المحتوى والرسومات الحالية',
            'ok': binding_integrity_ok,
            'detail': (
                f"اعتمادات قديمة نشطة: {integrity['stale_teacher_approval_bindings']} · "
                f"PDF قديم نشط: {integrity['stale_pdf_bindings']}"
            ),
            'owner': 'system',
        },
        {
            'id': 'reference_pdf',
            'label': 'مرجع علمي حقيقي تم إدخاله واستخراجه',
            'ok': refs['ingestion_ready'] > 0,
            'detail': f"{refs['ingestion_ready']} مرجع مكتمل الاستخراج من {refs['active']} مرجع نشط",
            'owner': 'teacher',
        },
        {
            'id': 'curriculum_map',
            'label': 'Curriculum Map حديث ومبني من المرجع',
            'ok': refs['fresh_curriculum_map'] > 0,
            'detail': f"{refs['fresh_curriculum_map']} خريطة حديثة من {refs['with_curriculum_map']} خريطة موجودة",
            'owner': 'teacher',
        },
        {
            'id': 'handwritten_job',
            'label': 'درس حقيقي تم نسخه وتنظيمه',
            'ok': jobs['structured'] > 0,
            'detail': f"{jobs['structured']} مشروع منظم من أصل {jobs['total']}",
            'owner': 'teacher',
        },
        {
            'id': 'ocr_review',
            'label': 'يوجد درس منظم بمصادر OCR محسومة ومربوطة',
            'ok': jobs['ocr_clear_structured'] > 0,
            'detail': f"{jobs['ocr_clear_structured']} درس منظم خالٍ من مراجعات OCR المعلقة",
            'owner': 'teacher',
        },
        {
            'id': 'reference_review',
            'label': 'Scientific Reference Review حديث للمحتوى الحالي',
            'ok': jobs['fresh_reference_reviewed'] > 0,
            'detail': f"{jobs['fresh_reference_reviewed']} مراجعة حديثة من {jobs['reference_reviewed']} مراجعة موجودة",
            'owner': 'teacher',
        },
        {
            'id': 'teacher_approval',
            'label': 'اعتماد المدرس مربوط بالمحتوى والرسومات الحالية',
            'ok': jobs['fresh_teacher_approved'] > 0,
            'detail': f"{jobs['fresh_teacher_approved']} اعتماد حديث من {jobs['teacher_approved']} اعتماد مسجل",
            'owner': 'teacher',
        },
        {
            'id': 'final_pdf',
            'label': 'مسار كامل واحد على الأقل وصل إلى PDF حديث وآمن',
            'ok': jobs['complete_release_jobs'] > 0,
            'detail': (
                f"{jobs['complete_release_jobs']} مسار مكتمل · "
                f"{jobs['fresh_final_pdf_ready']} PDF حديث من {jobs['final_pdf_ready']} PDF مسجل"
            ),
            'owner': 'teacher',
        },
    ]
    blockers = [item for item in checks if not item['ok']]
    system_blockers = [item for item in blockers if item['owner'] == 'system']
    return {
        'version': app.version,
        'acceptance_ready': not blockers,
        'platform_ready': not system_blockers,
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
        'policy': {
            'diagnostics_are_read_only': True,
            'no_acceptance_criterion_satisfied_by_invented_scientific_content': True,
            'teacher_approval_bound_to_content_and_diagram_manifest': True,
            'final_pdf_bound_to_content_and_diagram_manifest': True,
            'one_end_to_end_job_required_for_final_acceptance': True,
            'orphan_hashes_reported_but_do_not_impersonate_active_approval': True,
        },
    }


@app.get('/api/admin/lesson-studio/acceptance', dependencies=[Depends(require_admin)])
def lesson_studio_acceptance():
    """Expose the strict, read-only Lesson Studio production acceptance snapshot."""
    return acceptance_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>جاهزية Lesson Studio v1.8</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1040px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.item{padding:12px;border-bottom:1px solid #eee}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.n{font-size:26px;font-weight:800}a{margin-left:10px}@media(max-width:650px){main{padding:10px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a><a href="/admin/lesson-studio">Lesson Studio</a><a href="/admin/lesson-studio/release-readiness">Release Readiness</a><a href="/admin/project-closure">Project Closure</a></div>
<div id=out class=box>جارٍ تشغيل فحص القبول الآمن...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r=await fetch('/api/admin/lesson-studio/acceptance');if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){out.innerHTML='<div class=bad>تعذر تشغيل الفحص</div>';return}let c=x.counts,j=c.jobs,i=c.integrity;out.innerHTML='<h1>Production Acceptance — Lesson Studio v'+e(x.version)+'</h1><p class="'+(x.acceptance_ready?'ok':x.platform_ready?'warn':'bad')+'"><b>'+(x.acceptance_ready?'✅ القبول الكامل مكتمل':x.platform_ready?'⚠️ المنصة سليمة وتنتظر بوابات المحتوى البشرية':'⛔ يوجد مانع برمجي/تشغيلي')+'</b></p><div class=grid><div class=card><div class=muted>Schema</div><div class=n>'+ (c.schema.ready?'✅':'⛔') +'</div></div><div class=card><div class=muted>دروس منظمة</div><div class=n>'+j.structured+'</div></div><div class=card><div class=muted>اعتمادات حديثة</div><div class=n>'+j.fresh_teacher_approved+'</div></div><div class=card><div class=muted>مسارات PDF مكتملة</div><div class=n>'+j.complete_release_jobs+'</div></div></div><h2>بوابات القبول</h2>'+x.checks.map(v=>'<div class="item '+(v.ok?'ok':v.owner==='system'?'bad':'warn')+'">'+(v.ok?'✅ ':'⚠️ ')+e(v.label)+'<div class=muted>'+e(v.detail)+'</div></div>').join('')+'<h2>Integrity Diagnostics</h2><div class=item>Stale teacher approvals: '+e(i.stale_teacher_approval_bindings)+'</div><div class=item>Stale PDF bindings: '+e(i.stale_pdf_bindings)+'</div><div class=item>Orphan teacher hashes: '+e(i.orphan_teacher_hashes)+'</div><div class=item>Orphan PDF hashes: '+e(i.orphan_pdf_hashes)+'</div><p class=muted>هذا الفحص لا يكتب cache، ولا يعتمد محتوى، ولا ينشئ PDF، ولا يغلق أي بوابة بشرية تلقائيًا.</p>'}
load();
</script></main></html>'''


@app.get('/admin/lesson-studio/acceptance', response_class=HTMLResponse)
def lesson_studio_acceptance_page():
    """Render the strict production acceptance dashboard."""
    return PAGE
