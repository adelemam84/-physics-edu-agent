from __future__ import annotations
import os
from fastapi import Depends
from fastapi.responses import HTMLResponse
from .main import app
from .db import connect
from .security import require_admin

@app.get("/api/admin/system-readiness",dependencies=[Depends(require_admin)])
def system_readiness():
    with connect() as con:
        db={
          "subjects":con.execute("SELECT count(*) n FROM subjects WHERE active=TRUE").fetchone()["n"],
          "grades":con.execute("SELECT count(*) n FROM grade_levels WHERE active=TRUE").fetchone()["n"],
          "curricula":con.execute("SELECT count(*) n FROM curriculum_versions WHERE active=TRUE").fetchone()["n"],
          "terms":con.execute("SELECT count(*) n FROM academic_terms").fetchone()["n"],
          "units":con.execute("SELECT count(*) n FROM units").fetchone()["n"],
          "lessons":con.execute("SELECT count(*) n FROM lessons").fetchone()["n"],
          "concepts":con.execute("SELECT count(*) n FROM concepts").fetchone()["n"],
          "documents":con.execute("SELECT count(*) n FROM documents").fetchone()["n"],
          "unassigned_documents":con.execute("""SELECT count(*) n FROM documents
            WHERE subject_id IS NULL OR grade_level_id IS NULL OR curriculum_version_id IS NULL OR term_id IS NULL""").fetchone()["n"],
          "document_pages":con.execute("SELECT count(*) n FROM document_pages").fetchone()["n"],
          "question_assets":con.execute("SELECT count(*) n FROM question_assets").fetchone()["n"],
          "skills":con.execute("SELECT count(*) n FROM skills WHERE active=TRUE").fetchone()["n"],
          "approved_questions":con.execute("SELECT count(*) n FROM questions WHERE approved=TRUE").fetchone()["n"],
          "unclassified_questions":con.execute("""SELECT count(*) n FROM questions q WHERE q.approved=FALSE AND
            (q.subject_id IS NULL OR q.grade_level_id IS NULL OR q.curriculum_version_id IS NULL OR q.term_id IS NULL OR
             q.unit_id IS NULL OR q.lesson_id IS NULL OR NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
             OR NOT EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id))""").fetchone()["n"],
          "students":con.execute("SELECT count(*) n FROM students").fetchone()["n"],
          "guardians_opted_in":con.execute("SELECT count(*) n FROM guardians WHERE active=TRUE AND whatsapp_opt_in=TRUE").fetchone()["n"],
        }
    wa={
      "token":bool(os.getenv("WHATSAPP_ACCESS_TOKEN","").strip()),
      "phone_id":bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID","").strip()),
      "graph_version":bool(os.getenv("WHATSAPP_GRAPH_VERSION","").strip()),
      "result_template":bool(os.getenv("WHATSAPP_RESULT_TEMPLATE","").strip()),
      "low_template":bool(os.getenv("WHATSAPP_LOW_SCORE_TEMPLATE","").strip()),
      "weekly_template":bool(os.getenv("WHATSAPP_WEEKLY_TEMPLATE","").strip()),
      "webhook_verify_token":bool(os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN","").strip()),
      "meta_app_secret":bool(os.getenv("META_APP_SECRET","").strip()),
    }
    wa_ready=all(wa.values())
    checks=[
      {"name":"الهيكل الأكاديمي","ok":db["subjects"]>0 and db["grades"]>0 and db["curricula"]>0 and db["terms"]>0,
       "detail":f'{db["subjects"]} مواد · {db["grades"]} صفوف · {db["curricula"]} مناهج · {db["terms"]} ترم'},
      {"name":"مصادر المحتوى","ok":db["documents"]>0 and db["document_pages"]>0,
       "detail":f'{db["documents"]} ملفات · {db["document_pages"]} صفحات مفهرسة'},
      {"name":"التصنيف العلمي","ok":db["concepts"]>0 and db["skills"]>=9,
       "detail":f'{db["concepts"]} مفاهيم · {db["skills"]} مهارات'},
      {"name":"بنك الأسئلة المعتمد","ok":db["approved_questions"]>0 and db["question_assets"]>=db["approved_questions"],
       "detail":f'{db["approved_questions"]} سؤال معتمد · {db["question_assets"]} قصاصة محفوظة'},
      {"name":"بيانات الطلاب","ok":db["students"]>0,"detail":f'{db["students"]} طالب'},
      {"name":"أولياء الأمور","ok":db["guardians_opted_in"]>0,"detail":f'{db["guardians_opted_in"]} موافقة واتساب'},
      {"name":"WhatsApp Cloud API","ok":wa_ready,
       "detail":"مكتمل" if wa_ready else "ناقص إعداد من إعدادات الاتصال/القوالب/Webhook"},
    ]
    actions=[]
    if db["curricula"]==0: actions.append({"title":"إنشاء المناهج والترمين","path":"/admin/academic","owner":"user"})
    if db["documents"]==0: actions.append({"title":"رفع ملفات PDF الأصلية","path":"/admin/document-recovery","owner":"user"})
    elif db["unassigned_documents"]>0: actions.append({"title":f'إعادة تصنيف {db["unassigned_documents"]} ملف PDF قديم داخل المنهج الصحيح',"path":"/admin/workflow","owner":"user"})
    if db["approved_questions"]==0: actions.append({"title":"استخراج ومراجعة واعتماد الأسئلة","path":"/admin/workflow","owner":"admin"})
    if db["students"]==0: actions.append({"title":"إضافة الطلاب وأكواد الدخول","path":"/admin/students","owner":"user"})
    if db["guardians_opted_in"]==0: actions.append({"title":"إضافة أولياء الأمور وتسجيل موافقة واتساب","path":"/admin/parents","owner":"user"})
    if not wa_ready: actions.append({"title":"إضافة إعدادات WhatsApp وقوالب Meta إلى Vercel","path":"/admin/parents","owner":"user"})
    return {"ready":all(x["ok"] for x in checks),"checks":checks,"counts":db,"whatsapp":wa,"next_actions":actions,
            "external_requirements":["ملفات PDF الأصلية للمناهج/الشرح وبنوك الأسئلة ومفاتيح الإجابة","بيانات الطلاب وأولياء الأمور الحقيقية","بيانات WhatsApp Cloud API وأسماء قوالب Meta المعتمدة"]}

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>جاهزية النظام</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:900px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.item{padding:12px;border-bottom:1px solid #eee}.ok{color:#067647}.bad{color:#b42318}.muted{color:#667085}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px}</style><main><div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/academic">الهيكل الأكاديمي</a> · <a href="/admin/workflow">المصادر والأسئلة</a></div><div id=out></div><script>
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function load(){let r=await fetch('/api/admin/system-readiness',{}),x=await r.json();if(!r.ok){out.innerHTML='<div class=box>تعذر الفحص</div>';return}out.innerHTML='<div class=box><h1>جاهزية النظام</h1>'+x.checks.map(c=>'<div class="item '+(c.ok?'ok':'bad')+'">'+(c.ok?'✅ ':'⚠️ ')+e(c.name)+'<div class=muted>'+e(c.detail)+'</div></div>').join('')+'</div><div class=box><h2>الخطوات التالية</h2>'+(x.next_actions.length?x.next_actions.map(v=>'<div class=item><a href="'+e(v.path)+'">'+e(v.title)+'</a><div class=muted>'+(v.owner==='user'?'مطلوب منك':'يُستكمل داخل النظام')+'</div></div>').join(''):'<div class="item ok">✅ لا توجد خطوات إعداد أساسية ناقصة</div>')+'</div><div class=box><h2>المدخلات الخارجية المطلوبة</h2>'+x.external_requirements.map(v=>'<div class=item>• '+e(v)+'</div>').join('')+'</div>'}load()</script></main></html>'''
@app.get("/admin/readiness",response_class=HTMLResponse)
def readiness_page(): return PAGE
