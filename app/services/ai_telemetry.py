from __future__ import annotations

import json
import os
from typing import Any

from ..db import connect


def _int_value(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def normalize_usage(provider: str, usage: dict | None) -> dict[str, int]:
    """Normalize provider usage metadata without retaining prompts or output text."""
    raw = dict(usage or {})
    input_tokens = _int_value(
        raw,
        "input_tokens",
        "prompt_tokens",
        "promptTokenCount",
        "inputTokenCount",
    )
    output_tokens = _int_value(
        raw,
        "output_tokens",
        "completion_tokens",
        "candidatesTokenCount",
        "outputTokenCount",
    )
    total_tokens = _int_value(
        raw,
        "total_tokens",
        "totalTokenCount",
    )
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _pricing() -> dict:
    """Optional operator-managed pricing; never hard-code model prices in application code."""
    raw = os.getenv("AI_MODEL_PRICING_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def estimate_cost_usd(model: str | None, *, input_tokens: int, output_tokens: int) -> float | None:
    if not model:
        return None
    item = _pricing().get(model)
    if not isinstance(item, dict):
        return None
    try:
        input_rate = float(item.get("input_per_million") or 0)
        output_rate = float(item.get("output_per_million") or 0)
    except (TypeError, ValueError):
        return None
    if input_rate < 0 or output_rate < 0:
        return None
    return round(
        (input_tokens / 1_000_000.0) * input_rate
        + (output_tokens / 1_000_000.0) * output_rate,
        8,
    )


def record_ai_usage(
    *,
    provider: str,
    task: str,
    model: str | None,
    status: str,
    latency_ms: int | None = None,
    usage: dict | None = None,
    error_code: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Best-effort, content-free AI telemetry. Telemetry failure never breaks user work."""
    normalized = normalize_usage(provider, usage)
    cost = estimate_cost_usd(
        model,
        input_tokens=normalized["input_tokens"],
        output_tokens=normalized["output_tokens"],
    )
    safe_metadata = dict(metadata or {})
    # Explicitly reject likely content-bearing keys.
    for key in list(safe_metadata):
        if key.lower() in {
            "prompt",
            "text",
            "transcript",
            "content",
            "answer",
            "question_text",
            "output",
            "response",
        }:
            safe_metadata.pop(key, None)
    try:
        with connect() as con:
            con.execute(
                """INSERT INTO ai_usage_events(
                     provider,task,model,status,latency_ms,
                     input_tokens,output_tokens,total_tokens,estimated_cost_usd,
                     usage_json,metadata_json,error_code
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)""",
                (
                    str(provider)[:80],
                    str(task)[:120],
                    str(model)[:160] if model else None,
                    str(status)[:32],
                    max(0, int(latency_ms)) if latency_ms is not None else None,
                    normalized["input_tokens"],
                    normalized["output_tokens"],
                    normalized["total_tokens"],
                    cost,
                    json.dumps(usage or {}, ensure_ascii=False, default=str),
                    json.dumps(safe_metadata, ensure_ascii=False, default=str),
                    str(error_code)[:160] if error_code else None,
                ),
            )
        return True
    except Exception:
        return False


def usage_snapshot(hours: int = 24) -> dict:
    """Return aggregate, privacy-preserving AI usage for the admin operations page."""
    hours = min(max(int(hours), 1), 24 * 31)
    with connect() as con:
        summary = con.execute(
            """SELECT
                 count(*) total_calls,
                 count(*) FILTER(WHERE status='success') success_calls,
                 count(*) FILTER(WHERE status<>'success') failed_calls,
                 coalesce(sum(input_tokens),0) input_tokens,
                 coalesce(sum(output_tokens),0) output_tokens,
                 coalesce(sum(total_tokens),0) total_tokens,
                 coalesce(sum(estimated_cost_usd),0) estimated_cost_usd,
                 round(avg(latency_ms) FILTER(WHERE latency_ms IS NOT NULL)) avg_latency_ms
               FROM ai_usage_events
               WHERE created_at >= now() - (%s * interval '1 hour')""",
            (hours,),
        ).fetchone()
        groups = list(
            con.execute(
                """SELECT provider,task,model,
                     count(*) calls,
                     count(*) FILTER(WHERE status='success') success_calls,
                     count(*) FILTER(WHERE status<>'success') failed_calls,
                     coalesce(sum(input_tokens),0) input_tokens,
                     coalesce(sum(output_tokens),0) output_tokens,
                     coalesce(sum(total_tokens),0) total_tokens,
                     coalesce(sum(estimated_cost_usd),0) estimated_cost_usd,
                     round(avg(latency_ms) FILTER(WHERE latency_ms IS NOT NULL)) avg_latency_ms
                   FROM ai_usage_events
                   WHERE created_at >= now() - (%s * interval '1 hour')
                   GROUP BY provider,task,model
                   ORDER BY calls DESC,provider,task""",
                (hours,),
            ).fetchall()
        )
        failures = list(
            con.execute(
                """SELECT provider,task,model,error_code,created_at
                   FROM ai_usage_events
                   WHERE created_at >= now() - (%s * interval '1 hour')
                     AND status<>'success'
                   ORDER BY created_at DESC
                   LIMIT 20""",
                (hours,),
            ).fetchall()
        )
    return {
        "window_hours": hours,
        "summary": dict(summary or {}),
        "groups": [dict(x) for x in groups],
        "recent_failures": [dict(x) for x in failures],
        "pricing_configured": bool(_pricing()),
        "privacy": {
            "stores_prompts": False,
            "stores_outputs": False,
            "stores_student_answers": False,
            "stores_source_text": False,
        },
    }
