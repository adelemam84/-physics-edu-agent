from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .db import connect
from .main import app

VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()


def _verify_signature(raw: bytes, header: str | None) -> bool:
    if not APP_SECRET:
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.split("=",1)[1], expected)


def _provider_ts(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except Exception:
        return None


@app.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if not VERIFY_TOKEN:
        raise HTTPException(503, "WHATSAPP_WEBHOOK_VERIFY_TOKEN is not configured")
    if hub_mode == "subscribe" and hub_verify_token and hmac.compare_digest(hub_verify_token, VERIFY_TOKEN):
        return hub_challenge or ""
    raise HTTPException(403, "Webhook verification failed")


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    raw = await request.body()
    if not APP_SECRET:
        raise HTTPException(503, "META_APP_SECRET is not configured")
    if not _verify_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    updates = []
    entries = payload.get("entry") or []
    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for status in value.get("statuses") or []:
                mid = str(status.get("id") or "").strip()
                state = str(status.get("status") or "").strip().lower()
                if not mid or state not in {"sent","delivered","read","failed"}:
                    continue
                ts = _provider_ts(status.get("timestamp"))
                errors = status.get("errors") or []
                err = errors[0] if errors else {}
                code = str(err.get("code") or "")[:120] or None
                title = str(err.get("title") or err.get("message") or "")[:500] or None

                with connect() as con:
                    row = con.execute(
                        "SELECT id,delivery_status FROM parent_notifications WHERE provider_message_id=%s LIMIT 1",
                        (mid,),
                    ).fetchone()
                    if not row:
                        updates.append({"provider_message_id":mid,"status":state,"matched":False})
                        continue

                    current = (row["delivery_status"] or "").lower()
                    rank = {"":0,"sent":1,"delivered":2,"read":3,"failed":4}
                    allow = state == "failed" or rank.get(state,0) >= rank.get(current,0)
                    if not allow:
                        updates.append({"id":row["id"],"status":current,"ignored_regression":state})
                        continue

                    con.execute(
                        """UPDATE parent_notifications SET
                             delivery_status=%s,
                             provider_status_at=COALESCE(%s,now()),
                             delivered_at=CASE WHEN %s IN ('delivered','read') THEN COALESCE(delivered_at,COALESCE(%s,now())) ELSE delivered_at END,
                             read_at=CASE WHEN %s='read' THEN COALESCE(read_at,COALESCE(%s,now())) ELSE read_at END,
                             provider_error_code=%s,
                             provider_error_title=%s,
                             error_message=CASE WHEN %s='failed' THEN COALESCE(%s,error_message) ELSE error_message END
                           WHERE id=%s""",
                        (state,ts,state,ts,state,ts,code,title,state,title,row["id"]),
                    )
                updates.append({"id":row["id"],"status":state,"matched":True})

    return {"ok":True,"updates":updates}
