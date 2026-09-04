from __future__ import annotations

import os

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin


def collect_alerts():
    failure_threshold=float(os.getenv("WHATSAPP_FAILURE_ALERT_PCT","10") or 10)
    stuck_minutes=int(os.getenv("WHATSAPP_STUCK_SENDING_MINUTES","10") or 10)
    queue_age_minutes=int(os.getenv("WHATSAPP_QUEUED_ALERT_MINUTES","30") or 30)
    alerts=[]
    with connect() as con:
        vals=con.execute("""SELECT
          (SELECT count(*) FROM documents WHERE subject_id IS NULL OR grade_level_id IS NULL OR curriculum_version_id IS NULL OR term_id IS NULL) unassigned_documents,
          (SELECT count(*) FROM questions q WHERE q.approved=TRUE AND (
             q.accepted_answer IS NULL OR btrim(q.accepted_answer)='' OR q.lesson_id IS NULL
             OR NOT EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id)
             OR NOT EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
             OR NOT EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id))) invalid_approved_questions,
          (SELECT count(DISTINCT qq.quiz_id) FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id WHERE q.approved=FALSE) invalid_quizzes,
          (SELECT count(*) FROM students WHERE external_code IS NULL OR btrim(external_code)='') students_without_code,
          (SELECT count(*) FROM guardians WHERE active=TRUE AND whatsapp_opt_in=FALSE) guardians_without_optin
        """).fetchone()
        wa=con.execute("""SELECT
          count(*) total,
          count(*) FILTER(WHERE status='failed') failed,
          count(*) FILTER(WHERE status='sending' AND created_at<now()-(%s*interval '1 minute')) stuck_sending,
          count(*) FILTER(WHERE status='queued' AND created_at<now()-(%s*interval '1 minute')) old_queued,
          count(*) FILTER(WHERE status='failed' AND attempts_count>=5) retry_exhausted,
          count(*) FILTER(WHERE delivery_status='failed') provider_failed
          FROM parent_notifications""",(stuck_minutes,queue_age_minutes)).fetchone()

    if int(vals["unassigned_documents"] or 0):
        alerts.append({"severity":"warning","source":"content","title":"ملفات PDF غير مصنفة","detail":f'{vals["unassigned_documents"]} ملف يحتاج مادة/صف/منهج/ترم',"path":"/admin/document-recovery"})
    if int(vals["invalid_approved_questions"] or 0):
        alerts.append({"severity":"error","source":"questions","title":"أسئلة معتمدة غير مكتملة","detail":f'{vals["invalid_approved_questions"]} سؤال يحتاج مراجعة فورية',"path":"/admin/workflow"})
    if int(vals["invalid_quizzes"] or 0):
        alerts.append({"severity":"error","source":"quizzes","title":"اختبارات غير سليمة","detail":f'{vals["invalid_quizzes"]} اختبار يحتوي سؤالًا غير معتمد',"path":"/admin/quiz-builder"})
    if int(vals["students_without_code"] or 0):
        alerts.append({"severity":"error","source":"students","title":"طلاب بدون كود دخول","detail":f'{vals["students_without_code"]} طالب',"path":"/admin/students"})
    if int(vals["guardians_without_optin"] or 0):
        alerts.append({"severity":"info","source":"guardians","title":"أولياء أمور بدون موافقة واتساب","detail":f'{vals["guardians_without_optin"]} ولي أمر',"path":"/admin/parents"})

    total=int(wa["total"] or 0); failed=int(wa["failed"] or 0)
    failure_pct=round(failed/total*100,1) if total else 0.0
    if total>=5 and failure_pct>=failure_threshold:
        alerts.append({"severity":"error","source":"whatsapp","title":"ارتفاع فشل واتساب","detail":f'{failure_pct}% من الرسائل فشلت',"path":"/admin/whatsapp-monitor"})
    if int(wa["stuck_sending"] or 0):
        alerts.append({"severity":"error","source":"whatsapp","title":"رسائل واتساب عالقة","detail":f'{wa["stuck_sending"]} رسالة عالقة في sending',"path":"/admin/whatsapp-monitor"})
    if int(wa["retry_exhausted"] or 0):
        alerts.append({"severity":"error","source":"whatsapp","title":"استنفاد محاولات واتساب","detail":f'{wa["retry_exhausted"]} رسالة وصلت للحد الأقصى',"path":"/admin/whatsapp-monitor"})
    if int(wa["old_queued"] or 0):
        alerts.append({"severity":"warning","source":"whatsapp","title":"رسائل واتساب قديمة في الانتظار","detail":f'{wa["old_queued"]} رسالة',"path":"/admin/whatsapp-monitor"})
    if int(wa["provider_failed"] or 0):
        alerts.append({"severity":"warning","source":"whatsapp","title":"Meta أبلغت عن فشل تسليم","detail":f'{wa["provider_failed"]} رسالة',"path":"/admin/whatsapp-monitor"})

    missing=[]
    envs={
      "DATABASE_URL":os.getenv("DATABASE_URL","").strip(),
      "ADMIN_API_KEY":os.getenv("ADMIN_API_KEY","").strip(),
      "WHATSAPP_ACCESS_TOKEN":os.getenv("WHATSAPP_ACCESS_TOKEN","").strip(),
      "WHATSAPP_PHONE_NUMBER_ID":os.getenv("WHATSAPP_PHONE_NUMBER_ID","").strip(),
      "WHATSAPP_WEBHOOK_VERIFY_TOKEN":os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN","").strip(),
      "META_APP_SECRET":os.getenv("META_APP_SECRET","").strip(),
    }
    for k,v in envs.items():
        if not v: missing.append(k)
    if missing:
        alerts.append({"severity":"warning","source":"configuration","title":"إعدادات تشغيل ناقصة","detail":"، ".join(missing),"path":"/admin/readiness"})

    rank={"error":0,"warning":1,"info":2}
    alerts.sort(key=lambda a:(rank.get(a["severity"],9),a["source"],a["title"]))
    return {
      "healthy":not any(a["severity"]=="error" for a in alerts),
      "error_count":sum(1 for a in alerts if a["severity"]=="error"),
      "warning_count":sum(1 for a in alerts if a["severity"]=="warning"),
      "info_count":sum(1 for a in alerts if a["severity"]=="info"),
      "alerts":alerts,
    }


PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مركز التنبيهات</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1000px;margin:auto;padding:18px}.box{background:#fff;padding:16px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.alert{padding:12px;border-radius:12px;margin:9px 0;border:1px solid #ddd}.error{color:#b42318;border-color:#f3b4ad}.warning{color:#b54708;border-color:#f1cf9d}.info{color:#175cd3;border-color:#b9cdf7}.ok{color:#067647}.muted{color:#667085}a{color:inherit}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/readiness">جاهزية النظام</a> · <a href="/admin/diagnostics">تشخيص البيانات</a></div>
<div class=box><h1>مركز التنبيهات</h1><div id=sum class=muted></div><div id=list>جارٍ التحميل...</div></div>
<script>
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let r=await fetch('/api/admin/alert-center');if(r.status===401){location.href='/admin/login';return}let x=await r.json();sum.innerHTML='أخطاء: <b>'+x.error_count+'</b> · تحذيرات: <b>'+x.warning_count+'</b> · معلومات: <b>'+x.info_count+'</b>';list.innerHTML=x.alerts.length?x.alerts.map(a=>'<div class="alert '+e(a.severity)+'"><b>'+e(a.title)+'</b><div>'+e(a.detail)+'</div><div class=muted>'+e(a.source)+'</div><a href="'+e(a.path)+'">فتح الإجراء</a></div>').join(''):'<div class=ok>✅ لا توجد تنبيهات حالية</div>'}
load()
</script></main></html>'''


@app.get("/api/admin/alert-center", dependencies=[Depends(require_admin)])
def alert_center():
    return collect_alerts()


@app.get("/api/admin/alert-center/summary", dependencies=[Depends(require_admin)])
def alert_center_summary():
    x=collect_alerts()
    return {"healthy":x["healthy"],"error_count":x["error_count"],"warning_count":x["warning_count"],"info_count":x["info_count"],"total":len(x["alerts"])}


@app.get("/admin/alerts", response_class=HTMLResponse)
def alerts_page():
    return PAGE
