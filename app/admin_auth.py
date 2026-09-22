from __future__ import annotations

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .main import app
from .security import COOKIE_NAME, SESSION_MAX_AGE, admin_configured, admin_session_valid, make_admin_session_token, validate_admin_key
from .services.rate_limit import enforce_request_policy


class LoginIn(BaseModel):
    key: str = Field(min_length=1, max_length=512)


@app.get("/api/admin/session")
def admin_session_status(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"configured": admin_configured(), "authenticated": admin_session_valid(request)}


@app.post("/api/admin/login")
def admin_login(p: LoginIn, response: Response, request: Request):
    response.headers["Cache-Control"] = "no-store"
    enforce_request_policy(
        request,
        name="admin_login",
        default_limit=8,
        default_window_seconds=900,
    )
    if not admin_configured():
        raise HTTPException(503, "ADMIN_API_KEY is not configured")
    if not validate_admin_key(p.key.strip()):
        raise HTTPException(401, "مفتاح الإدارة غير صحيح")
    response.set_cookie(
        COOKIE_NAME,
        make_admin_session_token(),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"ok": True, "expires_in_seconds": SESSION_MAX_AGE}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


LOGIN = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول الإدارة</title><style>
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#d8dee9;--brand:#3157d5;--bad:#b42318;--ok:#067647}*{box-sizing:border-box}body{font-family:system-ui;background:linear-gradient(145deg,#eef3ff,var(--bg));margin:0;color:var(--text);display:grid;min-height:100vh;place-items:center;padding:18px}.card{width:min(94vw,450px);background:var(--card);border:1px solid #e6eaf1;border-radius:20px;padding:24px;box-shadow:0 16px 50px #10182816}.brand{font-size:13px;font-weight:800;color:var(--brand);margin-bottom:8px}.field{display:grid;gap:7px;margin:16px 0}.input-wrap{display:flex;gap:8px}.input-wrap input{flex:1;min-width:0}input,button{box-sizing:border-box;padding:12px;border:1px solid var(--line);border-radius:11px;font:inherit}button{cursor:pointer;background:#fff}button.primary{width:100%;background:var(--brand);border-color:var(--brand);color:#fff;font-weight:800}button:disabled{opacity:.65;cursor:wait}input:focus-visible,button:focus-visible{outline:3px solid #84adff;outline-offset:2px}.muted{color:var(--muted);font-size:13px;line-height:1.7}.bad{color:var(--bad)}.ok{color:var(--ok)}#toggle{white-space:nowrap}.secure{background:#f8faff;border:1px solid #e5ebff;padding:10px 12px;border-radius:12px;margin:12px 0}</style><main class=card><div class=brand>Physics Education AI Agent</div><h1>دخول الإدارة</h1><p class=muted>أدخل مفتاح الإدارة الخاص ببيئة Production. يتم إنشاء جلسة آمنة داخل المتصفح ولا يتم حفظ المفتاح في Local Storage.</p><div class=secure><b>🔐 تسجيل دخول آمن</b><div class=muted>الجلسة HttpOnly وتُستخدم بدل إرسال المفتاح مع كل طلب.</div></div><form id=loginForm onsubmit="login(event)"><div class=field><label for=key>مفتاح الإدارة</label><div class=input-wrap><input id=key name=key type=password autocomplete=current-password required maxlength=512 placeholder="ADMIN_API_KEY"><button id=toggle type=button onclick="toggleKey()" aria-label="إظهار أو إخفاء المفتاح">إظهار</button></div></div><button id=submitBtn class=primary type=submit>دخول</button><div id=msg class=muted role=status aria-live=polite></div></form></main><script>
function toggleKey(){let show=key.type==='password';key.type=show?'text':'password';toggle.textContent=show?'إخفاء':'إظهار';key.focus()}
async function login(ev){ev.preventDefault();msg.className='muted';msg.textContent='جارٍ التحقق...';submitBtn.disabled=true;submitBtn.textContent='جارٍ التحقق...';try{let r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:key.value})});let x=await r.json().catch(()=>({}));if(!r.ok){msg.className='bad';msg.textContent=x.detail||('تعذر تسجيل الدخول ('+r.status+')');return}msg.className='ok';msg.textContent='تم تسجيل الدخول بنجاح';location.href='/admin/dashboard'}catch(e){msg.className='bad';msg.textContent='تعذر الاتصال بالخادم. تحقق من الاتصال ثم أعد المحاولة.'}finally{submitBtn.disabled=false;submitBtn.textContent='دخول'}}
fetch('/api/admin/session').then(r=>r.json()).then(x=>{if(x.authenticated)location.href='/admin/dashboard';else if(x.configured===false){msg.className='bad';msg.textContent='مفتاح الإدارة غير مضبوط في بيئة التشغيل.'}}).catch(()=>{})
</script></html>'''


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    return LOGIN
