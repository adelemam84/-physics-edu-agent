from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .main import app
from .db import connect
from .security import require_admin


@app.get("/api/admin/diagnostics", dependencies=[Depends(require_admin)])
def diagnostics():
    with connect() as con:
        checks = [
            {
                "id": "unassigned_documents",
                "name": "ملفات PDF غير مصنفة أكاديميًا",
                "severity": "warning",
                "count": con.execute("""SELECT count(*) n FROM documents
                    WHERE subject_id IS NULL OR grade_level_id IS NULL
                       OR curriculum_version_id IS NULL OR term_id IS NULL""").fetchone()["n"],
            },
            {
                "id": "orphan_questions",
                "name": "أسئلة بدون مستند مصدر",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n FROM questions q
                    LEFT JOIN documents d ON d.id=q.document_id
                    WHERE q.document_id IS NULL OR d.id IS NULL""").fetchone()["n"],
            },
            {
                "id": "approved_without_asset",
                "name": "أسئلة معتمدة بدون قصاصة مصدر",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n FROM questions q
                    WHERE q.approved=TRUE
                      AND NOT EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)""").fetchone()["n"],
            },
            {
                "id": "approved_without_answer",
                "name": "أسئلة معتمدة بدون إجابة معتمدة",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n FROM questions
                    WHERE approved=TRUE AND (accepted_answer IS NULL OR btrim(accepted_answer)='')""").fetchone()["n"],
            },
            {
                "id": "approved_incomplete_context",
                "name": "أسئلة معتمدة بتصنيف أكاديمي غير مكتمل",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n FROM questions q
                    WHERE q.approved=TRUE AND (
                      q.subject_id IS NULL OR q.grade_level_id IS NULL OR
                      q.curriculum_version_id IS NULL OR q.term_id IS NULL OR
                      q.unit_id IS NULL OR q.lesson_id IS NULL OR
                      NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) OR
                      NOT EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
                    )""").fetchone()["n"],
            },
            {
                "id": "duplicate_document_hashes",
                "name": "ملفات مكررة حسب SHA-256",
                "severity": "warning",
                "count": con.execute("""SELECT count(*) n FROM (
                    SELECT file_sha256 FROM document_files
                    WHERE file_sha256 IS NOT NULL
                    GROUP BY file_sha256 HAVING count(*)>1
                ) x""").fetchone()["n"],
            },
            {
                "id": "quizzes_with_unapproved_questions",
                "name": "اختبارات تحتوي سؤالًا غير معتمد",
                "severity": "error",
                "count": con.execute("""SELECT count(DISTINCT qq.quiz_id) n
                    FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id
                    WHERE q.approved=FALSE""").fetchone()["n"],
            },
            {
                "id": "attempt_answers_outside_quiz",
                "name": "إجابات محاولات لسؤال خارج الاختبار",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n
                    FROM attempt_answers aa
                    JOIN attempts a ON a.id=aa.attempt_id
                    LEFT JOIN quiz_questions qq ON qq.quiz_id=a.quiz_id AND qq.question_id=aa.question_id
                    WHERE qq.question_id IS NULL""").fetchone()["n"],
            },
            {
                "id": "academic_context_mismatches",
                "name": "تعارضات في العلاقات الأكاديمية",
                "severity": "error",
                "count": con.execute("""SELECT
                  (SELECT count(*) FROM questions q JOIN lessons l ON l.id=q.lesson_id WHERE
                    q.subject_id IS DISTINCT FROM l.subject_id OR q.grade_level_id IS DISTINCT FROM l.grade_level_id OR
                    q.curriculum_version_id IS DISTINCT FROM l.curriculum_version_id OR q.term_id IS DISTINCT FROM l.term_id OR
                    q.unit_id IS DISTINCT FROM l.unit_id)
                  + (SELECT count(*) FROM quizzes z JOIN quiz_questions qq ON qq.quiz_id=z.id JOIN questions q ON q.id=qq.question_id WHERE
                    z.subject_id IS DISTINCT FROM q.subject_id OR z.grade_level_id IS DISTINCT FROM q.grade_level_id OR
                    z.curriculum_version_id IS DISTINCT FROM q.curriculum_version_id OR z.term_id IS DISTINCT FROM q.term_id)
                  + (SELECT count(*) FROM questions q JOIN documents d ON d.id=q.document_id WHERE d.subject_id IS NOT NULL AND (
                    q.subject_id IS DISTINCT FROM d.subject_id OR q.grade_level_id IS DISTINCT FROM d.grade_level_id OR
                    q.curriculum_version_id IS DISTINCT FROM d.curriculum_version_id OR q.term_id IS DISTINCT FROM d.term_id))
                  n""").fetchone()["n"],
            },
            {
                "id": "students_without_code",
                "name": "طلاب بدون كود دخول",
                "severity": "error",
                "count": con.execute("""SELECT count(*) n FROM students
                    WHERE external_code IS NULL OR btrim(external_code)=''""").fetchone()["n"],
            },
            {
                "id": "guardians_without_optin",
                "name": "أولياء أمور بدون موافقة واتساب",
                "severity": "info",
                "count": con.execute("""SELECT count(*) n FROM guardians
                    WHERE active=TRUE AND whatsapp_opt_in=FALSE""").fetchone()["n"],
            },
        ]

    blocking = sum(int(x["count"]) for x in checks if x["severity"] == "error")
    warnings = sum(int(x["count"]) for x in checks if x["severity"] == "warning")
    return {
        "healthy": blocking == 0,
        "blocking_issue_count": blocking,
        "warning_issue_count": warnings,
        "checks": checks,
    }


PAGE = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>تشخيص سلامة النظام</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:980px;margin:auto;padding:18px}
.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}
.row{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:11px 0;border-bottom:1px solid #eee}
.bad{color:#b42318}.warn{color:#b54708}.ok{color:#067647}.muted{color:#667085}.n{font-size:22px;font-weight:800}
a{color:#175cd3;text-decoration:none}
</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/readiness">جاهزية النظام</a></div>
<div id=out class=box>جارٍ فحص سلامة البيانات...</div>
<script>
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){
 let r=await fetch('/api/admin/diagnostics'),x=await r.json();
 if(!r.ok){out.innerHTML='تعذر تشغيل التشخيص';return}
 let cls=x.healthy?'ok':'bad';
 out.innerHTML='<h1>تشخيص سلامة النظام</h1><p class="'+cls+'">'+
 (x.healthy?'✅ لا توجد مشكلات مانعة للتشغيل':'⚠️ توجد مشكلات مانعة: '+x.blocking_issue_count)+
 '</p>'+x.checks.map(c=>'<div class=row><div><b>'+e(c.name)+'</b><div class=muted>'+e(c.id)+'</div></div><div class="n '+(c.count?c.severity==='error'?'bad':c.severity==='warning'?'warn':'':'ok')+'">'+c.count+'</div></div>').join('')
}
load()
</script></main></html>'''


@app.get("/admin/diagnostics", response_class=HTMLResponse)
def diagnostics_page():
    return PAGE
