from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .db import connect
from .main import app
from .security import require_admin

CANVA_CLIENT_ID=os.getenv("CANVA_CLIENT_ID","").strip()
CANVA_CLIENT_SECRET=os.getenv("CANVA_CLIENT_SECRET","").strip()
CANVA_REDIRECT_URI=os.getenv("CANVA_REDIRECT_URI","").strip()
CANVA_PRODUCTION_REDIRECT="https://physics-edu-agent.vercel.app/api/integrations/canva/oauth/callback"
CANVA_SCOPES=os.getenv(
    "CANVA_SCOPES",
    "design:content:read design:content:write design:meta:read brandtemplate:content:read brandtemplate:meta:read",
).strip()


def _init_store():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS external_oauth_tokens(
          provider text PRIMARY KEY,
          access_token text,
          refresh_token text,
          token_type text,
          scope text,
          expires_at timestamptz,
          updated_at timestamptz NOT NULL DEFAULT now()
        )""")


def _redirect_uri(request: Request) -> str:
    if CANVA_REDIRECT_URI:
        return CANVA_REDIRECT_URI
    # OAuth providers require an exact stable redirect URI. Always use the
    # canonical production alias unless explicitly overridden for another env.
    return CANVA_PRODUCTION_REDIRECT


def _basic_auth() -> str:
    raw=f"{CANVA_CLIENT_ID}:{CANVA_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _save_tokens(data: dict):
    _init_store()
    expires=datetime.now(timezone.utc)+timedelta(seconds=max(0,int(data.get("expires_in") or 0)-60))
    with connect() as con:
        con.execute("""INSERT INTO external_oauth_tokens(provider,access_token,refresh_token,token_type,scope,expires_at,updated_at)
          VALUES('canva',%s,%s,%s,%s,%s,now())
          ON CONFLICT(provider) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=COALESCE(excluded.refresh_token,external_oauth_tokens.refresh_token),
            token_type=excluded.token_type,scope=excluded.scope,expires_at=excluded.expires_at,updated_at=now()""",
          (data.get("access_token"),data.get("refresh_token"),data.get("token_type"),data.get("scope"),expires))


def canva_access_token() -> str:
    if not (CANVA_CLIENT_ID and CANVA_CLIENT_SECRET):
        raise HTTPException(503,"Canva client credentials are not configured")
    _init_store()
    with connect() as con:
        row=con.execute("SELECT * FROM external_oauth_tokens WHERE provider='canva'").fetchone()
    if not row:
        raise HTTPException(503,"Canva account is not authorized yet")
    now=datetime.now(timezone.utc)
    if row.get("access_token") and row.get("expires_at") and row["expires_at"]>now:
        return str(row["access_token"])
    refresh=str(row.get("refresh_token") or "")
    if not refresh:
        raise HTTPException(503,"Canva refresh token is unavailable; authorize Canva again")
    with httpx.Client(timeout=30) as client:
        r=client.post("https://api.canva.com/rest/v1/oauth/token",
          data={"grant_type":"refresh_token","refresh_token":refresh},
          headers={"Authorization":_basic_auth(),"Content-Type":"application/x-www-form-urlencoded"})
    if r.status_code>=400:
        raise HTTPException(502,f"Canva token refresh failed: {r.text[:400]}")
    data=r.json()
    _save_tokens(data)  # Canva rotates refresh tokens; persist the replacement atomically.
    return str(data["access_token"])


@app.get("/api/admin/integrations/canva/oauth/start",dependencies=[Depends(require_admin)])
def canva_oauth_start(request: Request):
    if not (CANVA_CLIENT_ID and CANVA_CLIENT_SECRET):
        raise HTTPException(503,"Canva client credentials are not configured")
    verifier=secrets.token_urlsafe(64)[:96]
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state=secrets.token_urlsafe(32)
    response=RedirectResponse("https://www.canva.com/api/oauth/authorize?"+urlencode({
        "code_challenge":challenge,
        "code_challenge_method":"s256",
        "scope":CANVA_SCOPES,
        "response_type":"code",
        "client_id":CANVA_CLIENT_ID,
        "state":state,
        "redirect_uri":_redirect_uri(request),
    }))
    secure=request.url.scheme=="https"
    response.set_cookie("canva_oauth_state",state,max_age=600,httponly=True,secure=secure,samesite="lax")
    response.set_cookie("canva_oauth_verifier",verifier,max_age=600,httponly=True,secure=secure,samesite="lax")
    return response


@app.get("/api/integrations/canva/oauth/callback")
def canva_oauth_callback(request: Request,code: str|None=None,state: str|None=None,error: str|None=None):
    if error:
        raise HTTPException(400,f"Canva authorization failed: {error}")
    expected=request.cookies.get("canva_oauth_state")
    verifier=request.cookies.get("canva_oauth_verifier")
    if not code or not state or not expected or not secrets.compare_digest(state,expected) or not verifier:
        raise HTTPException(400,"Invalid or expired Canva OAuth state")
    with httpx.Client(timeout=30) as client:
        r=client.post("https://api.canva.com/rest/v1/oauth/token",
          data={"grant_type":"authorization_code","code":code,"code_verifier":verifier,"redirect_uri":_redirect_uri(request)},
          headers={"Authorization":_basic_auth(),"Content-Type":"application/x-www-form-urlencoded"})
    if r.status_code>=400:
        raise HTTPException(502,f"Canva token exchange failed: {r.text[:500]}")
    _save_tokens(r.json())
    response=HTMLResponse("""<!doctype html><html lang='ar' dir='rtl'><meta charset='utf-8'><title>Canva connected</title>
    <body style='font-family:sans-serif;max-width:700px;margin:60px auto'><h1>تم ربط Canva بنجاح</h1>
    <p>يمكنك إغلاق هذه الصفحة والعودة إلى Lesson Studio.</p></body></html>""")
    response.delete_cookie("canva_oauth_state")
    response.delete_cookie("canva_oauth_verifier")
    return response


@app.get("/api/admin/integrations/canva/oauth/status",dependencies=[Depends(require_admin)])
def canva_oauth_status(request: Request):
    configured=bool(CANVA_CLIENT_ID and CANVA_CLIENT_SECRET)
    authorized=False
    if os.getenv("DATABASE_URL"):
        _init_store()
        with connect() as con:
            authorized=bool(con.execute("SELECT 1 FROM external_oauth_tokens WHERE provider='canva' AND refresh_token IS NOT NULL").fetchone())
    return {
        "configured":configured,
        "authorized":authorized,
        "redirect_uri":_redirect_uri(request),
        "scopes":CANVA_SCOPES.split(),
        "token_storage":"database_rotating_refresh_token",
        "authorize_url":"/api/admin/integrations/canva/oauth/start",
        "production_redirect_uri":CANVA_PRODUCTION_REDIRECT,
    }
