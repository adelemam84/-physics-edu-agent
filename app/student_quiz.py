from __future__ import annotations

import re
from decimal import Decimal
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .main import app
from .db import connect
from .security import require_admin
from .parent_notifications import queue_attempt_notifications

class AnswerIn(BaseModel):
    question_id: int
    answer: str

class SubmitAttempt(BaseModel):
    student_code: str
    answers: list[AnswerIn]

def norm(v: str | None) -> str:
    if v is None:
        return ""
    v = re.sub(r"\s+", " ", str(v)).strip().casefold()
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return v.translate(trans)

def is_correct(answer: str, accepted: str | None) -> bool:
    if not accepted:
        return False
    choices = [norm(x) for x in re.split(r"\s*\|\s*", accepted) if norm(x)]
    return norm(answer) in choices

@app.patch("/api/quizzes/{quiz_id}/publish", dependencies=[Depends(require_admin)])
def publish_quiz(quiz_id: int, published: bool = True):
    with connect() as con:
        q = con.execute("SELECT id,title FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not q: raise HTTPException(404,"Quiz not found")
        if published:
            bad = con.execute("""SELECT count(*) n FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id
                                 WHERE qq.quiz_id=%s AND (x.approved=FALSE OR x.accepted_answer IS NULL OR btrim(x.accepted_answer)='')""",(quiz_id,)).fetchone()["n"]
            total = con.execute("SELECT count(*) n FROM quiz_questions WHERE quiz_id=%s",(quiz_id,)).fetchone()["n"]
            if not total: raise HTTPException(409,"الاختبار لا يحتوي على أسئلة")
            if bad: raise HTTPException(409,{"message":"لا يمكن نشر الاختبار قبل اعتماد كل الأسئلة وتسجيل الإجابة المعتمدة","invalid_questions":bad})
        return con.execute("UPDATE quizzes SET published=%s WHERE id=%s RETURNING id,title,published",(published,quiz_id)).fetchone()

@app.get("/api/student/quizzes/{quiz_id}")
def student_quiz(quiz_id: int):
    with connect() as con:
        q=con.execute("SELECT id,title,duration_minutes FROM quizzes WHERE id=%s AND published=TRUE",(quiz_id,)).fetchone()
        if not q: raise HTTPException(404,"الاختبار غير متاح")
        items=list(con.execute("""SELECT qq.position,qq.points,x.id,x.text_verbatim,x.question_type,
                    (a.question_id IS NOT NULL) has_asset
                    FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id
                    LEFT JOIN question_assets a ON a.question_id=x.id
                    WHERE qq.quiz_id=%s AND x.approved=TRUE ORDER BY qq.position""",(quiz_id,)).fetchall())
        return {**q,"questions":items}

@app.post("/api/student/quizzes/{quiz_id}/submit")
def submit_quiz(quiz_id:int,p:SubmitAttempt):
    code=p.student_code.strip()
    if not code: raise HTTPException(400,"أدخل كود الطالب")
    with connect() as con:
        student=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
        if not student: raise HTTPException(404,"كود الطالب غير صحيح")
        quiz=con.execute("SELECT id,title FROM quizzes WHERE id=%s AND published=TRUE",(quiz_id,)).fetchone()
        if not quiz: raise HTTPException(404,"الاختبار غير متاح")
        rows=list(con.execute("""SELECT qq.question_id,qq.points,x.accepted_answer
              FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id
              WHERE qq.quiz_id=%s AND x.approved=TRUE ORDER BY qq.position""",(quiz_id,)).fetchall())
        if not rows: raise HTTPException(409,"الاختبار لا يحتوي على أسئلة جاهزة")
        allowed={r["question_id"]:r for r in rows}
        submitted={a.question_id:a.answer for a in p.answers}
        max_score=sum((Decimal(str(r["points"])) for r in rows),Decimal("0"))
        attempt=con.execute("""INSERT INTO attempts(student_id,quiz_id,score,max_score,completed_at,submitted_at)
                               VALUES (%s,%s,0,%s,now(),now()) RETURNING id""",(student["id"],quiz_id,max_score)).fetchone()
        score=Decimal("0"); correct=0
        for qid,r in allowed.items():
            ans=submitted.get(qid,"")
            ok=is_correct(ans,r["accepted_answer"])
            pts=Decimal(str(r["points"])) if ok else Decimal("0")
            score+=pts; correct+=1 if ok else 0
            con.execute("""INSERT INTO attempt_answers(attempt_id,question_id,answer_text,is_correct,awarded_score,points_awarded)
                           VALUES (%s,%s,%s,%s,%s,%s)""",(attempt["id"],qid,ans,ok,pts,pts))
        con.execute("UPDATE attempts SET score=%s WHERE id=%s",(score,attempt["id"]))
        attempt_id=attempt["id"]
    notify={"queued":[],"guardian_count":0}
    try:
        notify=queue_attempt_notifications(attempt_id)
    except Exception:
        pass
    pct=round(float(score/max_score*100),1) if max_score else 0.0
    return {"attempt_id":attempt_id,"student_name":student["name"],"quiz_title":quiz["title"],
            "score":float(score),"max_score":float(max_score),"percentage":pct,
            "correct":correct,"incorrect":len(rows)-correct,
            "adaptive_recommended": pct < 85,
            "parent_notifications":notify}

STUDENT = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>اختبار الفيزياء</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033}main{max-width:900px;margin:auto;padding:18px}.box,.q{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.asset{max-width:100%;border-radius:10px}.row{display:flex;gap:8px;flex-wrap:wrap}input,button{padding:11px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}input.answer{width:100%;box-sizing:border-box}.muted{color:#667085}.result{font-size:22px;font-weight:700}</style><main>
<div class=box><h1 id=title>اختبار الفيزياء</h1><div class=row><input id=code placeholder="كود الطالب"><button onclick=submitQuiz()>إنهاء الاختبار وإظهار النتيجة</button></div><div id=msg class=muted></div></div><div id=items></div><div id=result class=box style="display:none"></div>
<script>
const quizId=Number(location.pathname.split('/').pop());let data=null;
function esc(s){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let r=await fetch('/api/student/quizzes/'+quizId),x=await r.json();if(!r.ok){msg.textContent=x.detail||'تعذر تحميل الاختبار';return}data=x;title.textContent=x.title;items.innerHTML=x.questions.map(q=>`<div class=q><b>سؤال ${q.position}</b>${q.has_asset?`<div><img class=asset src="/api/practice/questions/${q.id}/asset"></div>`:''}<div>${esc(q.text_verbatim)}</div><input class=answer id="a_${q.id}" placeholder="اكتب الإجابة"></div>`).join('')}
async function submitQuiz(){if(!data)return;let answers=data.questions.map(q=>({question_id:q.id,answer:document.getElementById('a_'+q.id).value}));let r=await fetch('/api/student/quizzes/'+quizId+'/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_code:code.value,answers})}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='string'?x.detail:JSON.stringify(x.detail);return}result.style.display='block';result.innerHTML=`<div class=result>${esc(x.student_name)} — ${x.percentage}%</div><p>الدرجة: ${x.score} / ${x.max_score}</p><p>صحيح: ${x.correct} · خطأ: ${x.incorrect}</p><p class=muted>تم حفظ النتيجة وتجهيز إشعار ولي الأمر المسجل والموافق على رسائل واتساب.</p>${x.adaptive_recommended?'<button onclick="startAdaptive()">ابدأ تدريبًا علاجيًا مناسبًا لمستواك</button>':'<p class="muted">مستواك الحالي جيد؛ سيظل النظام يتابع نقاط القوة والضعف من المحاولات التالية.</p>'}`;scrollTo({top:document.body.scrollHeight,behavior:'smooth'})}
async function startAdaptive(){msg.textContent='جارٍ تجهيز التدريب العلاجي...';let r=await fetch('/api/student/adaptive-practice/create?student_code='+encodeURIComponent(code.value)+'&count=10',{method:'POST'}),x=await r.json();if(!r.ok){msg.textContent=typeof x.detail==='string'?x.detail:JSON.stringify(x.detail);return}location.href=x.student_path}load();
</script></main></html>'''

@app.get("/student/quiz/{quiz_id}",response_class=HTMLResponse)
def student_quiz_page(quiz_id:int):
    return STUDENT
