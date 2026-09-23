from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("SMOKE_BASE_URL", "https://physics-edu-agent.vercel.app").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "8"))
ATTEMPTS = max(1, int(os.getenv("SMOKE_ATTEMPTS", "3")))
OUTPUT = Path(os.getenv("SMOKE_OUTPUT", "production-smoke-results.json"))
EXPECT_VERSION = os.getenv("SMOKE_EXPECT_VERSION", "").strip()


def _health_ok(data: dict) -> bool:
    return (
        data.get("status") == "ok"
        and (not EXPECT_VERSION or str(data.get("version") or "") == EXPECT_VERSION)
    )


def _ready_ok(data: dict) -> bool:
    return (
        data.get("status") == "ready"
        and data.get("content_ingestion") == "locked"
        and (not EXPECT_VERSION or str(data.get("version") or "") == EXPECT_VERSION)
    )


def _html_has(*tokens: str):
    def validate(body: str) -> bool:
        return isinstance(body, str) and all(token in body for token in tokens)

    return validate


CHECKS = (
    ("/health", "json", _health_ok),
    ("/health/ready", "json", _ready_ok),
    ("/api/research-engine/status", "json", lambda data: isinstance(data.get("configured"), bool)),
    ("/api/next-release/status", "json", lambda data: isinstance(data, dict) and bool(data)),
    (
        "/api/student/session",
        "json",
        lambda data: isinstance(data, dict) and data.get("authenticated") is False,
    ),
    (
        "/api/admin/feature-status",
        "status",
        lambda status: status == 401,
    ),
    (
        "/api/student/exams/resolve/SMOKE-LEGACY-CODE",
        "status",
        lambda status: status == 410,
    ),
    (
        "/student",
        "text",
        _html_has(
            "id=studentLoginForm",
            'onsubmit="loginPortal(event)"',
            "/api/student/session",
        ),
    ),
    (
        "/admin/dashboard",
        "text",
        _html_has(
            "دخول الإدارة",
            "HttpOnly",
            "/api/admin/login",
        ),
    ),
    (
        "/student/quiz/1",
        "text",
        _html_has(
            'role="progressbar"',
            "flushPendingSaves",
            "submitInFlight",
            "/api/student/session",
        ),
    ),
    (
        "/student/results/1",
        "text",
        _html_has(
            "table-wrap",
            "/api/student/session",
            "weakBtn.disabled=true",
        ),
    ),
    (
        "/student/study-queue",
        "text",
        _html_has(
            "statusLabels=",
            "taskMsg",
            "/api/student/session",
        ),
    ),
    (
        "/student/command-center",
        "text",
        _html_has(
            "const msg=document.getElementById('msg')",
            "/api/student/session",
        ),
    ),
)


def _request(path: str, mode: str) -> dict:
    started = time.perf_counter()
    req = Request(
        BASE_URL + path,
        headers={"User-Agent": "physics-edu-agent-production-smoke/1.0"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            status = int(response.status)
        text = body.decode("utf-8")
        payload = (
            json.loads(text)
            if mode == "json"
            else status
            if mode == "status"
            else text
        )
        return {
            "ok": 200 <= status < 300 or mode == "status",
            "status": status,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "payload": payload,
            "error": "",
        }
    except HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        payload = status if mode == "status" else None
        return {
            "ok": mode == "status",
            "status": status,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "payload": payload,
            "error": "" if mode == "status" else type(exc).__name__,
        }
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        status = int(getattr(exc, "code", 0) or 0)
        return {
            "ok": False,
            "status": status,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "payload": None,
            "error": type(exc).__name__,
        }


def run() -> dict:
    results: dict[str, dict] = {}
    overall = True

    for path, mode, validator in CHECKS:
        attempts: list[dict] = []
        passed = False
        for index in range(ATTEMPTS):
            result = _request(path, mode)
            attempts.append({
                key: value for key, value in result.items() if key != "payload"
            })
            payload = result.get("payload")
            if result["ok"] and validator(payload):
                passed = True
                break
            if index + 1 < ATTEMPTS:
                time.sleep(index + 1)

        last = attempts[-1]
        results[path] = {
            "passed": passed,
            "mode": mode,
            "attempts": attempts,
            "final_status": last["status"],
            "final_elapsed_ms": last["elapsed_ms"],
            "final_error": last["error"],
        }
        overall = overall and passed

    summary = {
        "target": BASE_URL,
        "passed": overall,
        "expected_version": EXPECT_VERSION or None,
        "content_ingestion_expected": "locked",
        "student_session_expected": "anonymous_false",
        "admin_api_anonymous_expected": 401,
        "legacy_exam_code_get_expected": 410,
        "student_shell_contracts": "read_only",
        "checks": results,
        "checked_at_epoch": int(time.time()),
    }
    OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
