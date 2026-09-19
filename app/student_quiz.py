from __future__ import annotations

import re
from decimal import Decimal
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .main import app
from .db import connect
from .security import require_admin
from .parent_notifications import queue_attempt_notifications
from .services.grading import grade_answer
from .student_security import resolve_student_code
from .exam_engine import ensure_exam_open

def is_correct(answer: str, accepted: str | None) -> bool:
    """Backward-compatible wrapper used by lesson diagnostics and older modules."""
    return bool(grade_answer(answer, accepted))

class AnswerIn(BaseModel):
    question_id: int
    answer: str = Field(max_length=5000)

class SubmitAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[AnswerIn] = Field(max_length=200)
    attempt_id: int | None = None

class SaveAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: int
    answer: str = Field(max_length=5000)

@app.patch("/api/quizzes/{quiz_id}/publish", dependencies=[Depends(require_admin)])
def legacy_publish_quiz(quiz_id: int, published: bool = True):
    # Legacy endpoint must never bypass the centralized publication-quality gate.
    if published:
        raise HTTPException(410,{"message":"استخدم بوابة النشر الجديدة POST /api/quizzes/{quiz_id}/publish"})
    with connect() as con:
        q=con.execute("""UPDATE quizzes SET published=FALSE,
          lifecycle_status=CASE WHEN lifecycle_status='published' THEN 'ready' ELSE lifecycle_status END
          WHERE id=%s RETURNING id,title,published,lifecycle_status""",(quiz_id,)).fetchone()
        if not q: raise HTTPException(404,"Quiz not found")
        return q

@app.get("/api/student/quizzes/{quiz_id}")
def student_quiz(quiz_id: int, request: Request):
    # Published quiz metadata/questions still require a valid student session so
    # exam content cannot be enumerated before login.
    code=resolve_student_code(request)
    with connect() as con:
        st=con.execute("SELECT id FROM students WHERE external_code=%s",(code,)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        q=con.execute("""SELECT id,title,duration_minutes,max_attempts,retry_wait_minutes,score_policy,
          access_code,available_from,available_until,integrity_policy,now() db_now FROM quizzes
          WHERE id=%s AND published=TRUE AND lifecycle_status='published'
            AND (owner_student_id IS NULL OR owner_student_id=%s)""",(quiz_id,st["id"])).fetchone()
        if not q: raise HTTPException(404,"الاختبار غير متاح")
        ensure_exam_open(q)
        items=list(con.execute("""SELECT qq.position,qq.points,x.id,x.text_verbatim,x.question_type,
                    EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=x.id) has_asset
                    FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id
                    WHERE qq.quiz_id=%s AND x.approved=TRUE
                      AND x.subject_id=(SELECT subject_id FROM quizzes WHERE id=%s)
                      AND x.grade_level_id=(SELECT grade_level_id FROM quizzes WHERE id=%s)
                      AND x.curriculum_version_id=(SELECT curriculum_version_id FROM quizzes WHERE id=%s)
                      AND x.term_id=(SELECT term_id FROM quizzes WHERE id=%s)
                      AND x.accepted_answer IS NOT NULL AND btrim(x.accepted_answer)<>''
                      AND x.lesson_id IS NOT NULL AND x.subject_id IS NOT NULL AND x.grade_level_id IS NOT NULL
                      AND x.curriculum_version_id IS NOT NULL AND x.term_id IS NOT NULL
                      AND x.question_type<>'unknown' AND x.difficulty<>'unclassified'
                      AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=x.id AND qr.status='open')
                      AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=x.id)
                      AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=x.id)
                    ORDER BY qq.position""",(quiz_id,quiz_id,quiz_id,quiz_id,quiz_id)).fetchall())
        total=con.execute("SELECT count(*) n FROM quiz_questions WHERE quiz_id=%s",(quiz_id,)).fetchone()["n"]
        if not total or len(items)!=total:
            raise HTTPException(409,"تم إيقاف الاختبار مؤقتًا لأن أحد الأسئلة لم يعد مستوفيًا لشروط الاعتماد")
        return {**q,"questions":items,"delivery_state":"open"}

@app.post("/api/student/quizzes/{quiz_id}/start")
def start_quiz_attempt(quiz_id:int, request: Request):
    code=resolve_student_code(request)
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        quiz=con.execute("""SELECT id,title,duration_minutes,max_attempts,retry_wait_minutes,score_policy FROM quizzes
          WHERE id=%s AND published=TRUE AND lifecycle_status='published'
            AND (owner_student_id IS NULL OR owner_student_id=%s)""",(quiz_id,st["id"])).fetchone()
        if not quiz: raise HTTPException(404,"الاختبار غير متاح")
        ensure_exam_open(quiz)
        stats=con.execute("""SELECT count(*) FILTER(WHERE completed_at IS NOT NULL) completed,
          max(completed_at) FILTER(WHERE completed_at IS NOT NULL) last_completed FROM attempts
          WHERE student_id=%s AND quiz_id=%s""",(st["id"],quiz_id)).fetchone()
        completed=int(stats["completed"] or 0)
        if completed>=int(quiz["max_attempts"]): raise HTTPException(409,{"message":"استنفدت عدد المحاولات المسموح بها","max_attempts":quiz["max_attempts"]})
        if stats["last_completed"] is not None and int(quiz["retry_wait_minutes"] or 0)>0:
            allowed=con.execute("SELECT now() >= %s + (%s * interval '1 minute') v",(stats["last_completed"],quiz["retry_wait_minutes"])).fetchone()["v"]
            if not allowed:
                retry_at=con.execute("SELECT %s + (%s * interval '1 minute') v",(stats["last_completed"],quiz["retry_wait_minutes"])).fetchone()["v"]
                raise HTTPException(409,{"message":"يجب الانتظار قبل بدء محاولة جديدة","retry_at":retry_at})
        open_attempt=con.execute("""SELECT id,started_at FROM attempts
          WHERE student_id=%s AND quiz_id=%s AND completed_at IS NULL
          ORDER BY id DESC LIMIT 1""",(st["id"],quiz_id)).fetchone()
        if open_attempt:
            expires_at=con.execute("""SELECT CASE WHEN %s IS NULL THEN NULL
              ELSE %s + (%s * interval '1 minute') END v""",
              (quiz["duration_minutes"],open_attempt["started_at"],quiz["duration_minutes"])).fetchone()["v"]
            return {"attempt_id":open_attempt["id"],"started_at":open_attempt["started_at"],
                    "expires_at":expires_at,"resumed":True,"duration_minutes":quiz["duration_minutes"],"attempt_number":completed+1,"max_attempts":quiz["max_attempts"],"score_policy":quiz["score_policy"]}
        max_score=con.execute("SELECT coalesce(sum(points),0) v FROM quiz_questions WHERE quiz_id=%s",(quiz_id,)).fetchone()["v"]
        a=con.execute("""INSERT INTO attempts(student_id,quiz_id,score,max_score,started_at,submitted_at)
          VALUES(%s,%s,NULL,%s,now(),now()) RETURNING id,started_at""",(st["id"],quiz_id,max_score)).fetchone()
        expires_at=con.execute("""SELECT CASE WHEN %s IS NULL THEN NULL
          ELSE %s + (%s * interval '1 minute') END v""",
          (quiz["duration_minutes"],a["started_at"],quiz["duration_minutes"])).fetchone()["v"]
        return {"attempt_id":a["id"],"started_at":a["started_at"],"expires_at":expires_at,
                "resumed":False,"duration_minutes":quiz["duration_minutes"],"attempt_number":completed+1,"max_attempts":quiz["max_attempts"],"score_policy":quiz["score_policy"]}

@app.put("/api/student/attempts/{attempt_id}/answer")
def save_quiz_answer(attempt_id:int,p:SaveAnswer, request: Request):
    code=resolve_student_code(request)
    with connect() as con:
        a=con.execute("""SELECT a.id,a.quiz_id,a.started_at,a.completed_at,s.external_code,q.duration_minutes
          FROM attempts a JOIN students s ON s.id=a.student_id JOIN quizzes q ON q.id=a.quiz_id WHERE a.id=%s""",(attempt_id,)).fetchone()
        if not a or a["external_code"]!=code: raise HTTPException(404,"المحاولة غير موجودة")
        if a["completed_at"] is not None: raise HTTPException(409,"تم تسليم هذه المحاولة بالفعل")
        if a["duration_minutes"] is not None:
            expired=con.execute("SELECT now() >= %s + (%s * interval '1 minute') v",
              (a["started_at"],a["duration_minutes"])).fetchone()["v"]
            if expired: raise HTTPException(409,"انتهى وقت الاختبار ولا يمكن تعديل الإجابات")
        if not con.execute("""SELECT 1 FROM quiz_questions qq JOIN quizzes q ON q.id=qq.quiz_id
          WHERE qq.quiz_id=%s AND qq.question_id=%s AND q.published=TRUE AND q.lifecycle_status='published'""",
          (a["quiz_id"],p.question_id)).fetchone():
            raise HTTPException(400,"السؤال غير موجود في الاختبار المنشور")
        con.execute("""INSERT INTO attempt_answers(attempt_id,question_id,answer_text,is_correct,awarded_score,points_awarded)
          VALUES(%s,%s,%s,NULL,NULL,0)
          ON CONFLICT (attempt_id,question_id) WHERE attempt_id IS NOT NULL AND question_id IS NOT NULL
          DO UPDATE SET answer_text=EXCLUDED.answer_text,is_correct=NULL,awarded_score=NULL,points_awarded=0""",
          (attempt_id,p.question_id,p.answer))
        return {"ok":True,"attempt_id":attempt_id,"question_id":p.question_id}

@app.get("/api/student/attempts/{attempt_id}/saved")
def saved_quiz_answers(attempt_id:int, request: Request):
    code=resolve_student_code(request)
    with connect() as con:
        a=con.execute("""SELECT a.id,a.completed_at,s.external_code FROM attempts a JOIN students s ON s.id=a.student_id
          WHERE a.id=%s""",(attempt_id,)).fetchone()
        if not a or a["external_code"]!=code: raise HTTPException(404,"المحاولة غير موجودة")
        rows=list(con.execute("""SELECT question_id,answer_text FROM attempt_answers
          WHERE attempt_id=%s ORDER BY id""",(attempt_id,)).fetchall())
        return {"attempt_id":attempt_id,"completed":a["completed_at"] is not None,"answers":rows}

@app.post("/api/student/quizzes/{quiz_id}/submit")
def submit_quiz(quiz_id:int,p:SubmitAttempt, request: Request):
    code=resolve_student_code(request)
    with connect() as con:
        student=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
        if not student: raise HTTPException(404,"كود الطالب غير صحيح")
        quiz=con.execute("""SELECT id,title,duration_minutes,max_attempts,retry_wait_minutes,score_policy FROM quizzes
          WHERE id=%s AND published=TRUE AND lifecycle_status='published'
            AND (owner_student_id IS NULL OR owner_student_id=%s)""",(quiz_id,student["id"])).fetchone()
        if not quiz: raise HTTPException(404,"الاختبار غير متاح")
        rows=list(con.execute("""SELECT qq.question_id,qq.points,x.accepted_answer
              FROM quiz_questions qq JOIN questions x ON x.id=qq.question_id
              WHERE qq.quiz_id=%s AND x.approved=TRUE
                AND x.subject_id=(SELECT subject_id FROM quizzes WHERE id=%s)
                AND x.grade_level_id=(SELECT grade_level_id FROM quizzes WHERE id=%s)
                AND x.curriculum_version_id=(SELECT curriculum_version_id FROM quizzes WHERE id=%s)
                AND x.term_id=(SELECT term_id FROM quizzes WHERE id=%s)
                AND x.accepted_answer IS NOT NULL AND btrim(x.accepted_answer)<>''
                AND x.lesson_id IS NOT NULL AND x.subject_id IS NOT NULL AND x.grade_level_id IS NOT NULL
                AND x.curriculum_version_id IS NOT NULL AND x.term_id IS NOT NULL
                AND x.question_type<>'unknown' AND x.difficulty<>'unclassified'
                AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=x.id AND qr.status='open')
                AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=x.id)
                AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=x.id)
              ORDER BY qq.position""",(quiz_id,quiz_id,quiz_id,quiz_id,quiz_id)).fetchall())
        total_questions=con.execute("SELECT count(*) n FROM quiz_questions WHERE quiz_id=%s",(quiz_id,)).fetchone()["n"]
        if not rows: raise HTTPException(409,"الاختبار لا يحتوي على أسئلة جاهزة")
        if len(rows)!=total_questions: raise HTTPException(409,"تم إيقاف الاختبار لأن أحد الأسئلة لم يعد مستوفيًا لشروط الاعتماد")
        allowed={r["question_id"]:r for r in rows}
        submitted_ids=[a.question_id for a in p.answers]
        if len(submitted_ids)!=len(set(submitted_ids)):
            raise HTTPException(400,"لا يمكن إرسال إجابتين لنفس السؤال")
        extra=[qid for qid in submitted_ids if qid not in allowed]
        if extra:
            raise HTTPException(400,"تم إرسال إجابة لسؤال غير موجود في الاختبار")
        submitted={a.question_id:a.answer for a in p.answers}
        max_score=sum((Decimal(str(r["points"])) for r in rows),Decimal("0"))
        attempt=None
        if p.attempt_id is not None:
            attempt=con.execute("""SELECT a.id,a.completed_at FROM attempts a
              WHERE a.id=%s AND a.student_id=%s AND a.quiz_id=%s""",(p.attempt_id,student["id"],quiz_id)).fetchone()
            if not attempt: raise HTTPException(404,"المحاولة غير موجودة")
            if attempt["completed_at"] is not None: raise HTTPException(409,"تم تسليم هذه المحاولة بالفعل")
        else:
            recent=con.execute("""SELECT id FROM attempts WHERE student_id=%s AND quiz_id=%s
              AND completed_at IS NOT NULL AND submitted_at>=now()-interval '10 seconds'
              ORDER BY id DESC LIMIT 1""",(student["id"],quiz_id)).fetchone()
            if recent: raise HTTPException(409,"تم استلام محاولة لهذا الاختبار منذ لحظات. انتظر قليلًا قبل إعادة الإرسال.")
            attempt=con.execute("""INSERT INTO attempts(student_id,quiz_id,score,max_score,started_at,completed_at,submitted_at)
              VALUES (%s,%s,NULL,%s,now(),NULL,now()) RETURNING id,completed_at""",(student["id"],quiz_id,max_score)).fetchone()
        saved={r["question_id"]:r["answer_text"] for r in con.execute(
            "SELECT question_id,answer_text FROM attempt_answers WHERE attempt_id=%s",(attempt["id"],)).fetchall()}
        expired=False
        if quiz["duration_minutes"] is not None:
            started=con.execute("SELECT started_at FROM attempts WHERE id=%s",(attempt["id"],)).fetchone()["started_at"]
            expired=bool(con.execute("SELECT now() >= %s + (%s * interval '1 minute') v",
                (started,quiz["duration_minutes"])).fetchone()["v"])
        if not expired:
            saved.update(submitted)
        score=Decimal("0"); correct=0
        for qid,r in allowed.items():
            ans=saved.get(qid,"") or ""
            ok=bool(grade_answer(ans,r["accepted_answer"]))
            pts=Decimal(str(r["points"])) if ok else Decimal("0")
            score+=pts; correct+=1 if ok else 0
            con.execute("""INSERT INTO attempt_answers(attempt_id,question_id,answer_text,is_correct,awarded_score,points_awarded)
              VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT (attempt_id,question_id) WHERE attempt_id IS NOT NULL AND question_id IS NOT NULL
              DO UPDATE SET answer_text=EXCLUDED.answer_text,is_correct=EXCLUDED.is_correct,
                awarded_score=EXCLUDED.awarded_score,points_awarded=EXCLUDED.points_awarded""",
              (attempt["id"],qid,ans,ok,pts,pts))
        con.execute("""UPDATE attempts SET score=%s,max_score=%s,completed_at=now(),submitted_at=now()
          WHERE id=%s""",(score,max_score,attempt["id"]))
        attempt_id=attempt["id"]
    notify={"queued":[],"guardian_count":0}
    try:
        notify=queue_attempt_notifications(attempt_id)
    except Exception as exc:
        # The student's result is already safely committed. Do not fail the submission
        # because a downstream parent-notification queue has a temporary problem.
        notify={"queued":[],"guardian_count":0,"queue_error":str(exc)[:500]}
    pct=round(float(score/max_score*100),1) if max_score else 0.0
    with connect() as con:
        policy=con.execute("SELECT score_policy FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()["score_policy"]
        history=list(con.execute("""SELECT score,max_score FROM attempts
          WHERE student_id=%s AND quiz_id=%s AND completed_at IS NOT NULL ORDER BY completed_at,id""",(student["id"],quiz_id)).fetchall())
    percentages=[float(r["score"]/r["max_score"]*100) if r["max_score"] else 0.0 for r in history]
    recorded=max(percentages) if policy=="highest" and percentages else (percentages[-1] if percentages else pct)
    return {"attempt_id":attempt_id,"student_name":student["name"],"quiz_title":quiz["title"],
            "score":float(score),"max_score":float(max_score),"percentage":pct,
            "correct":correct,"incorrect":len(rows)-correct,
            "adaptive_recommended": pct < 85,
            "parent_notifications":notify,"time_expired":expired,"score_policy":policy,"recorded_percentage":round(recorded,2),"attempts_used":len(history)}

STUDENT = r'''<!doctype html>
<html lang="ar" dir="rtl">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>اختبار الفيزياء</title>
<style>
:root{--bg:#f5f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e4e7ec;--brand:#2447a8;--soft:#eef3ff;--ok:#067647;--bad:#b42318}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);margin:0;color:var(--text)}
main{max-width:920px;margin:auto;padding:18px 18px 90px}.box,.q{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #1018280a}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
a{color:var(--brand);text-decoration:none}.muted{color:var(--muted)}.status{font-size:13px}.result{font-size:22px;font-weight:800}
input,button{padding:11px;border:1px solid #cbd2df;border-radius:10px;font:inherit}button{cursor:pointer;background:#fff}button.primary{background:var(--brand);border-color:var(--brand);color:#fff}button:disabled{opacity:.5;cursor:not-allowed}
input:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid #84adff;outline-offset:2px}.answer{width:100%;margin-top:10px}.asset{max-width:100%;max-height:520px;display:block;margin:10px auto;border-radius:12px}
.q-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.pill{display:inline-block;background:var(--soft);color:var(--brand);border-radius:999px;padding:5px 9px;font-size:12px;font-weight:700}
.progress{height:9px;background:#eaecf0;border-radius:999px;overflow:hidden;margin:9px 0}.progress>span{display:block;height:100%;background:var(--brand);width:0;transition:width .2s ease}
.save-ok{color:var(--ok)}.save-bad{color:var(--bad)}.sticky-actions{position:sticky;bottom:8px;z-index:10;background:#ffffffed;backdrop-filter:blur(8px)}
@media(max-width:650px){main{padding:10px 10px 92px}.box,.q{padding:13px;border-radius:14px}.row>*{flex:1 1 100%}.result{font-size:18px}.sticky-actions{bottom:4px}.q{scroll-margin-top:10px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
<main>
<div class="box">
  <div class="top"><a href="/student">← بوابة الطالب</a><span id="sessionBadge" class="pill">فحص الجلسة...</span></div>
  <h1 id="title">اختبار الفيزياء</h1>
  <div class="row" id="loginRow">
    <label for="code" class="muted">كود الطالب</label>
    <input id="code" autocomplete="one-time-code" placeholder="أدخل كود الطالب">
    <button class="primary" onclick="startAttempt()">بدء / استكمال الاختبار</button>
  </div>
  <div id="timer" class="result"></div>
  <div class="progress" aria-label="نسبة الإجابات"><span id="progressBar"></span></div>
  <div id="progressText" class="muted"></div>
  <div id="msg" class="status muted" aria-live="polite"></div>
</div>
<div id="items"></div>
<div class="box sticky-actions">
  <div class="row">
    <button class="primary" id="submitBtn" onclick="submitQuiz()" disabled>إنهاء الاختبار وإظهار النتيجة</button>
    <button onclick="location.href='/student'">العودة للبوابة</button>
  </div>
</div>
<div id="result" class="box" style="display:none" aria-live="polite"></div>

<script>
const quizId=Number(location.pathname.split('/').pop());
let data=null,attemptId=null,expiresAt=null,timerHandle=null,autoSubmitting=false,integrityPolicy={mode:'off'};
const saveTimers=new Map();

function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function apiError(x,fallback){return typeof x?.detail==='string'?x.detail:(x?.detail?.message||fallback)}
function updateProgress(){
  if(!data){progressText.textContent='';return}
  const answers=data.questions.filter(q=>(document.getElementById('a_'+q.id)?.value||'').trim()).length;
  const total=data.questions.length||0,pct=total?Math.round(answers*100/total):0;
  progressText.textContent='تمت الإجابة عن '+answers+' من '+total+' أسئلة';
  progressBar.style.width=pct+'%';
}
async function sessionInfo(){
  return fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));
}
async function ensureSession(){
  let s=await sessionInfo();
  if(s.authenticated){sessionBadge.textContent='جلسة آمنة · '+(s.student?.name||'الطالب');loginRow.querySelector('label').style.display='none';code.style.display='none';return true}
  let v=code.value.trim();
  if(!v)throw new Error('أدخل كود الطالب');
  let r=await fetch('/api/student/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({student_code:v})});
  let x=await r.json().catch(()=>null);
  if(!r.ok)throw new Error(apiError(x,'تعذر تسجيل الدخول'));
  code.value='';code.style.display='none';loginRow.querySelector('label').style.display='none';
  sessionBadge.textContent='جلسة آمنة · '+(x.student?.name||'الطالب');
  return true;
}
async function loadQuiz(){
  let r=await fetch('/api/student/quizzes/'+quizId,{cache:'no-store'}),x=await r.json().catch(()=>null);
  if(!r.ok){msg.textContent=apiError(x,'تعذر تحميل الاختبار');return false}
  data=x;integrityPolicy=x.integrity_policy||{mode:'off'};title.textContent=x.title;
  items.innerHTML=x.questions.map(q=>`<section class="q" id="q_${q.id}">
    <div class="q-head"><b>سؤال ${q.position}</b><span id="save_${q.id}" class="muted"></span></div>
    ${q.has_asset?`<img class="asset" src="/api/practice/questions/${q.id}/asset" alt="صورة السؤال ${q.position}" loading="lazy">`:''}
    <div>${esc(q.text_verbatim)}</div>
    <input class="answer" id="a_${q.id}" aria-label="إجابة السؤال ${q.position}" placeholder="اكتب الإجابة" disabled oninput="queueSave(${q.id})">
  </section>`).join('');
  updateProgress();
  return true
}
async function load(){
  let s=await sessionInfo();
  if(s.authenticated){
    sessionBadge.textContent='جلسة آمنة · '+(s.student?.name||'الطالب');
    code.style.display='none';loginRow.querySelector('label').style.display='none';
    if(await loadQuiz())msg.textContent='يمكنك بدء أو استكمال المحاولة.'
  }else{
    sessionBadge.textContent='تسجيل الدخول مطلوب';
    items.innerHTML='';
    msg.textContent='أدخل كود الطالب لبدء أو استكمال المحاولة.'
  }
}
async function startAttempt(){try{await ensureAttempt()}catch(e){msg.textContent=e.message}}
async function ensureAttempt(){
  if(attemptId)return attemptId;
  await ensureSession();
  if(!data && !await loadQuiz())throw new Error('تعذر تحميل الاختبار');
  let r=await fetch('/api/student/quizzes/'+quizId+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  let x=await r.json().catch(()=>null);
  if(!r.ok)throw new Error(apiError(x,'تعذر بدء الاختبار'));
  attemptId=x.attempt_id;expiresAt=x.expires_at?new Date(x.expires_at):null;submitBtn.disabled=false;
  document.querySelectorAll('.answer').forEach(el=>el.disabled=false);
  startTimer();
  let sr=await fetch('/api/student/attempts/'+attemptId+'/saved',{cache:'no-store'}),sx=await sr.json().catch(()=>null);
  if(sr.ok){for(let a of sx.answers||[]){let el=document.getElementById('a_'+a.question_id);if(el)el.value=a.answer_text||''}}
  updateProgress();
  msg.textContent=x.resumed?'تم استكمال محاولتك السابقة.':'بدأت محاولة جديدة ويتم حفظ كل إجابة تلقائيًا.';
  return attemptId;
}
function queueSave(qid){
  if(expiresAt&&Date.now()>=expiresAt.getTime())return;
  updateProgress();
  clearTimeout(saveTimers.get(qid));
  let badge=document.getElementById('save_'+qid);if(badge){badge.textContent='بانتظار الحفظ';badge.className='muted'}
  saveTimers.set(qid,setTimeout(()=>saveAnswer(qid),500));
}
function integrityEnabled(key){
  return integrityPolicy&&integrityPolicy.mode!=='off'&&integrityPolicy[key]!==false
}
async function reportIntegrity(eventType,detail=''){
  if(!attemptId||!integrityPolicy||integrityPolicy.mode==='off')return;
  try{
    let r=await fetch('/api/student/attempts/'+attemptId+'/integrity-event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_type:eventType,detail})});
    let x=await r.json().catch(()=>null);
    if(!r.ok)return;
    if(x.action==='warn')msg.textContent='تنبيه: تم تسجيل خروجك من سياق الامتحان ('+x.violations+' مخالفة).';
    if(x.action==='auto_submit'&&!autoSubmitting){autoSubmitting=true;msg.textContent='تم بلوغ حد المخالفات وسيتم تسليم آخر إجابات محفوظة.';submitQuiz(true)}
  }catch(_e){}
}
document.addEventListener('visibilitychange',()=>{if(document.hidden&&integrityEnabled('track_tab_switch'))reportIntegrity('tab_hidden')});
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&attemptId&&integrityEnabled('track_fullscreen_exit'))reportIntegrity('fullscreen_exit')});
document.addEventListener('copy',()=>{if(integrityEnabled('track_copy_paste'))reportIntegrity('copy')});
document.addEventListener('paste',()=>{if(integrityEnabled('track_copy_paste'))reportIntegrity('paste')});
document.addEventListener('contextmenu',()=>{if(integrityEnabled('track_context_menu'))reportIntegrity('context_menu')});
window.addEventListener('blur',()=>{if(integrityEnabled('track_window_blur'))reportIntegrity('window_blur')});

function startTimer(){
  clearInterval(timerHandle);
  if(!expiresAt){timer.textContent='بدون وقت محدد';return}
  function tick(){
    let ms=expiresAt.getTime()-Date.now();
    if(ms<=0){
      timer.textContent='انتهى الوقت';document.querySelectorAll('.answer').forEach(el=>el.disabled=true);submitBtn.disabled=true;clearInterval(timerHandle);
      if(!autoSubmitting){autoSubmitting=true;submitQuiz(true)}
      return
    }
    let s=Math.floor(ms/1000),m=Math.floor(s/60),sec=s%60;
    timer.textContent='الوقت المتبقي: '+m+':'+String(sec).padStart(2,'0')
  }
  tick();timerHandle=setInterval(tick,1000)
}
async function saveAnswer(qid){
  try{
    let id=await ensureAttempt(),el=document.getElementById('a_'+qid),badge=document.getElementById('save_'+qid);
    let r=await fetch('/api/student/attempts/'+id+'/answer',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({question_id:qid,answer:el.value})});
    let x=await r.json().catch(()=>null);
    if(!r.ok)throw new Error(apiError(x,'تعذر حفظ الإجابة'));
    if(badge){badge.textContent='تم الحفظ';badge.className='save-ok'}
  }catch(e){
    let badge=document.getElementById('save_'+qid);if(badge){badge.textContent='لم تُحفظ';badge.className='save-bad'}
    msg.textContent=e.message
  }finally{saveTimers.delete(qid)}
}
async function submitQuiz(fromTimer=false){
  if(!data)return;
  try{await ensureAttempt()}catch(e){msg.textContent=e.message;return}
  for(const timer of saveTimers.values())clearTimeout(timer);saveTimers.clear();
  let answers=data.questions.map(q=>({question_id:q.id,answer:document.getElementById('a_'+q.id).value}));
  let r=await fetch('/api/student/quizzes/'+quizId+'/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers,attempt_id:attemptId})});
  let x=await r.json().catch(()=>null);
  if(!r.ok){msg.textContent=apiError(x,'تعذر تسليم الاختبار');return}
  clearInterval(timerHandle);document.querySelectorAll('.answer').forEach(el=>el.disabled=true);submitBtn.disabled=true;
  result.style.display='block';
  result.innerHTML=`<div class=result>${esc(x.student_name)} — ${x.percentage}%</div>
    ${x.time_expired?'<p class="muted">تم التسليم بعد انتهاء الوقت باستخدام آخر إجابات محفوظة قبل انتهاء المدة.</p>':''}
    <p>الدرجة: ${x.score} / ${x.max_score}</p><p>صحيح: ${x.correct} · خطأ: ${x.incorrect}</p>
    <p class=muted>تم حفظ النتيجة. التصحيح النهائي حتمي من الإجابات المعتمدة في بنك الأسئلة.</p>
    <div class=row><button onclick="downloadAttemptReview()">تنزيل الاختبار بإجاباتي PDF</button><button onclick="downloadMistakesReview()">تنزيل مذكرة أخطائي PDF</button></div>
    ${x.adaptive_recommended?'<button class="primary" onclick="startAdaptive()">ابدأ تدريبًا علاجيًا مناسبًا لمستواك</button>':'<p class="muted">مستواك الحالي جيد؛ سيستمر النظام في متابعة نقاط القوة والضعف.</p>'}`;
  result.scrollIntoView({behavior:'smooth',block:'start'})
}
async function downloadReview(url,filename,payload){
  msg.textContent='جارٍ تجهيز ملف المراجعة...';
  try{
    let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!r.ok){let x=await r.json().catch(()=>null);msg.textContent=apiError(x,'تعذر إنشاء ملف المراجعة');return}
    let blob=await r.blob(),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);msg.textContent='تم تجهيز ملف المراجعة.'
  }catch(e){msg.textContent='تعذر الاتصال أثناء تجهيز ملف المراجعة.'}
}
function downloadAttemptReview(){if(!attemptId)return;return downloadReview('/api/student/attempts/'+attemptId+'/review-pdf','attempt-'+attemptId+'-review.pdf',{max_questions:100})}
function downloadMistakesReview(){return downloadReview('/api/student/review/mistakes-pdf','my-mistakes-review.pdf',{max_questions:100})}
async function startAdaptive(){
  msg.textContent='جارٍ تجهيز التدريب العلاجي...';
  let r=await fetch('/api/student/adaptive-practice/create?count=10',{method:'POST'}),x=await r.json().catch(()=>null);
  if(!r.ok){msg.textContent=apiError(x,'تعذر إنشاء التدريب');return}
  location.href=x.student_path
}
load();
</script>
</main></html>'''

@app.get("/student/quiz/{quiz_id}",response_class=HTMLResponse)
def student_quiz_page(quiz_id:int):
    return STUDENT
