from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .corpus_public_status import current_curriculum_phase2_status
from .main import app
from .security import require_admin


def _completion_snapshot() -> dict:
    status = current_curriculum_phase2_status()
    if not status.get("active"):
        return {
            "active": False,
            "status": "not_configured",
            "next_actions": ["Configure an active third-secondary physics curriculum source."],
        }

    questions = status.get("questions") or {}
    quizzes = status.get("quizzes") or {}
    qa_rows = status.get("qa_open_by_reason") or []

    total = int(questions.get("total_questions") or 0)
    approved = int(questions.get("approved_questions") or 0)
    qa_open = sum(int(row.get("total") or 0) for row in qa_rows)
    pending_pages = sum(
        int(row.get("total") or 0)
        for row in qa_rows
        if row.get("reason_code") == "visual_transcription_required"
    )
    published = int(quizzes.get("published") or 0)

    remaining = max(total - approved, 0)
    approval_pct = round((approved / total) * 100, 1) if total else 0.0

    actions: list[str] = []
    if pending_pages:
        actions.append(f"Complete visual review for {pending_pages} pending source page(s).")
    if qa_open:
        actions.append(f"Resolve {qa_open} open question QA note(s) without inventing missing source text.")
    if remaining:
        actions.append(
            f"Review/transcribe and academically validate the remaining {remaining} question candidate(s) from the approved PDF source."
        )
    if approved and not published:
        actions.append("Publish a source-grounded diagnostic quiz from the approved current-curriculum questions.")
    if not actions:
        actions.append("Current question corpus gates are complete. Continue only with approved source expansion.")

    phase = "complete"
    if pending_pages:
        phase = "page_review"
    elif qa_open or remaining:
        phase = "question_review"
    elif not published:
        phase = "quiz_publication"

    return {
        **status,
        "total_questions": total,
        "approved_questions": approved,
        "qa_open": qa_open,
        "pending_visual_pages": pending_pages,
        "published_quizzes": published,
        "phase": phase,
        "remaining_questions": remaining,
        "approval_percentage": approval_pct,
        "next_actions": actions,
        "integrity_rule": "PDF source remains authoritative; unreviewed image-only content must never be silently invented or auto-approved.",
    }


@app.get("/api/admin/current-corpus/ops", dependencies=[Depends(require_admin)])
def current_corpus_ops_api():
    return _completion_snapshot()


@app.get("/admin/current-corpus", response_class=HTMLResponse)
def current_corpus_ops_page():
    snapshot = _completion_snapshot()
    rows = "".join(f"<li>{a}</li>" for a in snapshot.get("next_actions", []))
    return HTMLResponse(
        f"""<!doctype html><html lang='ar' dir='rtl'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>تشغيل بنك أسئلة المنهج الحالي</title>
<style>body{{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}}main{{max-width:960px;margin:auto;padding:20px}}.box{{background:#fff;border-radius:16px;padding:18px;margin:12px 0;box-shadow:0 3px 14px #0001}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.card{{border:1px solid #e5e7eb;border-radius:12px;padding:14px}}.n{{font-size:28px;font-weight:800}}.muted{{color:#667085}}.warn{{color:#b54708}}.ok{{color:#067647}}ul{{line-height:1.9}}</style>
<main><div class='box'><h1>تشغيل بنك أسئلة المنهج الحالي</h1><p class='muted'>لوحة تشغيل مباشرة لإكمال بنك 2026/2027 مع الحفاظ على قاعدة المصدر PDF فقط.</p></div>
<div class='box grid'>
<div class='card'><div class='muted'>إجمالي المرشحين</div><div class='n'>{snapshot.get('total_questions',0)}</div></div>
<div class='card'><div class='muted'>المعتمد</div><div class='n'>{snapshot.get('approved_questions',0)}</div></div>
<div class='card'><div class='muted'>المتبقي</div><div class='n'>{snapshot.get('remaining_questions',0)}</div></div>
<div class='card'><div class='muted'>نسبة الاعتماد</div><div class='n'>{snapshot.get('approval_percentage',0)}%</div></div>
<div class='card'><div class='muted'>QA مفتوح</div><div class='n'>{snapshot.get('qa_open',0)}</div></div>
<div class='card'><div class='muted'>اختبارات منشورة</div><div class='n'>{snapshot.get('published_quizzes',0)}</div></div>
</div>
<div class='box'><h2>مساعد المراجعة البصرية</h2><p class='muted'>يولد Draft من القصاصة الأصلية فقط بدون اعتماد تلقائي.</p><p><a href='/admin/workflow?quality_issue=any'>فتح مسار مراجعة الأسئلة</a> · <a href='/admin/research-engine'>محرك المصادر</a></p><button onclick="fetch('/api/admin/current-corpus/visual-review/batch-suggest?limit=5',{method:'POST'}).then(r=>r.json()).then(x=>alert('تم تجهيز '+x.processed+' اقتراحات للمراجعة')).catch(e=>alert(e))">تجهيز 5 اقتراحات بصرية</button></div><div class='box'><h2>المرحلة الحالية</h2><p><b>{snapshot.get('phase','not_configured')}</b> · الحالة: <b>{snapshot.get('status','active')}</b></p><h3>الإجراءات التالية</h3><ul>{rows}</ul></div>
<div class='box'><h2>قاعدة النزاهة</h2><p class='warn'>{snapshot.get('integrity_rule','')}</p></div></main></html>"""
    )
