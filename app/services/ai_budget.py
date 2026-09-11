from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from ..db import connect


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

    Budgets are disabled unless explicitly configured. This keeps development and
    existing production behavior unchanged while allowing a hard ceiling later
    without a code deployment.
    """
    return AIBudgetConfig(
        daily_calls=_positive_int_env("AI_DAILY_CALL_BUDGET"),
        daily_cost_usd=_positive_decimal_env("AI_DAILY_COST_BUDGET_USD"),
        monthly_cost_usd=_positive_decimal_env("AI_MONTHLY_COST_BUDGET_USD"),
    )


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
            "blocks_only_when_explicit_budget_is_reached": True,
            "pricing_required_for_cost_budgets": True,
            "does_not_store_prompts_or_outputs": True,
        },
    }


def enforce_ai_budget(*, provider: str, task: str, model: str | None = None) -> dict:
    """Fail closed only when an explicitly configured budget is exhausted."""
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
