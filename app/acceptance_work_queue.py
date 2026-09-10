from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .content_completion import content_completion_snapshot
from .e2e_content_acceptance import e2e_content_acceptance_snapshot
from .lesson_studio_acceptance import acceptance_snapshot
from .main import app
from .security import require_admin


_EXPECTED_STUDIO_CHECKS = (
    'schema',
    'runtime',
    'release_binding_integrity',
    'reference_pdf',
    'curriculum_map',
    'handwritten_job',
    'ocr_review',
    'reference_review',
    'teacher_approval',
    'final_pdf',
)

_STUDIO_PATHS = {
    'schema': '/admin/lesson-studio/acceptance',
    'runtime': '/admin/lesson-studio/acceptance',
    'release_binding_integrity': '/admin/lesson-studio/acceptance',
    'reference_pdf': '/admin/lesson-studio/references',
    'curriculum_map': '/admin/lesson-studio/references',
    'handwritten_job': '/admin/lesson-studio',
    'ocr_review': '/admin/lesson-studio/acceptance',
    'reference_review': '/admin/lesson-studio/acceptance',
    'teacher_approval': '/admin/lesson-studio/acceptance',
    'final_pdf': '/admin/lesson-studio/acceptance',
}


def _queue_item(
    item_id: str,
    category: str,
    priority: int,
    owner: str,
    title: str,
    detail: str,
    path: str,
    evidence: dict | None = None,
) -> dict:
    """Build one stable, non-mutating acceptance work item."""
    return {
        'id': item_id,
        'category': category,
        'priority': int(priority),
        'owner': owner,
        'title': title,
        'detail': detail,
        'path': path,
        'evidence': evidence or {},
    }


def _dict_rows(value: object) -> list[dict] | None:
    """Validate an upstream list of dictionaries and fail closed on malformed entries."""
    if not isinstance(value, list):
        return None
    if any(not isinstance(item, dict) for item in value):
        return None
    return [dict(item) for item in value]


def _malformed_item(source: str, field: str, path: str) -> dict:
    """Turn malformed upstream diagnostic evidence into a system-owned blocker."""
    return _queue_item(
        f'malformed:{source}:{field}',
        'system',
        0,
        'system',
        f'بيانات تشخيص {source} غير مكتملة',
        f'الحقل {field} مفقود أو بصيغة غير صالحة؛ لا يمكن اعتباره ناجحًا.',
        path,
        {'source': source, 'field': field},
    )


def acceptance_work_queue_snapshot(
    *,
    content_snapshot: dict | None = None,
    studio_snapshot: dict | None = None,
    e2e_snapshot: dict | None = None,
) -> dict:
    """Return concrete open acceptance tasks from live evidence without approving or mutating anything."""
    content = content_snapshot if content_snapshot is not None else content_completion_snapshot()
    studio = studio_snapshot if studio_snapshot is not None else acceptance_snapshot()
    e2e = (
        e2e_snapshot
        if e2e_snapshot is not None
        else e2e_content_acceptance_snapshot(content_snapshot=content, studio_snapshot=studio)
    )

    queue: list[dict] = []
    active = bool(content.get('active'))
    if not active:
        queue.append(_queue_item(
            'curriculum:inactive',
            'curriculum_source',
            1,
            'teacher',
            'ضبط المنهج الحالي النشط',
            f"لا يمكن إكمال أدلة المحتوى قبل ضبط المنهج الحالي: {content.get('reason') or 'غير مهيأ'}",
            '/admin/academic',
            {'reason': content.get('reason')},
        ))

    lessons = _dict_rows(content.get('lessons'))
    if active and lessons is None:
        queue.append(_malformed_item('content_completion', 'lessons', '/admin/content-completion'))
    elif active:
        for lesson in lessons or []:
            if lesson.get('covered'):
                continue
            lesson_id = lesson.get('id')
            title = str(lesson.get('title') or f'Lesson {lesson_id}')
            queue.append(_queue_item(
                f'curriculum-source:{lesson_id}',
                'curriculum_source',
                1,
                'teacher',
                f'اعتماد مصدر شرح موثق للدرس: {title}',
                'يلزم نطاق صفحات مستخرج بالكامل وغير فارغ، مطابق للسياق، ثم اعتماد بشري صريح للربط.',
                '/admin/content-completion',
                {
                    'lesson_id': lesson_id,
                    'title': title,
                    'term_id': lesson.get('term_id'),
                    'chapter': lesson.get('chapter'),
                    'approved_explanatory_mapping_count': int(
                        lesson.get('approved_explanatory_mapping_count') or 0
                    ),
                },
            ))

    qa_rows = _dict_rows(content.get('qa_open_by_reason'))
    if active and qa_rows is None:
        queue.append(_malformed_item('content_completion', 'qa_open_by_reason', '/admin/current-corpus'))
    else:
        for row in qa_rows or []:
            reason = str(row.get('reason_code') or 'unknown')
            count = max(int(row.get('total') or 0), 0)
            if not count:
                continue
            if reason == 'visual_transcription_required':
                title = 'مراجعة النسخ البصري من صور المصدر'
            elif reason == 'source_candidate_mismatch':
                title = 'حسم عدم تطابق السؤال المرشح مع المصدر'
            else:
                title = f'حسم ملاحظات QA: {reason}'
            queue.append(_queue_item(
                f'question-qa:{reason}',
                'question_qa',
                2,
                'teacher',
                title,
                f'{count} عنصر مفتوح يحتاج مراجعة مصدر بشرية.',
                '/admin/current-corpus',
                {'reason_code': reason, 'count': count},
            ))

    checks = _dict_rows(studio.get('checks'))
    if checks is None:
        queue.append(_malformed_item('lesson_studio_acceptance', 'checks', '/admin/lesson-studio/acceptance'))
        checks_by_id: dict[str, dict] = {}
    else:
        checks_by_id = {str(item.get('id')): item for item in checks if item.get('id')}

    for check_id in _EXPECTED_STUDIO_CHECKS:
        check = checks_by_id.get(check_id)
        if check is None:
            queue.append(_queue_item(
                f'lesson-studio:missing:{check_id}',
                'system',
                0,
                'system',
                f'فحص Lesson Studio مفقود: {check_id}',
                'الفحص المتوقع غير موجود في snapshot الحالي، لذلك يتم الحجب fail-closed.',
                '/admin/lesson-studio/acceptance',
                {'check_id': check_id, 'missing': True},
            ))
            continue
        if check.get('ok'):
            continue
        owner = str(check.get('owner') or 'system')
        priority = 0 if owner == 'system' else 3
        queue.append(_queue_item(
            f'lesson-studio:{check_id}',
            'system' if owner == 'system' else 'lesson_studio',
            priority,
            owner,
            str(check.get('label') or check_id),
            str(check.get('detail') or 'فحص Lesson Studio غير ناجح.'),
            _STUDIO_PATHS.get(check_id, '/admin/lesson-studio/acceptance'),
            {'check_id': check_id},
        ))

    if not isinstance(e2e.get('overall_ready'), bool):
        queue.append(_malformed_item('e2e_content_acceptance', 'overall_ready', '/admin/e2e-content-acceptance'))
        e2e_ready = False
    else:
        e2e_ready = bool(e2e.get('overall_ready'))

    if e2e_ready and queue:
        queue.append(_queue_item(
            'system:e2e-queue-inconsistency',
            'system',
            0,
            'system',
            'تعارض بين نتيجة القبول وقائمة الأدلة',
            'القبول الكلي معلن ناجحًا رغم وجود مهام مفتوحة؛ يلزم فحص عقد التشخيص قبل أي اعتماد نهائي.',
            '/admin/e2e-content-acceptance',
            {'queue_items_before_guard': len(queue)},
        ))

    queue.sort(key=lambda item: (item['priority'], item['category'], item['id']))
    system_open = sum(1 for item in queue if item['owner'] == 'system')
    teacher_open = len(queue) - system_open
    next_action = queue[0] if queue else None

    return {
        'version': app.version,
        'ready': bool(e2e_ready and not queue),
        'overall_acceptance_ready': e2e_ready,
        'items': queue,
        'next_action': next_action,
        'summary': {
            'total_open': len(queue),
            'system_open': system_open,
            'teacher_open': teacher_open,
            'uncovered_lessons': sum(1 for item in queue if item['category'] == 'curriculum_source'),
            'question_qa_buckets': sum(1 for item in queue if item['category'] == 'question_qa'),
            'lesson_studio_open': sum(
                1 for item in queue if item['id'].startswith('lesson-studio:')
            ),
        },
        'policy': {
            'diagnostic_only': True,
            'live_source_evidence_only': True,
            'no_source_auto_approval': True,
            'no_question_auto_approval': True,
            'no_teacher_approval_synthesis': True,
            'no_scientific_content_invention': True,
            'malformed_or_missing_evidence_fails_closed': True,
        },
    }


@app.get('/api/admin/acceptance-work-queue', dependencies=[Depends(require_admin)])
def acceptance_work_queue_api():
    """Expose the read-only acceptance evidence queue to authorized administrators."""
    return acceptance_work_queue_snapshot()


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Acceptance Work Queue</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1120px;margin:auto;padding:16px}.box{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e4e7ec;border-radius:12px;padding:12px}.ok{color:#067647}.bad{color:#b42318}.warn{color:#b54708}.muted{color:#667085}.item{padding:12px;border-bottom:1px solid #eee}.btn{display:inline-block;margin-top:7px;padding:7px 11px;background:#172033;color:#fff;text-decoration:none;border-radius:8px}.tag{display:inline-block;padding:3px 8px;border-radius:999px;background:#eef2f7;font-size:12px}@media(max-width:650px){main{padding:10px}}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/e2e-content-acceptance">E2E Acceptance</a> · <a href="/admin/content-completion">Content Completion</a> · <a href="/admin/lesson-studio/acceptance">Lesson Studio</a></div>
<div id=out class=box>جارٍ بناء قائمة العمل من الأدلة الحالية...</div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function load(){let r;try{r=await fetch('/api/admin/acceptance-work-queue')}catch(err){out.innerHTML='<div class=bad>تعذر الاتصال بالخادم</div>';return}if(r.status===401){location.href='/admin/login';return}if(!r.ok){out.innerHTML='<div class=bad>تعذر تشغيل قائمة أدلة القبول</div>';return}let x;try{x=await r.json()}catch(err){out.innerHTML='<div class=bad>تعذر قراءة النتيجة</div>';return}let s=x.summary||{},items=x.items||[];out.innerHTML='<h1>Human Acceptance Evidence Queue</h1><p class="'+(x.ready?'ok':'warn')+'"><b>'+(x.ready?'✅ لا توجد أدلة أو مراجعات معلقة':'⚠️ توجد مهام قبول مفتوحة مرتبة بالأولوية')+'</b></p><div class=grid><div class=card><span class=muted>المفتوح</span><h2>'+e(s.total_open)+'</h2></div><div class=card><span class=muted>System</span><h2>'+e(s.system_open)+'</h2></div><div class=card><span class=muted>Teacher</span><h2>'+e(s.teacher_open)+'</h2></div><div class=card><span class=muted>دروس بلا تغطية</span><h2>'+e(s.uncovered_lessons)+'</h2></div></div><h2>قائمة العمل</h2>'+(items.length?items.map(v=>'<div class="item '+(v.owner==='system'?'bad':'warn')+'"><span class=tag>Priority '+e(v.priority)+'</span> <span class=tag>'+e(v.owner)+'</span> <span class=tag>'+e(v.category)+'</span><br><b>'+e(v.title)+'</b><div class=muted>'+e(v.detail)+'</div><a class=btn href="'+e(v.path)+'">فتح مسار المعالجة</a></div>').join(''):'<div class="item ok">✅ لا توجد مهام مفتوحة</div>')+'<p class=muted>هذه القائمة تشخيصية فقط. لا تنفذ اعتمادًا، ولا تغير سؤالًا أو مصدرًا، ولا تنشئ اعتماد مدرس أو محتوى علميًا من خارج الأدلة الحالية.</p>'}
load();
</script></main></html>'''


@app.get(
    '/admin/acceptance-work-queue',
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
def acceptance_work_queue_page():
    """Render the protected, read-only acceptance evidence work queue."""
    return PAGE
