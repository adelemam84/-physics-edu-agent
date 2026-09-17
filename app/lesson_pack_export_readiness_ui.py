from __future__ import annotations

from . import lesson_pack_studio_ui


_CSS_ANCHOR = ".preview-meta{text-align:center;color:#475467;font-weight:700}"
_READINESS_CSS = """
.readiness-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}.readiness-card{border:1px solid #e4e7ec;border-radius:12px;padding:12px;background:#fcfcfd}.readiness-card.ready{border-color:#abefc6;background:#ecfdf3}.readiness-card.blocked{border-color:#fecdca;background:#fef3f2}.readiness-card.pending{border-color:#fedf89;background:#fffaeb}.readiness-card h3{margin:0 0 6px}.readiness-list{margin:8px 0 0;padding-right:20px}#studentPdf.disabled,#teacherPdf.disabled{opacity:.45;pointer-events:none;text-decoration:none}.status-pill{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;background:#f2f4f7;color:#344054}
""".strip()

_PANEL_ANCHOR = '<div class=box><h2>إجراءات الجودة</h2>'
_READINESS_PANEL = """<div class=box id=exportReadinessBox><h2>جاهزية التصدير النهائي</h2><p class=muted>يتم فحص بنية الملزمة وملف PDF الفعلي قبل السماح بالتصدير. سلامة الـPreflight لا تستبدل اعتماد المدرس؛ التصدير النهائي يحتاج الاثنين معًا.</p><div id=exportReadiness class=readiness-grid><div class=readiness-card><p class=muted>جارٍ فحص نسخة الطالب ونسخة المدرس...</p></div></div></div>
""" + _PANEL_ANCHOR

_STATE_ANCHOR = "let data,previewEdition='student',previewPage=1,previewTotal=0,previewManifestCache={};"
_STATE_REPLACEMENT = _STATE_ANCHOR + "\nlet exportReadinessReports={};"

_INVALIDATE_ANCHOR = "function invalidatePreview(){previewManifestCache={};}"
_READINESS_SCRIPT = r"""function invalidatePreview(){previewManifestCache={};exportReadinessReports={};}
function blockerIds(report){let ids=[];for(let part of [report&&report.pack,report&&report.pdf]){for(let x of ((part&&part.blocking_failures)||[])){if(!ids.includes(x))ids.push(x)}}return ids}
function readinessCard(report,label){if(!report)return '<div class="readiness-card blocked"><h3>'+label+'</h3><p class=bad>تعذر تنفيذ فحص الجاهزية.</p></div>';let tech=!!report.preflight_ready,approved=!!report.teacher_approved,ready=!!report.export_ready;let cls=ready?'ready':(tech?'pending':'blocked');let badge=ready?'✅ جاهز للتصدير':(tech?'⏳ ينتظر اعتماد المدرس':'⛔ فحص التصدير غير ناجح');let blockers=blockerIds(report);let details=blockers.length?'<ul class=readiness-list>'+blockers.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>':'<p class=muted>لا توجد موانع تقنية في ملف PDF.</p>';return '<div class="readiness-card '+cls+'"><h3>'+label+'</h3><span class=status-pill>'+badge+'</span><p>Preflight: '+(tech?'✅':'❌')+' · اعتماد المدرس: '+(approved?'✅':'⏳')+'</p>'+details+'</div>'}
function applyExportReadiness(){let student=exportReadinessReports.student,teacher=exportReadinessReports.teacher;exportReadiness.innerHTML=readinessCard(student,'نسخة الطالب')+readinessCard(teacher,'نسخة المدرس');studentPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=student';teacherPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=teacher';let sr=!!(student&&student.export_ready),tr=!!(teacher&&teacher.export_ready);studentPdf.classList.toggle('disabled',!sr);teacherPdf.classList.toggle('disabled',!tr);studentPdf.setAttribute('aria-disabled',sr?'false':'true');teacherPdf.setAttribute('aria-disabled',tr?'false':'true');studentPdf.tabIndex=sr?0:-1;teacherPdf.tabIndex=tr?0:-1;}
async function refreshExportReadiness(){if(!(data&&data.pack_json)){exportReadinessReports={};exportReadiness.innerHTML='<div class="readiness-card blocked"><p class=muted>أنشئ الملزمة أولًا لتشغيل فحص الجاهزية.</p></div>';applyExportReadiness();return}let editions=['student','teacher'];let results=await Promise.all(editions.map(async edition=>{try{let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/preflight?edition='+edition);let x=await r.json();return [edition,r.ok?x:null]}catch(_){return [edition,null]}}));exportReadinessReports=Object.fromEntries(results);applyExportReadiness();}
"""

_EXPORT_ANCHOR = "studentPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=student';teacherPdf.href='/api/admin/lesson-pack-studio/jobs/'+id+'/export-pdf?edition=teacher';studentPdf.style.opacity=teacherPdf.style.opacity=data.teacher_approved?'1':'.45';studentPdf.style.pointerEvents=teacherPdf.style.pointerEvents=data.teacher_approved?'auto':'none';await refreshPreview(previewEdition,previewPage);"
_EXPORT_REPLACEMENT = "await refreshExportReadiness();await refreshPreview(previewEdition,previewPage);"

_APPROVE_ANCHOR = "action.textContent=r.ok?'✅ تم الاعتماد النهائي. يمكن تنزيل نسختي PDF.':JSON.stringify(x.detail||x);await load()"
_APPROVE_REPLACEMENT = "action.textContent=r.ok?'✅ تم الاعتماد النهائي. يتم الآن تأكيد جاهزية نسختي PDF.':JSON.stringify(x.detail||x);if(r.ok)invalidatePreview();await load()"


def enhance_lesson_pack_preview_html(html: str) -> str:
    """Add export-readiness UX without weakening the server-side export gate."""
    required = (_CSS_ANCHOR, _PANEL_ANCHOR, _STATE_ANCHOR, _INVALIDATE_ANCHOR, _EXPORT_ANCHOR)
    if not all(anchor in html for anchor in required):
        return html
    html = html.replace(_CSS_ANCHOR, _CSS_ANCHOR + _READINESS_CSS, 1)
    html = html.replace(_PANEL_ANCHOR, _READINESS_PANEL, 1)
    html = html.replace(_STATE_ANCHOR, _STATE_REPLACEMENT, 1)
    html = html.replace(_INVALIDATE_ANCHOR, _READINESS_SCRIPT, 1)
    html = html.replace(_EXPORT_ANCHOR, _EXPORT_REPLACEMENT, 1)
    if _APPROVE_ANCHOR in html:
        html = html.replace(_APPROVE_ANCHOR, _APPROVE_REPLACEMENT, 1)
    return html


_base_preview_page = lesson_pack_studio_ui._preview_page


def _preview_page_with_export_readiness(job_id: str) -> str:
    return enhance_lesson_pack_preview_html(_base_preview_page(job_id))


# The registered route resolves `_preview_page` from lesson_pack_studio_ui globals at
# request time, so this safely composes on top of the existing UI without duplicating it.
lesson_pack_studio_ui._preview_page = _preview_page_with_export_readiness
