from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .content_completion import content_completion_snapshot
from .lesson_studio_acceptance import acceptance_snapshot
from .main import app
from .security import require_admin


def _studio_check(studio: dict, check_id: str) -> dict:
    """Return one Lesson Studio acceptance check without treating a missing check as success."""
    for raw in studio.get('checks') or []:
        item = dict(raw)
        if item.get('id') == check_id:
            return item
    return {
        'id': check_id,
        'ok': False,
        'owner': 'system',
        'label': f'Missing Lesson Studio acceptance check: {check_id}',
        'detail': 'The expected acceptance check was not returned.',
    }


def _stage(
    stage_id: str,
    title: str,
    ok: bool,
    owner: str,
    detail: str,
    path: str,
) -> dict:
    """Build one stable acceptance-matrix stage."""
    return {
        'id': stage_id,
        'title': title,
        'ok': bool(ok),
        'owner': owner,
        'detail': detail,
        'path': path,
    }


def e2e_content_acceptance_snapshot(
    *,
    content_snapshot: dict | None = None,
    studio_snapshot: dict | None = None,
) -> dict:
    """Compose curriculum completion and Lesson Studio acceptance into one read-only final matrix."""
    content = content_snapshot if content_snapshot is not None else content_completion_snapshot()
    studio = studio_snapshot if studio_snapshot is not None else acceptance_snapshot()
    coverage = content.get('source_coverage') or {}

    active = bool(content.get('active'))
    documents = content.get('documents') or []
    total_lessons = int(coverage.get('total_lessons') or 0)
    covered_lessons = int(coverage.get('covered_lessons') or 0)
    open_qa = int(coverage.get('open_qa_total') or 0)

    schema = _studio_check(studio, 'schema')
    runtime = _studio_check(studio, 'runtime')
    release_binding_integrity = _studio_check(studio, 'release_binding_integrity')
    system_checks = (schema, runtime, release_binding_integrity)
    studio_platform_ok = bool(
        studio.get('platform_ready') and all(bool(item.get('ok')) for item in system_checks)
    )
    failed_system_checks = [str(item.get('id') or 'unknown') for item in system_checks if not item.get('ok')]

    reference_pdf = _studio_check(studio, 'reference_pdf')
    curriculum_map = _studio_check(studio, 'curriculum_map')
    structured_lesson = _studio_check(studio, 'handwritten_job')
    ocr_review = _studio_check(studio, 'ocr_review')
    reference_review = _studio_check(studio, 'reference_review')
    teacher_approval = _studio_check(studio, 'teacher_approval')
    final_pdf = _studio_check(studio, 'final_pdf')

    matrix = [
        _stage(
            'curriculum_active',
            'المنهج الحالي النشط مضبوط',
            active,
            'teacher',
            (
                f"العام الدراسي النشط: {content.get('academic_year')}"
                if active
                else f"لا يوجد منهج حالي نشط · {content.get('reason') or 'غير مهيأ'}"
            ),
            '/admin/academic',
        ),
        _stage(
            'explanatory_document_registered',
            'يوجد مصدر شرح حقيقي مسجل للمنهج الحالي',
            active and bool(documents),
            'teacher',
            f'{len(documents)} مصدر شرح مسجل للمنهج الحالي',
            '/admin/content-completion',
        ),
        _stage(
            'page_complete_curriculum_coverage',
            'كل درس مغطى بنطاق صفحات معتمد ومستخرج وغير فارغ',
            active and bool(coverage.get('explanatory_coverage_complete')),
            'teacher',
            f'{covered_lessons} / {total_lessons} درس مغطى',
            '/admin/content-completion',
        ),
        _stage(
            'question_qa_clear',
            'كل ملاحظات QA لأسئلة المنهج الحالي محسومة بشريًا',
            active and bool(coverage.get('question_review_complete')),
            'teacher',
            f'{open_qa} ملاحظة QA مفتوحة',
            '/admin/current-corpus',
        ),
        _stage(
            'lesson_studio_platform',
            'Lesson Studio سليم برمجيًا وتشغيليًا',
            studio_platform_ok,
            'system',
            (
                'فحوص schema/runtime/release_binding_integrity موجودة وناجحة'
                if studio_platform_ok
                else 'فحوص النظام غير ناجحة أو ناقصة: ' + ', '.join(failed_system_checks or ['platform_ready'])
            ),
            '/admin/lesson-studio/acceptance',
        ),
        _stage(
            'reference_pdf',
            'مرجع Lesson Studio الحقيقي مكتمل الإدخال والاستخراج',
            bool(reference_pdf.get('ok')),
            str(reference_pdf.get('owner') or 'teacher'),
            str(reference_pdf.get('detail') or ''),
            '/admin/lesson-studio/references',
        ),
        _stage(
            'curriculum_map',
            'Curriculum Map حديث ومطابق للمرجع الحالي',
            bool(curriculum_map.get('ok')),
            str(curriculum_map.get('owner') or 'teacher'),
            str(curriculum_map.get('detail') or ''),
            '/admin/lesson-studio/references',
        ),
        _stage(
            'structured_lesson',
            'يوجد درس حقيقي منظم من المصدر',
            bool(structured_lesson.get('ok')),
            str(structured_lesson.get('owner') or 'teacher'),
            str(structured_lesson.get('detail') or ''),
            '/admin/lesson-studio',
        ),
        _stage(
            'ocr_review',
            'OCR والمصادر المرتبطة بالدرس محسومة',
            bool(ocr_review.get('ok')),
            str(ocr_review.get('owner') or 'teacher'),
            str(ocr_review.get('detail') or ''),
            '/admin/lesson-studio/acceptance',
        ),
        _stage(
            'scientific_reference_review',
            'المراجعة العلمية حديثة وغير حاجبة',
            bool(reference_review.get('ok')),
            str(reference_review.get('owner') or 'teacher'),
            str(reference_review.get('detail') or ''),
            '/admin/lesson-studio/acceptance',
        ),
        _stage(
            'teacher_approval',
            'اعتماد المدرس حديث ومربوط بالمحتوى والرسومات الحالية',
            bool(teacher_approval.get('ok')),
            str(teacher_approval.get('owner') or 'teacher'),
            str(teacher_approval.get('detail') or ''),
            '/admin/lesson-studio/acceptance',
        ),
        _stage(
            'final_pdf',
            'يوجد مسار درس واحد مكتمل حتى PDF نهائي حديث',
            bool(final_pdf.get('ok')),
            str(final_pdf.get('owner') or 'teacher'),
            str(final_pdf.get('detail') or ''),
            '/admin/lesson-studio/acceptance',
        ),
    ]

    blockers = [item for item in matrix if not item['ok']]
    system_blockers = [item for item in blockers if item['owner'] == 'system']
    human_blockers = [item for item in blockers if item['owner'] != 'system']
    next_action = (system_blockers or human_blockers or [None])[0]

    content_ready = bool(content.get('content_complete'))
    studio_ready = bool(studio.get('acceptance_ready'))
    overall_ready = bool(content_ready and studio_ready and studio_platform_ok and not blockers)

    return {
        'version': app.version,
        'overall_ready': overall_ready,
        'platform_ready': studio_platform_ok,
        'curriculum_content_ready': content_ready,
        'lesson_studio_acceptance_ready': studio_ready,
        'matrix': matrix,
        'blockers': blockers,
        'system_blockers': system_blockers,
        'human_blockers': human_blockers,
        'next_action': next_action,
        'summary': {
            'stages_total': len(matrix),
            'stages_passed': sum(1 for item in matrix if item['ok']),
            'stages_blocked': len(blockers),
            'system_blockers': len(system_blockers),
            'human_blockers': len(human_blockers),
            'current_curriculum_lessons': total_lessons,
            'covered_curriculum_lessons': covered_lessons,
            'open_question_qa': open_qa,
        },
        'policy': {
            'diagnostics_are_read_only': True,
            'no_source_is_auto_approved': True,
            'no_question_is_auto_approved': True,
            'no_teacher_approval_is_synthesized': True,
            'no_scientific_content_is_invented': True,
            'curriculum_and_lesson_studio_must_both_pass': True,
            'system_checks_must_be_present_and_pass': True,
            'system_blockers_are_prioritized_before_human_work': True,
        },
    }


@app.get('/api/admin/e2e-content-acceptance', dependencies=[Depends(require_admin)])
def e2e_content_acceptance_api():
    """Return the final read-only curriculum and Lesson Studio acceptance matrix."""
    return e2e_content_acceptance_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>End-to-End Content Acceptance</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1120px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}.item{padding:12px;border-bottom:1px solid #eee}.btn{display:inline-block;margin-top:7px;padding:7px 11px;background:#172033;color:#fff;text-decoration:none;border-radius:8px}@media(max-width:650px){main{padding:10px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/content-completion">Content Completion</a> · <a href="/admin/lesson-studio/acceptance">Lesson Studio Acceptance</a> · <a href="/admin/project-closure">Project Closure</a></div>
<div id=out class=box>جارٍ بناء مصفوفة القبول النهائية...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r;try{r=await fetch('/api/admin/e2e-content-acceptance')}catch(err){out.innerHTML='<div class=bad>تعذر الاتصال بالخادم</div>';return}if(r.status===401){location.href='/admin/login';return}if(!r.ok){out.innerHTML='<div class=bad>تعذر تشغيل مصفوفة القبول</div>';return}let x;try{x=await r.json()}catch(err){out.innerHTML='<div class=bad>تعذر قراءة نتيجة القبول</div>';return}let s=x.summary||{},next=x.next_action;out.innerHTML='<h1>End-to-End Content Acceptance Matrix</h1><p class="'+(x.overall_ready?'ok':x.platform_ready?'warn':'bad')+'"><b>'+(x.overall_ready?'✅ المنهج ومسار Lesson Studio مقبولان بالكامل':x.platform_ready?'⚠️ المنصة سليمة وما زالت بوابات المحتوى البشرية مفتوحة':'⛔ يوجد مانع برمجي/تشغيلي')+'</b></p><div class=grid><div class=card><div class=muted>المراحل الناجحة</div><h2>'+e(s.stages_passed)+' / '+e(s.stages_total)+'</h2></div><div class=card><div class=muted>موانع النظام</div><h2>'+e(s.system_blockers)+'</h2></div><div class=card><div class=muted>الموانع البشرية</div><h2>'+e(s.human_blockers)+'</h2></div><div class=card><div class=muted>تغطية الدروس</div><h2>'+e(s.covered_curriculum_lessons)+' / '+e(s.current_curriculum_lessons)+'</h2></div></div>'+(next?'<div class="item '+(next.owner==='system'?'bad':'warn')+'"><b>الخطوة التالية: '+e(next.title)+'</b><div class=muted>'+e(next.detail)+'</div><a class=btn href="'+e(next.path)+'">فتح مسار المعالجة</a></div>':'<div class="item ok"><b>✅ لا توجد بوابات مفتوحة</b></div>')+'<h2>المصفوفة</h2>'+x.matrix.map(v=>'<div class="item '+(v.ok?'ok':v.owner==='system'?'bad':'warn')+'"><b>'+(v.ok?'✅ ':'⚠️ ')+e(v.title)+'</b><div class=muted>'+e(v.detail)+' · المسؤول: '+e(v.owner)+'</div>'+(v.ok?'':'<a class=btn href="'+e(v.path)+'">فتح</a>')+'</div>').join('')+'<p class=muted>هذه الصفحة تشخيصية فقط: لا تعتمد مصدرًا أو سؤالًا أو مدرسًا، ولا تنشئ PDF، ولا تملأ أي محتوى علمي مفقود من معرفة النموذج.</p>'}
load();
</script></main></html>'''


@app.get(
    '/admin/e2e-content-acceptance',
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
def e2e_content_acceptance_page():
    """Render the final end-to-end curriculum and Lesson Studio acceptance matrix."""
    return PAGE
