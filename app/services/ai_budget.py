from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from ..db import connect

FREE_ONLY_ALLOWED_GEMINI_MODELS = {
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
}


def project_free_only() -> bool:
    """Return the project-wide zero-cost policy.

    PROJECT_FREE_ONLY is the canonical flag; AI_FREE_ONLY remains a compatible
    alias used by older deployment/configuration paths. If the two are
    accidentally contradictory, a truthy value wins so paid providers remain
    fail-closed until the operator fixes configuration.
    """
    truthy = {"1", "true", "yes", "on"}
    values = [
        os.getenv("PROJECT_FREE_ONLY", "").strip().lower(),
        os.getenv("AI_FREE_ONLY", "").strip().lower(),
    ]
    configured = [value for value in values if value]
    if not configured:
        return True
    return any(value in truthy for value in configured)


def _enforce_free_only_provider(*, provider: str, task: str, model: str | None) -> None:
    if not project_free_only():
        return
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model or "").strip()
    if normalized_provider == "deterministic":
        return
    if normalized_provider == "gemini" and normalized_model in FREE_ONLY_ALLOWED_GEMINI_MODELS:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "message": "تم حظر مزود أو نموذج قد يسبب تكلفة لأن المشروع يعمل بوضع Free-only.",
            "reason": "project_free_only_policy",
            "provider": provider,
            "task": task,
            "model": model,
            "allowed_gemini_models": sorted(FREE_ONLY_ALLOWED_GEMINI_MODELS),
        },
    )


@dataclass(frozen=True)
class AIBudgetConfig:
    daily_calls: int | None
    daily_cost_usd: Decimal | None
    monthly_cost_usd: Decimal | None


def _positive_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _positive_decimal_env(name: str) -> Decimal | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def budget_config() -> AIBudgetConfig:
    """Read optional operator-managed AI budgets.

    Budgets are disabled unless explicitly configured. This keeps existing behavior
    unchanged while allowing a hard ceiling later without a code deployment.
    """
    return AIBudgetConfig(
        daily_calls=_positive_int_env("AI_DAILY_CALL_BUDGET"),
        daily_cost_usd=_positive_decimal_env("AI_DAILY_COST_BUDGET_USD"),
        monthly_cost_usd=_positive_decimal_env("AI_MONTHLY_COST_BUDGET_USD"),
    )


def _configured(cfg: AIBudgetConfig) -> bool:
    return any((cfg.daily_calls, cfg.daily_cost_usd, cfg.monthly_cost_usd))


def _usage_totals() -> dict:
    with connect() as con:
        row = con.execute(
            """SELECT
                 count(*) FILTER(WHERE created_at >= date_trunc('day', now())) daily_calls,
                 coalesce(sum(estimated_cost_usd) FILTER(
                   WHERE created_at >= date_trunc('day', now())
                 ),0) daily_cost_usd,
                 coalesce(sum(estimated_cost_usd) FILTER(
                   WHERE created_at >= date_trunc('month', now())
                 ),0) monthly_cost_usd
               FROM ai_usage_events"""
        ).fetchone()
    return dict(row or {})


def _ratio(value: Decimal | int, limit: Decimal | int | None) -> float | None:
    if limit is None:
        return None
    try:
        return round(float(Decimal(str(value)) / Decimal(str(limit))), 4)
    except (InvalidOperation, ZeroDivisionError):
        return None


def budget_snapshot() -> dict:
    cfg = budget_config()
    totals = _usage_totals()
    daily_calls = int(totals.get("daily_calls") or 0)
    daily_cost = Decimal(str(totals.get("daily_cost_usd") or 0))
    monthly_cost = Decimal(str(totals.get("monthly_cost_usd") or 0))

    checks = {
        "daily_calls": {
            "used": daily_calls,
            "limit": cfg.daily_calls,
            "ratio": _ratio(daily_calls, cfg.daily_calls),
        },
        "daily_cost_usd": {
            "used": float(daily_cost),
            "limit": float(cfg.daily_cost_usd) if cfg.daily_cost_usd is not None else None,
            "ratio": _ratio(daily_cost, cfg.daily_cost_usd),
        },
        "monthly_cost_usd": {
            "used": float(monthly_cost),
            "limit": float(cfg.monthly_cost_usd) if cfg.monthly_cost_usd is not None else None,
            "ratio": _ratio(monthly_cost, cfg.monthly_cost_usd),
        },
    }

    active = [x for x in checks.values() if x["limit"] is not None]
    exceeded = [x for x in active if x["ratio"] is not None and x["ratio"] >= 1]
    warning = [x for x in active if x["ratio"] is not None and 0.8 <= x["ratio"] < 1]
    level = "blocked" if exceeded else "warning" if warning else "ok" if active else "not_configured"

    return {
        "configured": bool(active),
        "level": level,
        "checks": checks,
        "hard_block_active": bool(exceeded),
        "policy": {
            "project_free_only": project_free_only(),
            "free_only_allowed_gemini_models": sorted(FREE_ONLY_ALLOWED_GEMINI_MODELS),
            "blocks_only_when_explicit_budget_is_reached": True,
            "pricing_required_for_cost_budgets": True,
            "does_not_store_prompts_or_outputs": True,
        },
    }


def enforce_ai_budget(*, provider: str, task: str, model: str | None = None) -> dict:
    """Enforce the zero-cost provider allowlist, then any explicit usage budgets.

    Free-only mode is enabled by default and fails closed for non-allowlisted
    providers/models before any external request can be issued.
    """
    _enforce_free_only_provider(provider=provider, task=task, model=model)
    cfg = budget_config()
    if not _configured(cfg):
        return {
            "configured": False,
            "level": "not_configured",
            "hard_block_active": False,
        }

    snap = budget_snapshot()
    if snap["hard_block_active"]:
        exceeded = [
            key for key, value in snap["checks"].items()
            if value["limit"] is not None and value["ratio"] is not None and value["ratio"] >= 1
        ]
        raise HTTPException(
            status_code=429,
            detail={
                "message": "تم إيقاف استدعاءات الذكاء الاصطناعي مؤقتًا لأن سقف الاستخدام المحدد إداريًا قد تم بلوغه.",
                "reason": "ai_budget_exhausted",
                "exceeded": exceeded,
                "provider": provider,
                "task": task,
                "model": model,
            },
            headers={"Retry-After": "3600"},
        )
    return snap
