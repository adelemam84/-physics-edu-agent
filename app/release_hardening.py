from __future__ import annotations

import os
import threading
import time

from fastapi import Depends

from .db import connect
from .exam_blueprint import blueprint_readiness
from .file_search_store import configured_store_name
from .main import app
from .research_engine import research_engine_status
from .security import require_admin
from .services.active_content_integrity import active_content_integrity_snapshot

NEXT_RELEASE = app.version
PUBLIC_STATUS_TTL_SECONDS = max(
    1.0,
    min(float(os.getenv("NEXT_RELEASE_PUBLIC_CACHE_SECONDS", "5")), 30.0),
)
_public_status_lock = threading.Lock()
_public_status_cache: tuple[float, dict] | None = None


def _sync_summary() -> dict:
    try:
        with connect() as con:
            exists = con.execute(
                "SELECT to_regclass('public.gemini_source_sync') name"
            ).fetchone()["name"]
            if not exists:
                return {"total": 0, "active": 0, "processing": 0, "failed": 0}
            row = con.execute(
                """SELECT count(*) total,
                  count(*) FILTER(WHERE state='active') active,
                  count(*) FILTER(WHERE state='processing') processing,
                  count(*) FILTER(WHERE state='failed') failed
                  FROM gemini_source_sync"""
            ).fetchone()
        return {
            k: int(row[k] or 0)
            for k in ("total", "active", "processing", "failed")
        }
    except Exception:
        return {"total": 0, "active": 0, "processing": 0, "failed": 0}


def _classify_release_state(
    runtime_blockers: list[str],
    content_gates: list[str],
) -> str:
    if runtime_blockers:
        return "code_ready_pending_runtime_activation"
    if content_gates:
        return "runtime_ready_content_gate_open"
    return "runtime_ready"


def next_release_status() -> dict:
    """Return release state without turning deferred AI/content capabilities into runtime blockers.

    Gemini and File Search are valuable source-processing capabilities, but source ingestion is
    intentionally independent from technical runtime handoff. Their absence is therefore reported
    as an optional capability warning rather than as a runtime activation failure.
    """
    research = research_engine_status()
    blueprint = blueprint_readiness()
    from .source_review import _source_page_coverage_snapshot

    source_coverage = _source_page_coverage_snapshot()["summary"]
    content_integrity = active_content_integrity_snapshot()
    sync = _sync_summary()

    checks = {
        "database_configured": True,
        "pdf_only_policy": True,
        "gemini_api_key_configured": bool(research.get("configured")),
        "file_search_store_configured": bool(configured_store_name()),
        "orchestrator_active": (
            research.get("orchestrator", {}).get("status") == "active"
        ),
        "question_bank_auto_write_disabled": (
            research.get("guardrails", {}).get("question_bank_auto_write") is False
        ),
        "exam_blueprint_23_23_active": (
            blueprint.get("blueprint", {}).get("objective_questions") == 23
            and blueprint.get("blueprint", {}).get("essay_questions") == 23
        ),
        "source_page_coverage_ready": bool(
            source_coverage.get("coverage_ready")
        ),
        "active_content_integrity_ready": bool(content_integrity.get("ready")),
    }

    # Runtime blockers are reserved for genuine platform/safety failures.
    # Optional AI/source-processing integrations are reported separately below.
    runtime_blockers: list[str] = []
    if not checks["question_bank_auto_write_disabled"]:
        runtime_blockers.append(
            "AI question-bank auto-write guard is not enforced"
        )

    optional_capabilities = {
        "gemini_source_engine": checks["gemini_api_key_configured"],
        "gemini_file_search": checks["file_search_store_configured"],
    }
    optional_warnings: list[str] = []
    if not optional_capabilities["gemini_source_engine"]:
        optional_warnings.append(
            "Gemini source tools are not configured; deterministic/runtime paths remain available"
        )
    if not optional_capabilities["gemini_file_search"]:
        optional_warnings.append(
            "Gemini File Search is not configured; deferred source ingestion does not block runtime readiness"
        )

    content_gates: list[str] = []
    if not checks["source_page_coverage_ready"]:
        content_gates.append(
            "source page coverage gap: "
            f"open_zero={source_coverage.get('open_zero_question_pages', 0)}, "
            f"count_mismatch={source_coverage.get('count_mismatch_pages', 0)}"
        )
    if not checks["active_content_integrity_ready"]:
        content_gates.append(
            "active curriculum integrity gap: "
            f"invalid_approved={content_integrity.get('invalid_approved_questions', 0)}, "
            f"question_lesson_mismatch={content_integrity.get('question_lesson_mismatches', 0)}, "
            f"quiz_question_mismatch={content_integrity.get('quiz_question_mismatches', 0)}, "
            f"critical_qa={content_integrity.get('critical_open_qa', 0)}"
        )
    if not blueprint.get("active_shape_feasible", False):
        gaps = blueprint.get("gaps", {})
        content_gates.append(
            "23+23 exam bank gap: "
            f"objective={gaps.get('objective', 0)}, essay={gaps.get('essay', 0)}"
        )

    return {
        "version": NEXT_RELEASE,
        "release_state": _classify_release_state(
            runtime_blockers,
            content_gates,
        ),
        "checks": checks,
        "runtime_blockers": runtime_blockers,
        "optional_capabilities": optional_capabilities,
        "optional_warnings": optional_warnings,
        "content_gates": content_gates,
        "blockers": runtime_blockers + content_gates,
        "gemini_source_sync": sync,
        "source_page_coverage": source_coverage,
        "active_content_integrity": content_integrity,
        "exam_blueprint": {
            "total_questions": 46,
            "objective_questions": 23,
            "essay_questions": 23,
            "feasible": bool(blueprint.get("active_shape_feasible")),
            "gaps": blueprint.get("gaps", {}),
        },
        "policy": {
            "technical_runtime_independent_of_deferred_content_ingestion": True,
            "optional_ai_capabilities_do_not_block_runtime": True,
            "question_bank_auto_write_must_remain_disabled": True,
        },
        "deployment_policy": (
            "promote only a main commit after deterministic regression gates and "
            "production smoke checks pass, via GitHub Actions or the manual controlled release path"
        ),
    }


def _public_status_projection(data: dict) -> dict:
    return {
        "version": data["version"],
        "release_state": data["release_state"],
        "orchestrator_active": data["checks"]["orchestrator_active"],
        "pdf_only_policy": True,
        "source_page_coverage": data["source_page_coverage"],
        "exam_blueprint": data["exam_blueprint"],
    }


def _public_next_release_snapshot() -> dict:
    """Coalesce bursty public status reads without caching admin diagnostics."""
    global _public_status_cache

    now = time.monotonic()
    cached = _public_status_cache
    if cached is not None and now - cached[0] < PUBLIC_STATUS_TTL_SECONDS:
        return cached[1]

    with _public_status_lock:
        now = time.monotonic()
        cached = _public_status_cache
        if cached is not None and now - cached[0] < PUBLIC_STATUS_TTL_SECONDS:
            return cached[1]

        value = _public_status_projection(next_release_status())
        _public_status_cache = (now, value)
        return value


@app.get("/api/next-release/status")
def public_next_release_status():
    return _public_next_release_snapshot()


@app.get(
    "/api/admin/next-release/status",
    dependencies=[Depends(require_admin)],
)
def admin_next_release_status():
    return next_release_status()
