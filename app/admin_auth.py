from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .main import app
from .security import COOKIE_NAME, SESSION_MAX_AGE, admin_configured, admin_session_valid, make_admin_session_token, require_admin, validate_admin_key
from .services.rate_limit import enforce_request_policy


class LoginIn(BaseModel):
    key: str


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


@app.post("/api/admin/logout", dependencies=[Depends(require_admin)])
def admin_logout(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return {"ok": True}


LOGIN = r'''<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>دخول الإدارة</title><style>
body{font-family:system-ui;background:#f5f7fb;margin:0;color:#172033;display:grid;min-height:100vh;place-items:center}.card{width:min(92vw,430px);background:#fff;border-radius:18px;padding:22px;box-shadow:0 8px 28px #0001}input,button{width:100%;box-sizing:border-box;padding:12px;border:1px solid #ccd2dd;border-radius:10px;font:inherit;margin:6px 0}button{cursor:pointer}.muted{color:#667085;font-size:13px}.bad{color:#b42318}.ok{color:#067647}</style><div class=card><h1>دخول الإدارة</h1><p class=muted>يتم إنشاء جلسة آمنة في المتصفح، ولن يتم حفظ مفتاح الإدارة في Local Storage.</p><input id=key type=password autocomplete=current-password placeholder="ADMIN_API_KEY"><button onclick=login()>دخول</button><div id=msg class=muted></div></div><script>
async function login(){msg.className='muted';msg.textContent='جارٍ التحقق...';let r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:key.value})}),x=await r.json();if(!r.ok){msg.className='bad';msg.textContent=x.detail||'تعذر تسجيل الدخول';return}msg.className='ok';msg.textContent='تم تسجيل الدخول';location.href='/admin/dashboard'}
fetch('/api/admin/session').then(r=>r.json()).then(x=>{if(x.authenticated)location.href='/admin/dashboard'})
</script></html>'''


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    return LOGIN
