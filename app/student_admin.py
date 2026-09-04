from __future__ import annotations
import csv
import io
import secrets
from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response, Response
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
    return "SCI-"+secrets.token_hex(5).upper()

@app.get("/api/admin/students",dependencies=[Depends(require_admin)])
def list_students():
    with connect() as con:
        return list(con.execute("""SELECT s.id,s.name,s.external_code,s.phone,s.email,s.created_at,
          count(distinct a.id) attempts,count(distinct g.id) guardians
          FROM students s LEFT JOIN attempts a ON a.student_id=s.id
          LEFT JOIN guardians g ON g.student_id=s.id
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

@app.get("/api/admin/students/import-template.csv",dependencies=[Depends(require_admin)])
def students_import_template():
    body="name,phone,email,external_code\nطالب مثال,01000000000,,\n"
    return Response("\ufeff"+body,media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":"attachment; filename=students_import_template.csv"})

@app.get("/api/admin/students/import-template.csv",dependencies=[Depends(require_admin)])
def students_import_template():
    body="name,phone,email,external_code\nStudent Example,,,\n"
    return Response("\ufeff"+body,media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":"attachment; filename=students_import_template.csv"})

@app.post("/api/admin/students/import-csv",dependencies=[Depends(require_admin)])
async def import_students_csv(file:UploadFile=File(...)):
    raw=await file.read()
    if len(raw)>2_000_000: raise HTTPException(413,"ملف الطلاب أكبر من الحد المسموح")
    try:text=raw.decode("utf-8-sig")
    except UnicodeDecodeError: raise HTTPException(400,"احفظ الملف CSV بترميز UTF-8")
    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames: raise HTTPException(400,"ملف CSV فارغ")
    aliases={"name":["name","اسم","اسم الطالب"],"phone":["phone","الهاتف","رقم الهاتف"],"email":["email","البريد","البريد الإلكتروني"],"external_code":["external_code","code","الكود","كود الطالب"]}
    norm={str(h).strip().lower():h for h in reader.fieldnames}
    def col(key):
        for a in aliases[key]:
            if a.lower() in norm:return norm[a.lower()]
        return None
    name_col=col("name")
    if not name_col: raise HTTPException(400,"يجب وجود عمود name أو اسم الطالب")
    phone_col,email_col,code_col=col("phone"),col("email"),col("external_code")
    created=[];skipped=[];errors=[]
    with connect() as con:
        for n,row in enumerate(reader,start=2):
            name=(row.get(name_col) or "").strip()
            if not name:
                errors.append({"row":n,"error":"اسم الطالب فارغ"});continue
            phone=(row.get(phone_col) or "").strip() if phone_col else None
            email=(row.get(email_col) or "").strip() if email_col else None
            requested=(row.get(code_col) or "").strip().upper() if code_col else ""
            try:
                if requested and con.execute("SELECT 1 FROM students WHERE external_code=%s",(requested,)).fetchone():
                    skipped.append({"row":n,"name":name,"reason":"الكود موجود"});continue
                code=requested
                if not code:
                    for _ in range(12):
                        code=new_code()
                        if not con.execute("SELECT 1 FROM students WHERE external_code=%s",(code,)).fetchone():break
                item=con.execute("""INSERT INTO students(name,phone,email,external_code)
                  VALUES(%s,%s,%s,%s) RETURNING id,name,external_code""",(name,phone or None,email or None,code)).fetchone()
                created.append(item)
            except Exception as e:
                errors.append({"row":n,"name":name,"error":str(e)[:200]})
    return {"created_count":len(created),"skipped_count":len(skipped),"error_count":len(errors),
            "created":created,"skipped":skipped[:50],"errors":errors[:50]}

@app.get("/api/admin/quizzes",dependencies=[Depends(require_admin)])
def admin_quizzes():
    with connect() as con:
        return list(con.execute("""SELECT q.id,q.title,q.published,q.created_at,q.duration_minutes,count(qq.question_id) question_count
          FROM quizzes q LEFT JOIN quiz_questions qq ON qq.quiz_id=q.id GROUP BY q.id ORDER BY q.id DESC""").fetchall())

PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>إدارة الطلاب والاختبارات</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:18px}.box{background:white;padding:16px;border-radius:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.row{display:flex;gap:8px;flex-wrap:wrap}input,button{padding:10px;border:1px solid #ccd2dd;border-radius:9px;font:inherit}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #eee;text-align:right}button{cursor:pointer}.ok{color:#067647}.muted{color:#667085;font-size:13px}</style><main>
<h1>إدارة الطلاب والاختبارات</h1><div class="box row"><input id=key type=password placeholder=ADMIN_API_KEY><button onclick=save()>حفظ المفتاح</button><a href="/admin/quiz-builder">منشئ الاختبارات</a></div>
<div class=box><h2>إضافة طالب</h2><div class=row><input id=name placeholder="اسم الطالب"><input id=phone placeholder="هاتف الطالب - اختياري"><input id=email placeholder="البريد - اختياري"><input id=code placeholder="كود مخصص - أو اتركه تلقائي"><button onclick=add()>إضافة وإنشاء الكود</button></div><p id=msg class=muted></p></div>
<div class=box><h2>استيراد الطلاب دفعة واحدة</h2><p class=muted>ارفع CSV من Excel. الأعمدة المدعومة: name/اسم الطالب، phone، email، external_code (اختياري).</p><div class=row><input id=csvfile type=file accept=".csv,text/csv"><button onclick=importCsv()>استيراد CSV</button><button onclick="downloadCsv('/api/admin/students/import-template.csv','students_import_template.csv')">تحميل نموذج CSV</button></div><p id=importMsg class=muted></p></div>
<div class=box><h2>الطلاب</h2><div id=students></div></div><div class=box><h2>الاختبارات</h2><div id=quizzes></div></div>
<script>key.value=localStorage.pk||'';const H=()=>({'X-Admin-Key':localStorage.pk||''});function save(){localStorage.pk=key.value;load()}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function add(){let b={name:name.value,phone:phone.value||null,email:email.value||null,external_code:code.value||null};let r=await fetch('/api/admin/students',{method:'POST',headers:{...H(),'Content-Type':'application/json'},body:JSON.stringify(b)}),x=await r.json();msg.textContent=r.ok?'تم إنشاء الطالب — الكود: '+x.external_code:(x.detail||'حدث خطأ');if(r.ok){name.value=phone.value=email.value=code.value='';load()}}
async function downloadCsv(url,name){let r=await fetch(url,{headers:H()});if(!r.ok){importMsg.textContent='تعذر تحميل النموذج';return}let b=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function downloadCsv(url,name){let r=await fetch(url,{headers:H()});if(!r.ok){importMsg.textContent='تعذر تحميل النموذج';return}let b=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function importCsv(){if(!csvfile.files.length){importMsg.textContent='اختر ملف CSV أولًا';return}let fd=new FormData();fd.append('file',csvfile.files[0]);let r=await fetch('/api/admin/students/import-csv',{method:'POST',headers:H(),body:fd}),x=await r.json();importMsg.textContent=r.ok?('تم إضافة '+x.created_count+' طالب · تخطي '+x.skipped_count+' · أخطاء '+x.error_count):(x.detail||'تعذر الاستيراد');if(r.ok)load()}
async function regen(id){let r=await fetch('/api/admin/students/'+id+'/regenerate-code',{method:'POST',headers:H()}),x=await r.json();if(r.ok){alert('الكود الجديد: '+x.external_code);load()}}
async function pub(id,v){let r=await fetch('/api/quizzes/'+id+'/publish?published='+v,{method:'PATCH',headers:H()}),x=await r.json();if(!r.ok)alert(typeof x.detail==='object'?(x.detail.message||JSON.stringify(x.detail)):x.detail);load()}
async function copyLink(id){await navigator.clipboard.writeText(location.origin+'/student/quiz/'+id);alert('تم نسخ رابط الاختبار')}
async function load(){let [sr,qr]=await Promise.all([fetch('/api/admin/students',{headers:H()}),fetch('/api/admin/quizzes',{headers:H()})]);if(sr.ok){let a=await sr.json();students.innerHTML='<table><tr><th>الطالب</th><th>الكود</th><th>المحاولات</th><th>أولياء الأمور</th><th></th></tr>'+a.map(s=>`<tr><td>${esc(s.name)}</td><td><b>${esc(s.external_code||'—')}</b></td><td>${s.attempts}</td><td>${s.guardians}</td><td><button onclick=regen(${s.id})>كود جديد</button> <a href="/admin/students/${s.id}/knowledge-map">خريطة المعرفة</a></td></tr>`).join('')+'</table>'}else students.textContent='أدخل مفتاح الإدارة الصحيح';
if(qr.ok){let a=await qr.json();quizzes.innerHTML='<table><tr><th>الاختبار</th><th>الأسئلة</th><th>الحالة</th><th>الإجراءات</th></tr>'+a.map(q=>`<tr><td>${esc(q.title)}</td><td>${q.question_count}</td><td class=${q.published?'ok':''}>${q.published?'منشور':'مسودة'}</td><td><button onclick=pub(${q.id},${!q.published})>${q.published?'إلغاء النشر':'نشر'}</button> <button onclick=copyLink(${q.id})>نسخ رابط الطالب</button></td></tr>`).join('')+'</table>'}}load()</script></main></html>'''
@app.get("/admin/students",response_class=HTMLResponse)
def students_page(): return PAGE
