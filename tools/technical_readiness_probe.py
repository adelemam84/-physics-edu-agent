from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("TECH_READY_BASE_URL", "https://physics-edu-agent.vercel.app").rstrip("/")
TIMEOUT_SECONDS = max(1.0, min(float(os.getenv("TECH_READY_TIMEOUT_SECONDS", "8")), 30.0))
ATTEMPTS = max(1, min(int(os.getenv("TECH_READY_ATTEMPTS", "2")), 4))
MAX_LATENCY_MS = max(500.0, float(os.getenv("TECH_READY_MAX_LATENCY_MS", "5000")))
OUTPUT = Path(os.getenv("TECH_READY_OUTPUT", "technical-readiness-results.json"))

SECURITY_HEADERS = {
    "strict-transport-security": "max-age=",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "",
    "permissions-policy": "",
    "content-security-policy": "frame-ancestors 'none'",
}

SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "api_key",
    "access_key",
    "database_url",
    "authorization",
)


def _contains_sensitive_key(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _request(path: str) -> dict:
    started = time.perf_counter()
    req = Request(
        BASE_URL + path,
        headers={
            "User-Agent": "physics-edu-agent-technical-readiness/1.0",
            "Accept": "application/json,text/html;q=0.8",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(65536)
            status = int(response.status)
            headers = {str(k).lower(): str(v) for k, v in response.headers.items()}
    except HTTPError as exc:
        status = int(exc.code)
        headers = {str(k).lower(): str(v) for k, v in exc.headers.items()}
        body = exc.read(65536)
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status": 0,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "headers": {},
            "json": None,
            "text": "",
            "transport_error": type(exc).__name__,
        }

    text = body.decode("utf-8", "replace")
    payload = None
    content_type = headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None

    return {
        "status": status,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "headers": headers,
        "json": payload,
        "text": text[:4096],
        "transport_error": "",
    }


def _security_header_violations(headers: dict[str, str]) -> list[str]:
    violations = []
    for name, expected in SECURITY_HEADERS.items():
        actual = headers.get(name, "")
        if not actual:
            violations.append(f"missing security header: {name}")
        elif expected and expected.lower() not in actual.lower():
            violations.append(f"unexpected {name}: {actual}")
    return violations


def _attempt(path: str, validator) -> dict:
    attempts = []
    for index in range(ATTEMPTS):
        row = _request(path)
        violations = list(validator(row))
        if row["elapsed_ms"] > MAX_LATENCY_MS:
            violations.append(
                f"latency {row['elapsed_ms']}ms exceeds {MAX_LATENCY_MS}ms"
            )
        attempts.append(
            {
                "status": row["status"],
                "elapsed_ms": row["elapsed_ms"],
                "transport_error": row["transport_error"],
                "violations": violations,
            }
        )
        if not violations:
            return {"passed": True, "attempts": attempts}
        if index + 1 < ATTEMPTS:
            time.sleep(index + 1)
    return {"passed": False, "attempts": attempts}


def _expect_health(row: dict) -> list[str]:
    out = []
    data = row.get("json")
    if row["status"] != 200:
        out.append(f"expected 200, got {row['status']}")
    if not isinstance(data, dict) or data.get("status") != "ok":
        out.append("health payload is not ok")
    if isinstance(data, dict) and _contains_sensitive_key(data):
        out.append("health payload contains a sensitive key name")
    out.extend(_security_header_violations(row["headers"]))
    return out


def _expect_ready(row: dict) -> list[str]:
    out = []
    data = row.get("json")
    if row["status"] != 200:
        out.append(f"expected 200, got {row['status']}")
    if not isinstance(data, dict) or data.get("status") != "ready":
        out.append("readiness payload is not ready")
    if "no-store" not in row["headers"].get("cache-control", "").lower():
        out.append("readiness response must be no-store")
    if isinstance(data, dict) and _contains_sensitive_key(data):
        out.append("readiness payload contains a sensitive key name")
    out.extend(_security_header_violations(row["headers"]))
    return out


def _expect_research_status(row: dict) -> list[str]:
    out = []
    data = row.get("json")
    if row["status"] != 200:
        out.append(f"expected 200, got {row['status']}")
    if not isinstance(data, dict):
        out.append("research status is not JSON")
        return out
    if not isinstance(data.get("configured"), bool):
        out.append("research configured flag is missing")
    if data.get("source_only") is not True:
        out.append("research engine is not source_only")
    if data.get("auto_publish") is not False:
        out.append("research engine auto_publish must remain false")
    if _contains_sensitive_key(data):
        out.append("research status contains a sensitive key name")
    out.extend(_security_header_violations(row["headers"]))
    return out


def _expect_release_status(row: dict) -> list[str]:
    out = []
    data = row.get("json")
    if row["status"] != 200:
        out.append(f"expected 200, got {row['status']}")
    if not isinstance(data, dict):
        out.append("release status is not JSON")
        return out
    state = str(data.get("release_state") or "")
    if not state.startswith("runtime_ready"):
        out.append(f"unexpected release_state: {state or 'missing'}")
    if data.get("orchestrator_active") is not True:
        out.append("orchestrator is not active")
    if data.get("pdf_only_policy") is not True:
        out.append("pdf_only_policy must remain true")
    if _contains_sensitive_key(data):
        out.append("release status contains a sensitive key name")
    out.extend(_security_header_violations(row["headers"]))
    return out


def _expect_anonymous_admin_denied(row: dict) -> list[str]:
    out = []
    if row["status"] != 401:
        out.append(f"anonymous admin API expected 401, got {row['status']}")
    if "set-cookie" in row["headers"]:
        out.append("anonymous admin denial unexpectedly sets a cookie")
    out.extend(_security_header_violations(row["headers"]))
    return out


def _expect_anonymous_student_session(row: dict) -> list[str]:
    out = []
    data = row.get("json")
    if row["status"] != 200:
        out.append(f"student session status expected 200, got {row['status']}")
    if not isinstance(data, dict) or data.get("authenticated") is not False:
        out.append("anonymous student session must be unauthenticated")
    if "no-store" not in row["headers"].get("cache-control", "").lower():
        out.append("student session response must be no-store")
    if "set-cookie" in row["headers"]:
        out.append("anonymous student session status unexpectedly sets a cookie")
    if isinstance(data, dict) and _contains_sensitive_key(data):
        out.append("student session status contains a sensitive key name")
    out.extend(_security_header_violations(row["headers"]))
    return out


CHECKS = (
    ("/health", _expect_health),
    ("/health/ready", _expect_ready),
    ("/api/research-engine/status", _expect_research_status),
    ("/api/next-release/status", _expect_release_status),
    ("/api/admin/ai-operations/summary", _expect_anonymous_admin_denied),
    ("/api/student/session", _expect_anonymous_student_session),
)


def run() -> dict:
    results = {}
    for path, validator in CHECKS:
        results[path] = _attempt(path, validator)

    passed = all(item["passed"] for item in results.values())
    result = {
        "target": BASE_URL,
        "passed": passed,
        "content_ingestion": "deferred",
        "checks": results,
        "thresholds": {
            "timeout_seconds": TIMEOUT_SECONDS,
            "attempts": ATTEMPTS,
            "max_latency_ms": MAX_LATENCY_MS,
        },
        "checked_at_epoch": int(time.time()),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "# Final Technical Readiness",
            "",
            f"- Target: `{BASE_URL}`",
            f"- Result: **{'PASS ✅' if passed else 'FAIL ❌'}**",
            "- Content ingestion: **deferred**",
            "",
            "| Check | Result | Last status | Last latency |",
            "|---|---|---:|---:|",
        ]
        for path, item in results.items():
            last = item["attempts"][-1]
            lines.append(
                f"| `{path}` | {'PASS ✅' if item['passed'] else 'FAIL ❌'} | "
                f"{last['status']} | {last['elapsed_ms']} ms |"
            )
            if not item["passed"]:
                for violation in last["violations"]:
                    lines.append(f"| ↳ | {violation} |  |  |")
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    return result


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["passed"] else 1)
