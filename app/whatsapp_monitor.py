from __future__ import annotations

from fastapi import Depends
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin


@app.get("/api/admin/whatsapp-monitor", dependencies=[Depends(require_admin)])
def whatsapp_monitor():
    with connect() as con:
        totals = con.execute(
            """SELECT
                 count(*) total,
                 count(*) FILTER(WHERE status='queued') queued,
                 count(*) FILTER(WHERE status='sending') sending,
                 count(*) FILTER(WHERE status='sent') sent,
                 count(*) FILTER(WHERE status='failed') failed,
                 count(*) FILTER(WHERE status='skipped') skipped,
                 count(*) FILTER(WHERE delivery_status='delivered') delivered,
                 count(*) FILTER(WHERE delivery_status='read') read,
                 count(*) FILTER(WHERE delivery_status='failed') provider_failed
               FROM parent_notifications"""
        ).fetchone()
        recent = list(con.execute(
            """SELECT n.id,n.notification_type,n.status,n.delivery_status,n.attempts_count,
                      n.created_at,n.sent_at,n.delivered_at,n.read_at,n.provider_error_code,
                      n.provider_error_title,s.name student_name,g.name guardian_name
               FROM parent_notifications n
               JOIN students s ON s.id=n.student_id
               JOIN guardians g ON g.id=n.guardian_id
               ORDER BY n.id DESC LIMIT 50"""
        ).fetchall())
        daily = list(con.execute(
            """SELECT to_char(date_trunc('day',created_at),'YYYY-MM-DD') day,
                      count(*) total,
                      count(*) FILTER(WHERE status='sent') sent,
                      count(*) FILTER(WHERE status='failed') failed,
                      count(*) FILTER(WHERE delivery_status='delivered') delivered,
                      count(*) FILTER(WHERE delivery_status='read') read
               FROM parent_notifications
               WHERE created_at>=now()-interval '14 days'
               GROUP BY 1 ORDER BY 1"""
        ).fetchall())
    total=int(totals["total"] or 0)
    sent=int(totals["sent"] or 0)
    delivered=int(totals["delivered"] or 0)
    read=int(totals["read"] or 0)
    return {
        "counts":dict(totals),
        "rates":{
            "send_success_pct": round(sent/total*100,1) if total else 0.0,
            "delivery_pct_of_sent": round(delivered/sent*100,1) if sent else 0.0,
            "read_pct_of_delivered": round(read/delivered*100,1) if delivered else 0.0,
        },
        "recent":recent,
        "daily":daily,
    }


PAGE=r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>مراقبة واتساب</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:16px}
.box{background:#fff;border-radius:16px;padding:14px;margin:10px 0;box-shadow:0 3px 14px #0001}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{padding:14px;border:1px solid #e7eaf0;border-radius:13px}.n{font-size:27px;font-weight:800}
table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid #eee;text-align:right;font-size:14px}.muted{color:#667085}.bad{color:#b42318}.ok{color:#067647}.warn{color:#b54708}a{color:#175cd3;text-decoration:none}
@media(max-width:760px){table{display:block;overflow-x:auto;white-space:nowrap}}
</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/parents">أولياء الأمور وواتساب</a></div>
<div class=box><h1>مراقبة واتساب</h1><div id=cards class=cards></div><div id=rates class=muted style="margin-top:12px"></div></div>
<div class=box><h2>آخر الرسائل</h2><div id=recent>جارٍ التحميل...</div></div>
<script>
function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function load(){let r=await fetch('/api/admin/whatsapp-monitor');if(r.status===401){location.href='/admin/login';return}let x=await r.json(),c=x.counts||{};
let specs=[['الإجمالي',c.total],['Queued',c.queued],['Sending',c.sending],['Sent',c.sent],['Delivered',c.delivered],['Read',c.read],['Failed',c.failed],['Provider failed',c.provider_failed]];
cards.innerHTML=specs.map(v=>'<div class=card><div class=muted>'+e(v[0])+'</div><div class=n>'+e(v[1]||0)+'</div></div>').join('');
rates.innerHTML='نجاح الإرسال: <b>'+x.rates.send_success_pct+'%</b> · الوصول من المرسل: <b>'+x.rates.delivery_pct_of_sent+'%</b> · القراءة من الواصل: <b>'+x.rates.read_pct_of_delivered+'%</b>';
recent.innerHTML=x.recent.length?'<table><tr><th>#</th><th>الطالب</th><th>ولي الأمر</th><th>النوع</th><th>الحالة</th><th>التسليم</th><th>المحاولات</th><th>الخطأ</th></tr>'+x.recent.map(n=>'<tr><td>'+n.id+'</td><td>'+e(n.student_name)+'</td><td>'+e(n.guardian_name)+'</td><td>'+e(n.notification_type)+'</td><td>'+e(n.status)+'</td><td>'+e(n.delivery_status||'—')+'</td><td>'+e(n.attempts_count)+'</td><td class=bad>'+e(n.provider_error_title||'')+'</td></tr>').join('')+'</table>':'لا توجد رسائل بعد';
}
load()
</script></main></html>'''


@app.get("/admin/whatsapp-monitor", response_class=HTMLResponse)
def whatsapp_monitor_page():
    return PAGE
