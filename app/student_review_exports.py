from __future__ import annotations

import base64
import html
import io

import fitz
from PIL import Image, ImageOps
from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .db import connect
from .main import app
from .services.source_asset_runtime import render_asset_bytes
from .student_security import resolve_student_code
from .services.rate_limit import enforce_subject_policy


class StudentReviewExportRequest(BaseModel):
    """Configure one student-owned review export; ownership comes from the signed session."""

    max_questions: int = Field(default=100, ge=1, le=200)


def _esc(value: object) -> str:
    """Escape source and student text before inserting it into the PDF HTML."""
    return html.escape(str(value or ""), quote=True)


def _compact_asset_data_uri(raw: bytes) -> str:
    """Downsample one source-backed question image for a bounded review PDF."""
    if not raw:
        raise ValueError("Empty question asset")
    with Image.open(io.BytesIO(raw)) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=84, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _attach_asset_data(rows: list[dict]) -> list[dict]:
    """Attach bounded exact-source visuals; failures stay explicit and are never recreated."""
    prepared: list[dict] = []
    for raw_row in rows:
        row = dict(raw_row)
        row["asset_data_uri"] = None
        row["asset_unavailable"] = False
        if row.get("asset_object_key"):
            asset_row = {
                "object_key": row["asset_object_key"],
                "page_number": row.get("asset_page_number"),
                "crop_x": row.get("crop_x"),
                "crop_y": row.get("crop_y"),
                "crop_width": row.get("crop_width"),
                "crop_height": row.get("crop_height"),
                "storage_url": row.get("asset_storage_url"),
            }
            try:
                row["asset_data_uri"] = _compact_asset_data_uri(render_asset_bytes(asset_row))
            except Exception:
                row["asset_unavailable"] = True
        prepared.append(row)
    return prepared


def _attempt_bundle(attempt_id: int, student_code: str) -> tuple[dict, list[dict]]:
    """Read one completed attempt only when it belongs to the supplied student code."""
    code = student_code.strip()
    if not code:
        raise HTTPException(400, "أدخل كود الطالب")
    with connect() as con:
        attempt = con.execute(
            """SELECT a.id,a.student_id,a.quiz_id,a.score,a.max_score,a.started_at,a.completed_at,a.submitted_at,
                      s.name student_name,s.external_code,qz.title quiz_title
               FROM attempts a
               JOIN students s ON s.id=a.student_id
               LEFT JOIN quizzes qz ON qz.id=a.quiz_id
               WHERE a.id=%s AND s.external_code=%s""",
            (attempt_id, code),
        ).fetchone()
        if not attempt:
            raise HTTPException(404, "المحاولة غير موجودة")
        if attempt["completed_at"] is None:
            raise HTTPException(409, "يتم إنشاء ملف المراجعة بعد تسليم الاختبار فقط")
        rows = list(
            con.execute(
                """SELECT aa.question_id,aa.answer_text,aa.is_correct,aa.points_awarded,
                          qq.position,qq.points,
                          q.text_verbatim,q.accepted_answer,q.solution_verbatim,q.difficulty,q.question_type,
                          coalesce(q.source_page,q.page) source_page,
                          l.title lesson_title,l.chapter,
                          d.filename source_filename,
                          qa.object_key asset_object_key,qa.page_number asset_page_number,
                          qa.crop_x,qa.crop_y,qa.crop_width,qa.crop_height,
                          ad.storage_url asset_storage_url
                   FROM attempt_answers aa
                   JOIN questions q ON q.id=aa.question_id
                   LEFT JOIN quiz_questions qq ON qq.quiz_id=%s AND qq.question_id=aa.question_id
                   LEFT JOIN lessons l ON l.id=q.lesson_id
                   LEFT JOIN documents d ON d.id=q.document_id
                   LEFT JOIN question_assets qa ON qa.question_id=q.id
                   LEFT JOIN documents ad ON ad.id=qa.document_id
                   WHERE aa.attempt_id=%s
                   ORDER BY qq.position NULLS LAST,aa.id""",
                (attempt["quiz_id"], attempt_id),
            ).fetchall()
        )
    return dict(attempt), _attach_asset_data([dict(x) for x in rows])


def _mistake_bundle(student_code: str, limit: int) -> tuple[dict, list[dict]]:
    """Read the student's distinct historical mistakes with the latest wrong answer and source asset."""
    code = student_code.strip()
    if not code:
        raise HTTPException(400, "أدخل كود الطالب")
    limit = min(max(int(limit), 1), 200)
    with connect() as con:
        student = con.execute(
            "SELECT id,name,external_code FROM students WHERE external_code=%s",
            (code,),
        ).fetchone()
        if not student:
            raise HTTPException(404, "كود الطالب غير صحيح")
        rows = list(
            con.execute(
                """WITH wrong AS (
                     SELECT aa.question_id,count(*) wrong_count,max(a.completed_at) last_wrong
                     FROM attempt_answers aa
                     JOIN attempts a ON a.id=aa.attempt_id
                     WHERE a.student_id=%s AND a.completed_at IS NOT NULL AND aa.is_correct=FALSE
                     GROUP BY aa.question_id
                   ),
                   latest_wrong AS (
                     SELECT DISTINCT ON (aa.question_id)
                            aa.question_id,aa.answer_text latest_student_answer,a.completed_at
                     FROM attempt_answers aa
                     JOIN attempts a ON a.id=aa.attempt_id
                     WHERE a.student_id=%s AND a.completed_at IS NOT NULL AND aa.is_correct=FALSE
                     ORDER BY aa.question_id,a.completed_at DESC NULLS LAST,aa.id DESC
                   )
                   SELECT q.id question_id,q.text_verbatim,q.accepted_answer,q.solution_verbatim,
                          q.difficulty,q.question_type,coalesce(q.source_page,q.page) source_page,
                          l.title lesson_title,l.chapter,d.filename source_filename,
                          w.wrong_count,w.last_wrong,lw.latest_student_answer answer_text,
                          FALSE is_correct,NULL::numeric points_awarded,NULL::integer position,NULL::numeric points,
                          qa.object_key asset_object_key,qa.page_number asset_page_number,
                          qa.crop_x,qa.crop_y,qa.crop_width,qa.crop_height,
                          ad.storage_url asset_storage_url
                   FROM wrong w
                   JOIN latest_wrong lw ON lw.question_id=w.question_id
                   JOIN questions q ON q.id=w.question_id
                   LEFT JOIN lessons l ON l.id=q.lesson_id
                   LEFT JOIN documents d ON d.id=q.document_id
                   LEFT JOIN question_assets qa ON qa.question_id=q.id
                   LEFT JOIN documents ad ON ad.id=qa.document_id
                   ORDER BY w.last_wrong DESC NULLS LAST,w.wrong_count DESC,q.id
                   LIMIT %s""",
                (student["id"], student["id"], limit),
            ).fetchall()
        )
    return dict(student), _attach_asset_data([dict(x) for x in rows])


def _review_html(
    *,
    title: str,
    subtitle: str,
    rows: list[dict],
    mistakes_only: bool,
    score_line: str | None = None,
) -> str:
    """Build source-only Arabic review HTML for PDF composition."""
    cards: list[str] = []
    for index, row in enumerate(rows, 1):
        correct = row.get("is_correct") is True
        status = "إجابة صحيحة" if correct else "تحتاج مراجعة"
        status_class = "ok" if correct else "bad"
        position = row.get("position")
        label = f"سؤال {position}" if position is not None else f"سؤال مراجعة {index}"
        lesson = row.get("lesson_title") or "غير مصنف"
        meta_bits = [str(lesson)]
        if row.get("difficulty"):
            meta_bits.append(str(row["difficulty"]))
        if row.get("wrong_count") is not None:
            meta_bits.append(f"تكرر الخطأ {row['wrong_count']} مرة")
        source_bits: list[str] = []
        if row.get("source_filename"):
            source_bits.append(str(row["source_filename"]))
        if row.get("source_page"):
            source_bits.append(f"صفحة {row['source_page']}")
        source_line = " · ".join(source_bits)

        asset_html = ""
        if row.get("asset_data_uri"):
            asset_html = (
                '<div class="asset-wrap"><img class="asset" src="'
                + _esc(row["asset_data_uri"])
                + '" alt="صورة السؤال الأصلية"></div>'
            )
        elif row.get("asset_unavailable"):
            asset_html = '<div class="asset-missing">صورة المصدر المرتبطة بالسؤال غير متاحة مؤقتًا؛ لم يتم إنشاء رسم بديل.</div>'

        solution = ""
        if row.get("solution_verbatim"):
            solution = '<div class="solution"><b>الحل من المصدر:</b><br>' + _esc(row["solution_verbatim"]).replace("\n", "<br>") + "</div>"

        cards.append(
            f'''<section class="question-card">
              <div class="question-head"><b>{_esc(label)}</b><span class="{status_class}">{_esc(status)}</span></div>
              <div class="meta">{_esc(" · ".join(meta_bits))}</div>
              {asset_html}
              <div class="question-text">{_esc(row.get("text_verbatim")).replace(chr(10), "<br>")}</div>
              <div class="answer student-answer"><b>إجابة الطالب:</b> {_esc(row.get("answer_text") or "بدون إجابة")}</div>
              <div class="answer accepted-answer"><b>الإجابة المعتمدة:</b> {_esc(row.get("accepted_answer") or "—")}</div>
              {solution}
              {f'<div class="source">المصدر: {_esc(source_line)}</div>' if source_line else ''}
            </section>'''
        )

    body = "".join(cards)
    if not body:
        body = '<section class="empty">لا توجد أخطاء مسجلة في المحاولات المكتملة حتى الآن.</section>'

    scope_note = (
        "هذا الملف يجمع الأسئلة التي أخطأت فيها فقط لمراجعتها لاحقًا."
        if mistakes_only
        else "هذا الملف يحفظ محاولة الاختبار وإجاباتك والتصحيح بعد التسليم."
    )
    return f'''<article dir="rtl" lang="ar">
      <header>
        <div class="brand">Science Education Platform</div>
        <h1>{_esc(title)}</h1>
        <div class="subtitle">{_esc(subtitle)}</div>
        {f'<div class="score">{_esc(score_line)}</div>' if score_line else ''}
        <div class="scope-note">{_esc(scope_note)}</div>
      </header>
      {body}
      <footer>مادة مراجعة شخصية مبنية فقط على أسئلة وإجابات محفوظة في المنصة. لا يتم اختراع سؤال أو حل أو رسم.</footer>
    </article>'''


_REVIEW_CSS = """
body { font-family: sans-serif; font-size: 11.5pt; line-height: 1.7; color: #172033; }
article { direction: rtl; }
header { border-bottom: 2px solid #2447a8; padding-bottom: 12px; margin-bottom: 14px; }
.brand { color: #475467; font-size: 9pt; }
h1 { font-size: 22pt; margin: 4px 0; }
.subtitle,.meta,.source,footer { color: #667085; font-size: 9pt; }
.score { font-size: 14pt; font-weight: bold; margin-top: 7px; }
.scope-note { background: #eef4ff; border: 1px solid #b2ccff; padding: 7px 10px; margin-top: 8px; }
.question-card { border: 1px solid #d0d5dd; border-radius: 8px; padding: 10px; margin: 10px 0 14px; }
.question-head { display: flex; justify-content: space-between; gap: 10px; }
.ok { color: #067647; font-weight: bold; }
.bad { color: #b42318; font-weight: bold; }
.question-text { font-size: 12.5pt; font-weight: 600; margin: 8px 0; }
.answer { padding: 6px 8px; margin: 5px 0; border-radius: 6px; }
.student-answer { background: #fff7ed; }
.accepted-answer { background: #ecfdf3; }
.solution { background: #f8fafc; border-right: 4px solid #667085; padding: 8px; margin: 7px 0; }
.asset-wrap { text-align: center; margin: 8px 0; }
.asset { max-width: 100%; max-height: 380px; }
.asset-missing { background: #fffaeb; border: 1px solid #fedf89; padding: 7px; margin: 7px 0; }
.source { border-top: 1px dashed #d0d5dd; padding-top: 5px; margin-top: 7px; }
.empty { padding: 30px; text-align: center; border: 1px solid #d0d5dd; background: #f8fafc; }
footer { border-top: 1px solid #d0d5dd; margin-top: 18px; padding-top: 7px; }
"""


def render_student_review_pdf(
    *,
    title: str,
    subtitle: str,
    rows: list[dict],
    mistakes_only: bool,
    score_line: str | None = None,
) -> bytes:
    """Render a bounded multi-page A4 Arabic student review PDF with optional source visuals."""
    page = fitz.paper_rect("a4")
    content_rect = fitz.Rect(page.x0 + 38, page.y0 + 40, page.x1 - 38, page.y1 - 42)
    html_text = _review_html(
        title=title,
        subtitle=subtitle,
        rows=rows,
        mistakes_only=mistakes_only,
        score_line=score_line,
    )
    story = fitz.Story(html=html_text, user_css=_REVIEW_CSS)
    output = io.BytesIO()
    writer = fitz.DocumentWriter(output)

    def rectfn(rect_num: int, filled: bool):
        if rect_num > 300:
            raise RuntimeError("Student review PDF exceeded safe page limit")
        return page, content_rect, None

    try:
        story.write(writer, rectfn)
    finally:
        writer.close()

    data = output.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid student review PDF output")

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        total = doc.page_count
        for number, pdf_page in enumerate(doc, 1):
            pdf_page.insert_text(
                (pdf_page.rect.width - 72, pdf_page.rect.height - 14),
                f"{number} / {total}",
                fontsize=8,
                color=(0.4, 0.4, 0.4),
            )
        metadata = dict(doc.metadata or {})
        metadata.update({"title": title, "author": "Science Education Platform", "subject": subtitle})
        doc.set_metadata(metadata)
        data = doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
    return data


@app.post("/api/student/attempts/{attempt_id}/review-pdf")
def student_attempt_review_pdf(attempt_id: int, payload: StudentReviewExportRequest, request: Request):
    """Download one completed student-owned attempt with answers and source-backed correction."""
    code = resolve_student_code(request)
    enforce_subject_policy(
        code,
        name='student_review_pdf',
        default_limit=20,
        default_window_seconds=3600,
    )
    attempt, rows = _attempt_bundle(attempt_id, code)
    max_score = float(attempt.get("max_score") or 0)
    score = float(attempt.get("score") or 0)
    percentage = round(score / max_score * 100, 1) if max_score else 0.0
    data = render_student_review_pdf(
        title=f"مراجعة الاختبار — {attempt.get('quiz_title') or 'اختبار'}",
        subtitle=f"الطالب: {attempt.get('student_name') or ''} · محاولة #{attempt_id}",
        rows=rows,
        mistakes_only=False,
        score_line=f"الدرجة: {score:g} / {max_score:g} · {percentage:g}%",
    )
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="attempt-{attempt_id}-review.pdf"', "Cache-Control": "no-store"},
    )


@app.post("/api/student/review/mistakes-pdf")
def student_mistakes_review_pdf(payload: StudentReviewExportRequest, request: Request):
    """Download a deduplicated personal mistake notebook from completed attempts."""
    code = resolve_student_code(request, payload.student_code)
    enforce_subject_policy(
        code,
        name='student_review_pdf',
        default_limit=20,
        default_window_seconds=3600,
    )
    student, rows = _mistake_bundle(code, payload.max_questions)
    data = render_student_review_pdf(
        title="مذكرة أخطائي",
        subtitle=f"الطالب: {student.get('name') or ''} · {len(rows)} سؤال للمراجعة",
        rows=rows,
        mistakes_only=True,
    )
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="my-mistakes-review.pdf"', "Cache-Control": "no-store"},
    )
