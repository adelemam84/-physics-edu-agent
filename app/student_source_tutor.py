from __future__ import annotations

import base64
import os
import re

import fitz
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .advanced_learning import _source_tutor_context
from .db import connect
from .main import app
from .science_lesson_studio import _gemini_text
from .services.ai_governance import model_settings
from .services.rate_limit import enforce_subject_policy
from .services.source_asset_runtime import _source_pdf
from .student_security import resolve_student_code


MAX_SELECTED_PAGES = max(1, min(int(os.getenv("STUDENT_TUTOR_MAX_PAGES", "6")), 8))
MAX_INLINE_BYTES = max(
    1_000_000,
    min(int(os.getenv("STUDENT_TUTOR_MAX_INLINE_BYTES", str(10 * 1024 * 1024))), 16 * 1024 * 1024),
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u0600-\u06FF]{2,}", re.UNICODE)
_STOPWORDS = {
    "اشرح", "وضح", "يعني", "ماذا", "كيف", "لماذا", "ايه", "إيه", "ماهو", "ماهي",
    "هذا", "هذه", "ذلك", "على", "الى", "إلى", "من", "في", "عن", "هو", "هي", "the",
    "and", "what", "why", "how", "explain",
}


class TutorAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1200)


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text or "")
        if token.lower() not in _STOPWORDS
    }


def select_source_pages(rows: list[dict], question: str, limit: int = MAX_SELECTED_PAGES) -> list[dict]:
    """Select a small, source-faithful PDF window without using another model call."""
    if not rows:
        return []
    limit = max(1, min(int(limit), MAX_SELECTED_PAGES, len(rows)))
    if len(rows) <= limit:
        return sorted(rows, key=lambda x: int(x["page_number"]))

    question_terms = _terms(question)
    scored: list[tuple[int, int, dict]] = []
    for row in rows:
        page_terms = _terms(str(row.get("extracted_text") or ""))
        overlap = len(question_terms.intersection(page_terms))
        # Prefer earlier original pages only as a deterministic tie-breaker.
        scored.append((overlap, -int(row["page_number"]), row))

    if any(score > 0 for score, _, _ in scored):
        selected = [x[2] for x in sorted(scored, reverse=True)[:limit]]
        return sorted(selected, key=lambda x: int(x["page_number"]))

    # Broad/no-overlap questions get an even deterministic sample across the approved range.
    if limit == 1:
        return [rows[0]]
    indices = {
        round(i * (len(rows) - 1) / (limit - 1))
        for i in range(limit)
    }
    return [rows[i] for i in sorted(indices)]


def _selected_pdf(storage_url: str, original_pages: list[int]) -> bytes:
    raw = _source_pdf(storage_url)
    src = fitz.open(stream=raw, filetype="pdf")
    out = fitz.open()
    try:
        for page_number in original_pages:
            if page_number < 1 or page_number > src.page_count:
                raise HTTPException(409, "صفحة مصدر معتمدة خارج نطاق ملف PDF")
            out.insert_pdf(src, from_page=page_number - 1, to_page=page_number - 1)
        data = out.tobytes(garbage=4, deflate=True, clean=True)
    finally:
        out.close()
        src.close()
    return data


def _student_and_source(code: str, question: str) -> tuple[dict, dict, list[dict]]:
    with connect() as con:
        student = con.execute(
            "SELECT id,name FROM students WHERE external_code=%s",
            (code,),
        ).fetchone()
        if not student:
            raise HTTPException(404, "كود الطالب غير صحيح")

        context = _source_tutor_context(con, student["id"])
        if not context.get("available"):
            raise HTTPException(409, context.get("reason") or "لا يوجد مصدر شرح معتمد")

        lesson_id = int(context["lesson_id"])
        mapping = con.execute(
            """SELECT m.id mapping_id,m.lesson_id,m.document_id,m.start_page,m.end_page,
                     d.filename,d.storage_url,d.kind,d.status,l.title lesson_title
               FROM lesson_source_mappings m
               JOIN documents d ON d.id=m.document_id
               JOIN lessons l ON l.id=m.lesson_id
               WHERE m.lesson_id=%s
                 AND m.mapping_status='approved'
                 AND d.kind IN ('lesson','explanation','textbook','notes')
                 AND d.status='approved'
                 AND d.storage_url IS NOT NULL
               ORDER BY m.updated_at DESC,m.id DESC
               LIMIT 1""",
            (lesson_id,),
        ).fetchone()
        if not mapping:
            raise HTTPException(409, "مصدر الشرح المعتمد غير متاح حاليًا")

        pages = list(
            con.execute(
                """SELECT page_number,extracted_text
                   FROM document_pages
                   WHERE document_id=%s
                     AND page_number BETWEEN %s AND %s
                     AND extracted_text IS NOT NULL
                     AND btrim(extracted_text)<>''
                   ORDER BY page_number""",
                (mapping["document_id"], mapping["start_page"], mapping["end_page"]),
            ).fetchall()
        )

    expected = int(mapping["end_page"]) - int(mapping["start_page"]) + 1
    if len(pages) != expected:
        raise HTTPException(
            409,
            {
                "message": "مصدر الدرس المعتمد يحتاج إعادة فهرسة قبل استخدام المدرس الذكي",
                "expected_pages": expected,
                "indexed_pages": len(pages),
            },
        )
    selected = select_source_pages([dict(x) for x in pages], question)
    return dict(student), dict(mapping), selected


def _system_instruction(original_pages: list[int]) -> str:
    pages = "، ".join(str(x) for x in original_pages)
    return (
        "أنت مدرس فيزياء مساعد مرتبط حصريًا بمصدر PDF معتمد. "
        "أجب فقط بما يمكن إثباته من الصفحات المرفقة، ولا تستخدم معرفة عامة أو ذاكرة خارجية. "
        "إذا كانت الإجابة غير مدعومة بوضوح في الصفحات المرفقة فقل: "
        "«المصدر المعتمد المرفق لا يكفي للإجابة على هذا السؤال» ولا تخمّن. "
        "لا تنشئ أسئلة تدريب أو امتحان، ولا تمنح درجات، ولا تغيّر أو تعتمد أي محتوى. "
        "حافظ على الأرقام والوحدات والمعادلات والرموز كما تظهر في المصدر. "
        "إذا اعتمد الشرح على شكل أو رسم، صف فقط ما يظهر فعليًا في الصفحة. "
        f"الصفحات الأصلية المتاحة هي: {pages}. "
        "كل فقرة علمية يجب أن تتضمن استشهادًا بصفحة أصلية بالشكل [صفحة N]. "
        "استخدم العربية الواضحة المناسبة للطالب وبإجابة مركزة."
    )


@app.post("/api/student/source-tutor/ask")
def student_source_tutor_ask(payload: TutorAsk, request: Request):
    code = resolve_student_code(request)
    enforce_subject_policy(
        code,
        name="student_source_tutor",
        default_limit=20,
        default_window_seconds=3600,
    )
    student, mapping, selected = _student_and_source(code, payload.question)
    original_pages = [int(x["page_number"]) for x in selected]
    if not original_pages:
        raise HTTPException(409, "لا توجد صفحات مصدر صالحة للشرح")

    pdf_bytes = _selected_pdf(str(mapping["storage_url"]), original_pages)
    page_map = "؛ ".join(
        f"الصفحة {index + 1} في الملف المرفق = الصفحة الأصلية {page}"
        for index, page in enumerate(original_pages)
    )
    prompt = (
        f"سؤال الطالب: {payload.question}\n"
        f"خريطة الصفحات: {page_map}\n"
        "أجب من المصدر المرفق فقط، واستخدم أرقام الصفحات الأصلية في الاستشهادات."
    )

    if len(pdf_bytes) <= MAX_INLINE_BYTES:
        answer = _gemini_text(
            [
                {"text": prompt},
                {
                    "inlineData": {
                        "mimeType": "application/pdf",
                        "data": base64.b64encode(pdf_bytes).decode("ascii"),
                    }
                },
            ],
            _system_instruction(original_pages),
            task="student_source_tutor",
        )
        source_mode = "selected_pdf_pages"
    else:
        excerpts = "\n\n".join(
            f"[صفحة {row['page_number']}]\n{row['extracted_text']}"
            for row in selected
        )
        answer = _gemini_text(
            [{"text": prompt + "\n\nنص الصفحات المعتمدة:\n" + excerpts}],
            _system_instruction(original_pages),
            task="student_source_tutor",
        )
        source_mode = "approved_extracted_text_fallback"

    return {
        "student": {"id": student["id"], "name": student["name"]},
        "lesson": {
            "id": mapping["lesson_id"],
            "title": mapping["lesson_title"],
        },
        "answer": answer,
        "source": {
            "document_id": mapping["document_id"],
            "filename": mapping["filename"],
            "mapped_pages": {
                "start": mapping["start_page"],
                "end": mapping["end_page"],
            },
            "selected_pages": original_pages,
            "mode": source_mode,
        },
        "model": model_settings()["gemini_lesson_studio"],
        "integrity": {
            "source_only": True,
            "approved_mapping_only": True,
            "generated_questions": False,
            "grading": False,
            "auto_approval": False,
            "chat_history_stored": False,
        },
    }


TUTOR_PAGE = r'''<!doctype html><html lang="ar" dir="rtl">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>المدرس المرتبط بالمصدر</title>
<style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--brand:#2447a8}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:900px;margin:auto;padding:16px}.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}
textarea,button{font:inherit;border:1px solid #cbd2df;border-radius:10px;padding:11px}textarea{width:100%;min-height:110px;resize:vertical}button{cursor:pointer;background:var(--brand);color:#fff}button:disabled{opacity:.55;cursor:not-allowed}
.muted{color:var(--muted)}.answer{white-space:pre-wrap;line-height:1.9;background:#f8fafc;border-radius:12px;padding:14px}.source{background:#eef4ff;border-radius:10px;padding:10px;margin-top:10px}
a{color:var(--brand);text-decoration:none}textarea:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid #84adff;outline-offset:2px}
@media(max-width:650px){main{padding:9px}.box{border-radius:14px;padding:13px}}
</style><main>
<div class=box><a href="/student/learning-suite">← مركز التعلم الذكي</a><h1>المدرس المرتبط بالمصدر</h1><p class=muted>الإجابة تأتي فقط من صفحات PDF المعتمدة للدرس المستهدف. لا يتم حفظ سجل محادثة دائم.</p><div id=context class=muted>جارٍ تحميل الدرس المستهدف...</div></div>
<div class=box><label for=q><b>اسأل عن الدرس</b></label><textarea id=q maxlength=1200 placeholder="مثال: لماذا تزداد شدة التيار عند ثبات الجهد ونقص المقاومة؟"></textarea><button id=ask onclick=askTutor()>اسأل من المصدر</button><div id=msg class=muted aria-live=polite></div></div>
<div class=box><h2>الإجابة</h2><div id=answer class=answer>لا توجد إجابة بعد.</div><div id=source class=source style="display:none"></div></div>
<script>
const e=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
async function loadContext(){
  let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));
  if(!s.authenticated){location.href='/student';return}
  let r=await fetch('/api/student/learning-suite',{cache:'no-store'}),x=await r.json().catch(()=>null);
  if(!r.ok){context.textContent='تعذر تحميل الدرس المستهدف.';return}
  let t=x.source_grounded_tutor;
  context.innerHTML=t?.available?('الدرس المستهدف: <b>'+e(t.lesson_title)+'</b> · المصدر: '+e(t.source.filename)+' · الصفحات '+e(t.source.start_page)+'–'+e(t.source.end_page)):'لا يوجد مصدر شرح معتمد متاح حاليًا.';
  ask.disabled=!t?.available;
}
async function askTutor(){
  let question=q.value.trim();if(question.length<3){msg.textContent='اكتب سؤالًا أوضح أولًا.';return}
  ask.disabled=true;msg.textContent='جارٍ البحث داخل صفحات المصدر المعتمدة...';answer.textContent='';source.style.display='none';
  try{
    let r=await fetch('/api/student/source-tutor/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})}),x=await r.json().catch(()=>null);
    if(!r.ok){msg.textContent=typeof x?.detail==='string'?x.detail:(x?.detail?.message||'تعذر الحصول على إجابة من المصدر');return}
    answer.textContent=x.answer||'لم يرجع المصدر إجابة.';
    source.style.display='block';
    source.innerHTML='<b>المصدر:</b> '+e(x.source.filename)+' · الصفحات المستخدمة: '+e((x.source.selected_pages||[]).join('، '))+'<br><span class=muted>الوضع: '+e(x.source.mode)+' · لا يتم حفظ المحادثة.</span>';
    msg.textContent='تمت الإجابة من المصدر المعتمد فقط.';
  }catch(err){msg.textContent='تعذر الاتصال بالمدرس المرتبط بالمصدر.'}
  finally{ask.disabled=false}
}
loadContext();
</script></main></html>'''


@app.get("/student/source-tutor", response_class=HTMLResponse)
def student_source_tutor_page():
    return TUTOR_PAGE
