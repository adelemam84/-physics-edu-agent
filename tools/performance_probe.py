from __future__ import annotations

import concurrent.futures
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

BASE_URL = os.getenv("PERF_BASE_URL", "https://physics-edu-agent.vercel.app").rstrip("/")
REQUESTS = max(20, min(int(os.getenv("PERF_REQUESTS", "100")), 200))
CONCURRENCY = max(1, min(int(os.getenv("PERF_CONCURRENCY", "10")), 16))
TIMEOUT_SECONDS = max(1.0, min(float(os.getenv("PERF_TIMEOUT_SECONDS", "10")), 30.0))
MAX_ERROR_RATE = max(0.0, min(float(os.getenv("PERF_MAX_ERROR_RATE", "0.01")), 1.0))
P95_LIMIT_MS = max(100.0, float(os.getenv("PERF_P95_LIMIT_MS", "2500")))
MAX_LIMIT_MS = max(P95_LIMIT_MS, float(os.getenv("PERF_MAX_LIMIT_MS", "8000")))
WARMUP_ROUNDS = max(1, min(int(os.getenv("PERF_WARMUP_ROUNDS", "2")), 4))
WARMUP_CONCURRENCY = max(1, min(int(os.getenv("PERF_WARMUP_CONCURRENCY", "10")), 16))

ENDPOINTS = (
    "/health",
    "/health/ready",
    "/api/research-engine/status",
    "/api/next-release/status",
)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def fetch(path: str) -> dict:
    started = time.perf_counter()
    status = 0
    error = ""
    try:
        req = urllib.request.Request(
            BASE_URL + path,
            method="GET",
            headers={
                "User-Agent": "physics-edu-agent-performance-readiness/1.0",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            status = int(response.status)
            response.read(2048)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        error = f"HTTPError:{exc.code}"
    except Exception as exc:
        error = exc.__class__.__name__
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "path": path,
        "status": status,
        "ok": status == 200 and not error,
        "elapsed_ms": elapsed_ms,
        "error": error,
    }


def summarize(rows: list[dict]) -> dict:
    by_path: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_path[row["path"]].append(row)

    endpoint_results = {}
    for path, items in by_path.items():
        latencies = [float(x["elapsed_ms"]) for x in items]
        failures = [x for x in items if not x["ok"]]
        endpoint_results[path] = {
            "requests": len(items),
            "successes": len(items) - len(failures),
            "failures": len(failures),
            "error_rate": round(len(failures) / max(1, len(items)), 4),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "p50": round(percentile(latencies, 0.50), 2),
                "p95": round(percentile(latencies, 0.95), 2),
                "p99": round(percentile(latencies, 0.99), 2),
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
            "status_codes": {
                str(code): sum(1 for x in items if x["status"] == code)
                for code in sorted({x["status"] for x in items})
            },
            "errors": sorted({x["error"] for x in failures if x["error"]}),
        }

    all_latencies = [float(x["elapsed_ms"]) for x in rows]
    failures = [x for x in rows if not x["ok"]]
    return {
        "target": BASE_URL,
        "request_count": len(rows),
        "concurrency": CONCURRENCY,
        "timeout_seconds": TIMEOUT_SECONDS,
        "successes": len(rows) - len(failures),
        "failures": len(failures),
        "error_rate": round(len(failures) / max(1, len(rows)), 4),
        "latency_ms": {
            "mean": round(statistics.fmean(all_latencies), 2) if all_latencies else 0.0,
            "p50": round(percentile(all_latencies, 0.50), 2),
            "p95": round(percentile(all_latencies, 0.95), 2),
            "p99": round(percentile(all_latencies, 0.99), 2),
            "max": round(max(all_latencies), 2) if all_latencies else 0.0,
        },
        "endpoints": endpoint_results,
    }


def main() -> int:
    # First-hit baseline is kept separate from the load sample.
    first_hits = {path: fetch(path) for path in ENDPOINTS}

    # Preserve cold-start evidence, then warm enough serverless capacity for a
    # steady-state sample. Warm-up is bounded, read-only, and recorded separately.
    warmup_schedule = [
        ENDPOINTS[i % len(ENDPOINTS)]
        for i in range(WARMUP_ROUNDS * WARMUP_CONCURRENCY)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=WARMUP_CONCURRENCY) as pool:
        warmup_rows = list(pool.map(fetch, warmup_schedule))
    warmup_summary = summarize(warmup_rows)

    schedule = [ENDPOINTS[i % len(ENDPOINTS)] for i in range(REQUESTS)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        rows = list(pool.map(fetch, schedule))
    wall_seconds = round(time.perf_counter() - started, 3)

    result = summarize(rows)
    result["first_hit"] = first_hits
    result["warmup"] = {
        "rounds": WARMUP_ROUNDS,
        "concurrency": WARMUP_CONCURRENCY,
        "request_count": len(warmup_rows),
        "summary": warmup_summary,
    }
    result["wall_seconds"] = wall_seconds
    result["throughput_rps"] = round(len(rows) / max(wall_seconds, 0.001), 2)
    result["thresholds"] = {
        "max_error_rate": MAX_ERROR_RATE,
        "p95_limit_ms": P95_LIMIT_MS,
        "max_limit_ms": MAX_LIMIT_MS,
    }

    violations: list[str] = []
    if result["error_rate"] > MAX_ERROR_RATE:
        violations.append(
            f"overall error rate {result['error_rate']:.2%} > {MAX_ERROR_RATE:.2%}"
        )
    if result["latency_ms"]["p95"] > P95_LIMIT_MS:
        violations.append(
            f"overall p95 {result['latency_ms']['p95']}ms > {P95_LIMIT_MS}ms"
        )
    if result["latency_ms"]["max"] > MAX_LIMIT_MS:
        violations.append(
            f"overall max {result['latency_ms']['max']}ms > {MAX_LIMIT_MS}ms"
        )

    for path, stats in result["endpoints"].items():
        if stats["error_rate"] > MAX_ERROR_RATE:
            violations.append(
                f"{path} error rate {stats['error_rate']:.2%} > {MAX_ERROR_RATE:.2%}"
            )
        if stats["latency_ms"]["p95"] > P95_LIMIT_MS:
            violations.append(
                f"{path} p95 {stats['latency_ms']['p95']}ms > {P95_LIMIT_MS}ms"
            )

    result["violations"] = violations
    result["passed"] = not violations

    with open("performance-results.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "# Production Performance Readiness",
            "",
            f"- Target: `{BASE_URL}`",
            f"- Requests: **{result['request_count']}**",
            f"- Concurrency: **{CONCURRENCY}**",
            f"- Warm-up: **{WARMUP_ROUNDS} rounds × {WARMUP_CONCURRENCY} concurrency**",
            f"- Success: **{result['successes']} / {result['request_count']}**",
            f"- Throughput: **{result['throughput_rps']} req/s**",
            f"- Overall p50 / p95 / p99: **{result['latency_ms']['p50']} / {result['latency_ms']['p95']} / {result['latency_ms']['p99']} ms**",
            "",
            "| Endpoint | Success | p50 | p95 | max |",
            "|---|---:|---:|---:|---:|",
        ]
        for path, stats in result["endpoints"].items():
            lines.append(
                f"| `{path}` | {stats['successes']}/{stats['requests']} | "
                f"{stats['latency_ms']['p50']} ms | {stats['latency_ms']['p95']} ms | "
                f"{stats['latency_ms']['max']} ms |"
            )
        lines += ["", f"**Result:** {'PASS ✅' if result['passed'] else 'FAIL ❌'}"]
        if violations:
            lines += ["", "## Violations"] + [f"- {x}" for x in violations]
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
