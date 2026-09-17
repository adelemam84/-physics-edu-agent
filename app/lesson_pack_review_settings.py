from __future__ import annotations

import json

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from .db import connect
from .lesson_pack_studio import _drain_pdf_cleanup, _queue_pdf_cleanup
from .lesson_studio_second_reviewer import reviewer_status
from .main import app
from .security import require_admin
from .services.lesson_pack_pdf_navigation import (
    FINAL_REVIEW_STYLES,
    normalize_final_review_settings,
)
from .services.rate_limit import enforce_request_policy


def _review_settings_row(job_id: str) -> dict:
    with connect() as con:
        row = con.execute(
            """SELECT id,pack_json,scientific_review_json,teacher_approved,
              pdf_student_object_key,pdf_teacher_object_key
              FROM lesson_pack_jobs WHERE id=%s""",
            (job_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Lesson Pack job not found")
    return dict(row)


def _clean_text(value: str | None, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


@app.get(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/final-review",
    dependencies=[Depends(require_admin)],
)
def get_lesson_pack_final_review_settings(job_id: str):
    row = _review_settings_row(job_id)
    pack = dict(row.get("pack_json") or {})
    if not pack:
        raise HTTPException(409, "Generate the Lesson Pack before configuring final review")
    return {
        "id": job_id,
        "settings": normalize_final_review_settings(pack),
        "teacher_approved": bool(row.get("teacher_approved")),
        "approval_will_be_invalidated_on_change": True,
    }


@app.post(
    "/api/admin/lesson-pack-studio/jobs/{job_id}/final-review",
    dependencies=[Depends(require_admin)],
)
def update_lesson_pack_final_review_settings(
    job_id: str,
    request: Request,
    style: str = Form("balanced"),
    title: str = Form(""),
    lead: str = Form(""),
    show_summary: bool = Form(True),
    show_quick_revision: bool = Form(True),
    show_laws: bool = Form(True),
    show_mistakes: bool = Form(True),
    show_checklist: bool = Form(True),
):
    enforce_request_policy(
        request,
        name="admin_lesson_pack_final_review_settings",
        default_limit=60,
        default_window_seconds=3600,
    )
    style = str(style or "balanced").strip().lower()
    if style not in FINAL_REVIEW_STYLES:
        raise HTTPException(422, "Invalid final-review style")

    requested = {
        "style": style,
        "title": _clean_text(title, 80),
        "lead": _clean_text(lead, 220),
        "show_summary": bool(show_summary),
        "show_quick_revision": bool(show_quick_revision),
        "show_laws": bool(show_laws),
        "show_mistakes": bool(show_mistakes),
        "show_checklist": bool(show_checklist),
    }

    with connect() as con:
        locked = con.execute(
            """SELECT pack_json,scientific_review_json,pdf_student_object_key,
              pdf_teacher_object_key FROM lesson_pack_jobs WHERE id=%s FOR UPDATE""",
            (job_id,),
        ).fetchone()
        if not locked:
            raise HTTPException(404, "Lesson Pack job not found")
        pack = dict(locked["pack_json"] or {})
        if not pack:
            raise HTTPException(409, "Generate the Lesson Pack before configuring final review")

        previous = normalize_final_review_settings(pack)
        candidate_pack = dict(pack)
        candidate_pack["final_review"] = requested
        normalized = normalize_final_review_settings(candidate_pack)
        changed = normalized != previous
        cleanup_keys: list[str | None] = []

        if changed:
            cleanup_keys = [
                locked["pdf_student_object_key"],
                locked["pdf_teacher_object_key"],
            ]
            _queue_pdf_cleanup(candidate_pack, cleanup_keys)
            next_status = (
                "scientific_review_required"
                if reviewer_status()["configured"] and not locked["scientific_review_json"]
                else "teacher_approval_required"
            )
            con.execute(
                """UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,teacher_approved=FALSE,
                  pdf_student_object_key=NULL,pdf_teacher_object_key=NULL,status=%s,
                  updated_at=now() WHERE id=%s""",
                (json.dumps(candidate_pack, ensure_ascii=False), next_status, job_id),
            )
        elif pack.get("final_review") != requested:
            # Persist the normalized explicit settings without invalidating approval
            # when they do not alter the rendered result.
            candidate_pack["final_review"] = requested
            con.execute(
                "UPDATE lesson_pack_jobs SET pack_json=%s::jsonb,updated_at=now() WHERE id=%s",
                (json.dumps(candidate_pack, ensure_ascii=False), job_id),
            )

    cleanup = _drain_pdf_cleanup(job_id) if changed else {"deleted": 0, "pending": 0}
    return {
        "id": job_id,
        "settings": normalized,
        "changed": changed,
        "approval_invalidated": changed,
        "pdfs_invalidated": changed,
        "cleanup": cleanup,
    }


def _settings_page(job_id: str) -> str:
    safe_id = json.dumps(job_id)
    return r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>إعدادات المراجعة النهائية</title><style>
*{box-sizing:border-box}body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:850px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:18px;margin:12px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}input,select,textarea,button{font:inherit;padding:10px;border:1px solid #ccd2dd;border-radius:10px;width:100%}textarea{min-height:90px;resize:vertical}button{cursor:pointer;background:#172033;color:#fff}.checks label{display:block;padding:8px 0}.checks input{width:auto;margin-left:7px}.muted{color:#667085}.ok{color:#067647}.warn{color:#b54708}</style><main>
<div class=box><a href="/admin/lesson-pack-studio/jobs/''' + job_id + r'''/preview">الرجوع لمعاينة الملزمة</a> · <a href="/admin/lesson-pack-studio">Lesson Pack Studio</a></div>
<div class=box><h1>تخصيص صفحة المراجعة النهائية</h1><p class=muted>التخصيص يغيّر العرض والترتيب فقط، ولا يضيف معلومات علمية من خارج محتوى الملزمة المعتمد. أي تغيير فعلي يلغي الاعتماد النهائي وملفات PDF القديمة حتى تراجع النسخة الجديدة.</p></div>
<form id=f class=box><div class=grid><label>أسلوب المراجعة<select name=style id=style><option value=balanced>متوازن</option><option value=exam_focus>تركيز امتحان</option><option value=concept_focus>تثبيت المفاهيم</option></select></label><label>عنوان الصفحة<input name=title id=title maxlength=80 placeholder="المراجعة النهائية"></label></div><p><label>سطر التوجيه<textarea name=lead id=lead maxlength=220></textarea></label></p><div class=checks><label><input type=checkbox name=show_summary id=show_summary value=true> إظهار الخلاصة</label><label><input type=checkbox name=show_quick_revision id=show_quick_revision value=true> إظهار نقاط المراجعة السريعة</label><label><input type=checkbox name=show_laws id=show_laws value=true> إظهار القوانين</label><label><input type=checkbox name=show_mistakes id=show_mistakes value=true> إظهار الأخطاء الشائعة</label><label><input type=checkbox name=show_checklist id=show_checklist value=true> إظهار قائمة التأكد النهائية</label></div><button>حفظ الإعدادات</button><p id=msg class=muted></p></form>
<script>
const id=''' + safe_id + r''';
const fields=['show_summary','show_quick_revision','show_laws','show_mistakes','show_checklist'];
async function load(){let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/final-review');if(r.status===401){location.href='/admin/login';return}let x=await r.json();if(!r.ok){msg.textContent=JSON.stringify(x.detail||x);return}let s=x.settings;style.value=s.style;title.value=s.title;lead.value=s.lead;fields.forEach(k=>document.getElementById(k).checked=!!s[k]);}
f.addEventListener('submit',async e=>{e.preventDefault();msg.textContent='جارٍ الحفظ...';let fd=new FormData();fields.forEach(k=>{if(!document.getElementById(k).checked)fd.set(k,'false')});let r=await fetch('/api/admin/lesson-pack-studio/jobs/'+id+'/final-review',{method:'POST',body:fd});let x=await r.json();if(!r.ok){msg.textContent='خطأ: '+JSON.stringify(x.detail||x);return}msg.className=x.changed?'warn':'ok';msg.textContent=x.changed?'تم الحفظ. تم إلغاء الاعتماد السابق ونسخ PDF القديمة، راجع المعاينة ثم اعتمد من جديد.':'الإعدادات محفوظة ولا يوجد تغيير في النسخة.';await load();});load();
</script></main></html>'''


@app.get(
    "/admin/lesson-pack-studio/jobs/{job_id}/review-settings",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
def lesson_pack_final_review_settings_page(job_id: str):
    return HTMLResponse(_settings_page(job_id))
