from __future__ import annotations
from decimal import Decimal
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .main import app
from .db import connect
from .student_quiz import is_correct
from .student_security import resolve_student_code

class DiagnosticAnswer(BaseModel):
    question_id:int
    answer:str

class DiagnosticSubmit(BaseModel):
    student_code: str | None = None
    answers:list[DiagnosticAnswer]

@app.get("/api/student/lessons/{lesson_id}")
def student_lesson(lesson_id:int, request: Request, student_code: str | None = None):
    code=resolve_student_code(request, student_code)
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        lesson=con.execute("""SELECT l.id,l.title,l.chapter,l.subject_id,l.grade_level_id,l.curriculum_version_id,l.term_id,l.unit_id,
          u.title unit_title,s.name_ar subject_name,g.name_ar grade_name
          FROM lessons l LEFT JOIN units u ON u.id=l.unit_id LEFT JOIN subjects s ON s.id=l.subject_id LEFT JOIN grade_levels g ON g.id=l.grade_level_id
          WHERE l.id=%s""",(lesson_id,)).fetchone()
        if not lesson: raise HTTPException(404,"الدرس غير موجود")
        concepts=list(con.execute("""SELECT id,title FROM concepts WHERE lesson_id=%s ORDER BY sort_order,id""",(lesson_id,)).fetchall())
        source_pages=list(con.execute("""SELECT DISTINCT d.id document_id,d.filename,dp.page_number,dp.extracted_text
          FROM lesson_source_mappings m JOIN documents d ON d.id=m.document_id
          JOIN document_pages dp ON dp.document_id=m.document_id AND dp.page_number BETWEEN m.start_page AND m.end_page
          WHERE m.lesson_id=%s AND m.mapping_status='approved' AND d.kind IN ('lesson','explanation','textbook','notes') AND d.status='approved'
            AND dp.extracted_text IS NOT NULL AND btrim(dp.extracted_text)<>''
          ORDER BY d.filename,dp.page_number LIMIT 30""",(lesson_id,)).fetchall())
        questions=list(con.execute("""SELECT q.id,q.text_verbatim,q.question_type,q.difficulty,
          EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id) has_asset
          FROM questions q WHERE q.lesson_id=%s AND q.approved=TRUE
            AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
            AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
            AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')
            AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
            AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
          ORDER BY random() LIMIT 5""",(lesson_id,)).fetchall())
        prior=con.execute("""SELECT count(*) responses,count(*) FILTER(WHERE aa.is_correct=TRUE) correct
          FROM attempt_answers aa JOIN attempts a ON a.id=aa.attempt_id JOIN questions q ON q.id=aa.question_id
          WHERE a.student_id=%s AND a.completed_at IS NOT NULL AND q.lesson_id=%s""",(st["id"],lesson_id)).fetchone()
    mastery=round(100*int(prior["correct"] or 0)/int(prior["responses"]),1) if int(prior["responses"] or 0) else None
    return {"student":st,"lesson":lesson,"concepts":concepts,"source_pages":source_pages,"diagnostic_questions":questions,
      "prior_mastery":mastery,"source_policy":"approved_lesson_sources_and_approved_source_questions_only",
      "content_note":"محتوى القراءة أدناه من نص صفحات PDF المصدرية المرتبطة بأسئلة هذا الدرس والمعتمدة في النظام؛ لا تتم إضافة معلومات علمية من خارج المصدر."}

@app.post("/api/student/lessons/{lesson_id}/diagnostic")
def lesson_diagnostic(lesson_id:int,p:DiagnosticSubmit, request: Request):
    code=resolve_student_code(request, p.student_code)
    with connect() as con:
        st=con.execute("SELECT id,name FROM students WHERE external_code=%s",(code,)).fetchone()
        if not st: raise HTTPException(404,"كود الطالب غير صحيح")
        rows=list(con.execute("""SELECT q.id,q.accepted_answer FROM questions q WHERE q.lesson_id=%s AND q.approved=TRUE
          AND q.id=ANY(%s) AND q.accepted_answer IS NOT NULL""",(lesson_id,[a.question_id for a in p.answers] or [-1])).fetchall())
        allowed={r["id"]:r for r in rows}
        if not allowed: raise HTTPException(400,"لا توجد أسئلة تمهيدية صالحة للتصحيح")
        submitted={a.question_id:a.answer for a in p.answers if a.question_id in allowed}
        attempt=con.execute("""INSERT INTO attempts(student_id,quiz_id,score,max_score,started_at,completed_at,submitted_at)
          VALUES(%s,NULL,0,%s,now(),now(),now()) RETURNING id""",(st["id"],len(allowed))).fetchone()
        score=Decimal("0");correct=0
        for qid,r in allowed.items():
            ans=submitted.get(qid,"")
            ok=is_correct(ans,r["accepted_answer"])
            pts=Decimal("1") if ok else Decimal("0")
            score+=pts;correct+=1 if ok else 0
            con.execute("""INSERT INTO attempt_answers(attempt_id,question_id,answer_text,is_correct,awarded_score,points_awarded)
              VALUES(%s,%s,%s,%s,%s,%s)""",(attempt["id"],qid,ans,ok,pts,pts))
        con.execute("UPDATE attempts SET score=%s WHERE id=%s",(score,attempt["id"]))
    pct=round(float(score/Decimal(len(allowed))*100),1)
    return {"attempt_id":attempt["id"],"correct":correct,"total":len(allowed),"percentage":pct,
      "readiness":"strong" if pct>=80 else "developing" if pct>=60 else "needs_review"}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>الدرس التالي</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:900px;margin:auto;padding:18px}.box,.q{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.muted{color:#667085}.good{color:#067647}.bad{color:#b42318}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}input,button{padding:11px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}input.answer{width:100%;box-sizing:border-box}.asset{max-width:100%;border-radius:10px}</style><main>
<div class=box><a href="/student">العودة لبوابة الطالب</a><h1 id=title>الدرس</h1><div id=meta class=muted></div></div><div id=body></div>
<script>
const lessonId=Number(location.pathname.split('/').pop());let data=null;
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let s=await fetch('/api/student/session',{cache:'no-store'}).then(r=>r.json()).catch(()=>({authenticated:false}));if(!s.authenticated){body.innerHTML='<div class=box>انتهت جلسة الطالب. <a href="/student">ارجع لبوابة الطالب لتسجيل الدخول.</a></div>';return}let r=await fetch('/api/student/lessons/'+lessonId,{cache:'no-store'}),x=await r.json();if(!r.ok){body.innerHTML='<div class=box>'+esc(x.detail||'تعذر تحميل الدرس')+'</div>';return}data=x;title.textContent=x.lesson.title;meta.textContent=(x.lesson.subject_name||'')+' · '+(x.lesson.grade_name||'')+' · '+(x.lesson.unit_title||'');body.innerHTML='<div class=box><h2>مفاهيم الدرس من الهيكل المعتمد</h2><div class=grid>'+x.concepts.map(c=>'<div class=card>'+esc(c.title)+'</div>').join('')+'</div><p class=muted>'+esc(x.content_note)+'</p></div><div class=box><h2>محتوى الدرس من المصدر</h2>'+(x.source_pages.length?x.source_pages.map(p=>'<div class=card><div class=muted>'+esc(p.filename)+' · صفحة '+p.page_number+'</div><div style="white-space:pre-wrap;line-height:1.9">'+esc(p.extracted_text)+'</div></div>').join(''):'<p class=muted>لم يتم ربط صفحات شرح مصدرية بهذا الدرس حتى الآن. لن يعرض النظام شرحًا مولدًا بدلًا منها.</p>')+'</div><div class=box><h2>اختبار تمهيدي من الأسئلة المعتمدة</h2>'+(x.prior_mastery==null?'':'<p class=muted>إتقانك السابق في هذا الدرس: '+x.prior_mastery+'%</p>')+x.diagnostic_questions.map((q,i)=>'<div class=q><b>سؤال '+(i+1)+'</b>'+(q.has_asset?'<div><img class=asset src="/api/practice/questions/'+q.id+'/asset"></div>':'')+'<div>'+esc(q.text_verbatim)+'</div><input class=answer id="a_'+q.id+'" placeholder="اكتب الإجابة"></div>').join('')+(x.diagnostic_questions.length?'<button onclick="submitDiag()">تصحيح الاختبار التمهيدي</button>':'<p class=muted>لا توجد أسئلة معتمدة كافية لهذا الدرس بعد.</p>')+'<div id=res></div></div>'}
async function submitDiag(){let answers=data.diagnostic_questions.map(q=>({question_id:q.id,answer:document.getElementById('a_'+q.id).value}));let r=await fetch('/api/student/lessons/'+lessonId+'/diagnostic',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers})}),x=await r.json();if(!r.ok){res.textContent=x.detail||'تعذر التصحيح';return}res.innerHTML='<div class="card '+(x.percentage>=80?'good':'bad')+'"><b>النتيجة '+x.percentage+'%</b><div>'+(x.percentage>=80?'أداء قوي في الاختبار التمهيدي.':'تحتاج مراجعة وتدريب على مفاهيم الدرس قبل الانتقال الكامل.')+'</div></div>'}
load()
</script></main></html>'''

@app.get("/student/lesson/{lesson_id}",response_class=HTMLResponse)
def student_lesson_page(lesson_id:int): return PAGE
