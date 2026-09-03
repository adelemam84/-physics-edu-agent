from __future__ import annotations
import secrets
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .main import app
from .db import connect
from .security import require_admin

class StudentIn(BaseModel):
    name:str
    phone:str|None=None
    email:str|None=None
    external_code:str|None=None

def new_code():
    return "PHY-"+secrets.token_hex(3).upper()

@app.get("/api/admin/students",dependencies=[Depends(require_admin)])
def list_students():
    with connect() as con:
        return list(con.execute("""SELECT s.id,s.name,s.external_code,s.phone,s.email,s.created_at,
          count(distinct a.id) attempts,count(distinct g.id) guardians
          FROM students s LEFT JOIN attempts a ON a.student_id=s.id
          LEFT JOIN student_guardians sg ON sg.student_id=s.id LEFT JOIN guardians g ON g.id=sg.guardian_id
          GROUP BY s.id ORDER BY s.id DESC""").fetchall())

@app.post("/api/admin/students",dependencies=[Depends(require_admin)])
def add_student(p:StudentIn):
    name=p.name.strip()
    if not name: raise HTTPException(400,"اسم الطالب مطلوب")
    with connect() as con:
        for _ in range(8):
            code=(p.external_code or new_code()).strip().upper()
            try:
                return con.execute("""INSERT INTO students(name,phone,email,external_code)
                  VALUES(%s,%s,%s,%s) RETURNING id,name,phone,email,external_code,created_at""",
                  (name,p.phone,p.email,code)).fetchone()
            except Exception:
                if p.external_code: raise HTTPException(409,"كود الطالب مستخدم بالفعل")
        raise HTTPException(500,"تعذر إنشاء كود فريد")

@app.post("/api/admin/students/{student_id}/regenerate-code",dependencies=[Depends(require_admin)])
def regenerate(student_id:int):
    with connect() as con:
        if not con.execute("SELECT 1 FROM students WHERE id=%s",(student_id,)).fetchone(): raise HTTPException(404,"Student not found")
        for _ in range(8):
            code=new_code()
            try:return con.execute("UPDATE students SET external_code=%s WHERE id=%s RETURNING id,name,external_code",(code,student_id)).fetchone()
            except Exception: pass
    raise HTTPException(500,"تعذر إنشاء كود فريد")

@app.get("/api/admin/quizzes",dependencies=[Depends(require_admin)])
def admin_quizzes():
    with connect() as con:
        return list(con.execute("""SELECT q.id,q.title,q.published,q.created_at,q.duration_minutes,count(qq.question_id) question_count
          FROM quizzes q LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id GROUP BY q.id ORDER BY q.id DESC""").fetchall())

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>إدارة الطلاب والاختبارات</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:white;padding:16px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}button{cursor:pointer}.ok{color:#067647}.muted{color:#667085;font-size:13px}</style><main>
<h1>إدارة الطلاب والاختبارات</h1><div class="box row"><input id=key type=password placeholder=ADMIN_API_KEY><button onclick=save()>حفظ المفتاح</button><a href="/admin/quiz-builder">منشئ الاختبارات</a></div>
<div class=box><h2>إضافة طالب</h2><div class=row><input id=name placeholder="اسم الطالب"><input id=phone placeholder="هاتف الطالب - اختياري"><input id=email placeholder="البريد - اختياري"><input id=code placeholder="كود مخصص - أو اتركه تلقائي"><button onclick=add()>إضافة وإنشاء الكود</button></div><p id=msg class=muted></p></div>
<div class=box><h2>الطلاب</h2><div id=students></div></div><div class=box><h2>الاختبارات</h2><div id=quizzes></div></div>
<script>key.value=localStorage.pk||'';const H=()=>({'X-Admin-Key':localStorage.pk||''});function save(){localStorage.pk=key.value;load()}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function add(){let b={name:name.value,phone:phone.value||null,email:email.value||null,external_code:code.value||null};let r=await fetch('/api/admin/students',{method:'POST',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify(b)}),x=await r.json();msg.textContent=r.ok?'تم إنشاء الطالب — الكود: '+x.external_code:(x.detail||'حدث خطأ');if(r.ok){name.value=phone.value=email.value=code.value='';load()}}
async function regen(id){let r=await fetch('/api/admin/students/'+id+'/regenerate-code',{method:'POST',headers:H()}),x=await r.json();if(r.ok){alert('الكود الجديد: '+x.external_code);load()}}
async function pub(id,v){let r=await fetch('/api/quizzes/'+id+'/publish?published='+v,{method:'PATCH',headers:H()}),x=await r.json();if(!r.ok)alert(typeof x.detail==='object'?(x.detail.message||JSON.stringify(x.detail)):x.detail);load()}
async function copyLink(id){await navigator.clipboard.writeText(location.origin+'/student/quiz/'+id);alert('تم نسخ رابط الاختبار')}
async function load(){let [sr,qr]=await Promise.all([fetch('/api/admin/students',{headers:H()}),fetch('/api/admin/quizzes',{headers:H()})]);if(sr.ok){let a=await sr.json();students.innerHTML='<table><tr><th>الطالب</th><th>الكود</th><th>المحاولات</th><th>أولياء الأمور</th><th></th></tr>'+a.map(s=>`<tr><td>${esc(s.name)}</td><td><b>${esc(s.external_code||'—')}</b></td><td>${s.attempts}</td><td>${s.guardians}</td><td><button onclick=regen(${s.id})>كود جديد</button></td></tr>`).join('')+'</table>'}else students.textContent='أدخل مفتاح الإدارة الصحيح';
if(qr.ok){let a=await qr.json();quizzes.innerHTML='<table><tr><th>الاختبار</th><th>الأسئلة</th><th>الحالة</th><th>الإجراءات</th></tr>'+a.map(q=>`<tr><td>${esc(q.title)}</td><td>${q.question_count}</td><td class=${q.published?'ok':''}>${q.published?'منشور':'مسودة'}</td><td><button onclick=pub(${q.id},${!q.published})>${q.published?'إلغاء النشر':'نشر'}</button> <button onclick=copyLink(${q.id})>نسخ رابط الطالب</button></td></tr>`).join('')+'</table>'}}load()</script></main></html>'''
@app.get("/admin/students",response_class=HTMLResponse)
def students_page(): return PAGE
