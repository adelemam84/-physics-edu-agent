from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os

from fastapi import HTTPException, Request

from ..db import connect


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def policy(name: str, *, default_limit: int, default_window_seconds: int) -> tuple[int, int]:
    prefix = "RATE_LIMIT_" + name.upper()
    return (
        _positive_int(prefix + "_MAX", default_limit),
        _positive_int(prefix + "_WINDOW_SECONDS", default_window_seconds),
    )


def _subject_hash_key() -> bytes:
    # Keep rate-limit subjects opaque even if the limiter table is exposed.
    # RATE_LIMIT_HASH_SECRET is optional; stable application secrets already
    # required by production readiness provide a safe deployment-wide fallback.
    for name in (
        "RATE_LIMIT_HASH_SECRET",
        "STUDENT_SESSION_SECRET",
        "ADMIN_SESSION_SECRET",
        "ADMIN_API_KEY",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return hashlib.sha256(("science-rate-limit:" + value).encode("utf-8")).digest()
    return hashlib.sha256(b"science-rate-limit:development-only").digest()


def subject_hash(scope: str, subject: str) -> str:
    value = f"{scope}:{subject}".encode("utf-8", "ignore")
    return hmac.new(_subject_hash_key(), value, hashlib.sha256).hexdigest()


def _normalized_ip(value: str | None) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _trusted_proxy_headers() -> bool:
    # Vercel owns/overwrites the forwarding chain at the public edge. Other
    # runtimes must opt in only when their reverse proxy also overwrites
    # X-Forwarded-For rather than passing arbitrary client input through.
    return bool(os.getenv("VERCEL")) or os.getenv("VERCEL_ENV", "").strip().lower() in {
        "production",
        "preview",
    } or _truthy_env("TRUST_PROXY_HEADERS")


def request_subject(request: Request) -> str:
    if _trusted_proxy_headers():
        forwarded = (
            request.headers.get("x-forwarded-for") or ""
        ).split(",", 1)[0].strip()
        ip = _normalized_ip(forwarded)
        if ip:
            return "ip:" + ip

    if request.client and request.client.host:
        ip = _normalized_ip(request.client.host)
        if ip:
            return "ip:" + ip
    return "ip:unknown"


def enforce_rate_limit(
    *,
    scope: str,
    subject: str,
    limit: int,
    window_seconds: int,
) -> dict:
    limit = max(1, int(limit))
    window_seconds = max(1, int(window_seconds))
    digest = subject_hash(scope, subject)
    with connect() as con:
        row = con.execute(
            """INSERT INTO request_rate_limits(scope,subject_hash,window_start,hits,updated_at)
               VALUES(%s,%s,now(),1,now())
               ON CONFLICT(scope,subject_hash) DO UPDATE SET
                 hits=CASE
                   WHEN request_rate_limits.window_start <= now() - (%s * interval '1 second')
                     THEN 1
                   ELSE request_rate_limits.hits + 1
                 END,
                 window_start=CASE
                   WHEN request_rate_limits.window_start <= now() - (%s * interval '1 second')
                     THEN now()
                   ELSE request_rate_limits.window_start
                 END,
                 updated_at=now()
               RETURNING hits,
                 greatest(1,ceil(extract(epoch FROM (
                   window_start + (%s * interval '1 second') - now()
                 ))))::integer retry_after""",
            (scope, digest, window_seconds, window_seconds, window_seconds),
        ).fetchone()
    hits = int(row["hits"])
    retry_after = max(1, int(row["retry_after"]))
    if hits > limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "تم تجاوز الحد المؤقت لهذه العملية. حاول لاحقًا.",
                "scope": scope,
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    return {
        "scope": scope,
        "limit": limit,
        "window_seconds": window_seconds,
        "hits": hits,
        "remaining": max(0, limit - hits),
        "retry_after": retry_after,
    }


def enforce_request_policy(
    request: Request,
    *,
    name: str,
    default_limit: int,
    default_window_seconds: int,
) -> dict:
    limit, window = policy(
        name,
        default_limit=default_limit,
        default_window_seconds=default_window_seconds,
    )
    return enforce_rate_limit(
        scope=name,
        subject=request_subject(request),
        limit=limit,
        window_seconds=window,
    )


def enforce_subject_policy(
    subject: str,
    *,
    name: str,
    default_limit: int,
    default_window_seconds: int,
) -> dict:
    limit, window = policy(
        name,
        default_limit=default_limit,
        default_window_seconds=default_window_seconds,
    )
    return enforce_rate_limit(
        scope=name,
        subject=subject,
        limit=limit,
        window_seconds=window,
    )
