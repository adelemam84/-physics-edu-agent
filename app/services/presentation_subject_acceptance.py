from __future__ import annotations

from typing import Any

from .lesson_presentation_blueprint import presentation_preflight, project_edition
from .lesson_presentation_pptx import pptx_preflight, render_presentation_pptx
from .science_subject_profiles import subject_profile


def _stage(stage_id: str, ok: bool, detail: str, *, owner: str = "system") -> dict[str, Any]:
    return {
        "id": stage_id,
        "ok": bool(ok),
        "detail": str(detail),
        "owner": owner,
    }


def presentation_subject_acceptance(
    blueprint: dict[str, Any],
    *,
    render_artifacts: bool = True,
) -> dict[str, Any]:
    """Run a deterministic technical acceptance matrix for one science presentation.

    This validates structure, subject-profile binding, student/teacher projections,
    visual QA, and optional in-memory PPTX rendering. It never persists artifacts,
    approves content, enables ingestion, or writes to the question bank.
    """
    subject = str(blueprint.get("subject") or "")
    expected_profile = subject_profile(subject)
    actual_profile = blueprint.get("subject_profile")
    stages: list[dict[str, Any]] = []

    profile_ok = isinstance(actual_profile, dict) and actual_profile == expected_profile
    stages.append(
        _stage(
            "subject_profile_binding",
            profile_ok,
            f"expected={expected_profile.get('id')} actual={actual_profile.get('id') if isinstance(actual_profile, dict) else 'missing'}",
        )
    )

    policy = dict(blueprint.get("generated_content_policy") or {})
    policy_ok = (
        policy.get("official_question_bank_write") is False
        and policy.get("content_ingestion_unchanged") is True
        and policy.get("source_grounded_only") is True
    )
    stages.append(_stage("safety_policy", policy_ok, "source-grounded / no bank write / ingestion unchanged"))

    base_report = presentation_preflight(blueprint)
    stages.append(
        _stage(
            "base_preflight",
            bool(base_report.get("ready")),
            ",".join(base_report.get("blocking_failures") or []) or "ready",
        )
    )

    visual_qa = dict(base_report.get("visual_qa") or {})
    stages.append(
        _stage(
            "visual_qa",
            bool(visual_qa.get("ready", True)),
            ",".join(visual_qa.get("blocking_failures") or []) or "ready",
        )
    )

    edition_reports: dict[str, Any] = {}
    pptx_reports: dict[str, Any] = {}
    for edition in ("student", "teacher"):
        try:
            projected = project_edition(blueprint, edition)
            report = projected.get("preflight") or presentation_preflight(projected, edition=edition)
            edition_reports[edition] = report
            stages.append(
                _stage(
                    f"{edition}_projection",
                    bool(report.get("ready")),
                    ",".join(report.get("blocking_failures") or []) or "ready",
                )
            )
            if render_artifacts and report.get("ready"):
                data = render_presentation_pptx(blueprint, edition)
                pptx_report = pptx_preflight(data, len(projected.get("slides") or []))
                pptx_reports[edition] = pptx_report
                stages.append(
                    _stage(
                        f"{edition}_pptx",
                        bool(pptx_report.get("ready")),
                        ",".join(pptx_report.get("blocking_failures") or []) or f"{pptx_report.get('slide_count', 0)} slides",
                    )
                )
            elif render_artifacts:
                pptx_reports[edition] = {"ready": False, "blocking_failures": ["projection_not_ready"]}
                stages.append(_stage(f"{edition}_pptx", False, "projection_not_ready"))
        except Exception as exc:
            edition_reports[edition] = {"ready": False, "blocking_failures": ["edition_exception"]}
            stages.append(_stage(f"{edition}_projection", False, f"{type(exc).__name__}: {exc}"))
            if render_artifacts:
                pptx_reports[edition] = {"ready": False, "blocking_failures": ["edition_exception"]}
                stages.append(_stage(f"{edition}_pptx", False, "edition_exception"))

    blockers = [x for x in stages if not x["ok"]]
    return {
        "ready": not blockers,
        "subject": subject,
        "subject_profile": expected_profile,
        "stages": stages,
        "blockers": blockers,
        "base_preflight": base_report,
        "edition_reports": edition_reports,
        "pptx_reports": pptx_reports,
        "summary": {
            "stages_total": len(stages),
            "stages_passed": sum(1 for x in stages if x["ok"]),
            "stages_blocked": len(blockers),
        },
        "policy": {
            "diagnostic_only": True,
            "artifacts_rendered_in_memory_only": True,
            "teacher_approval_not_synthesized": True,
            "official_question_bank_write": False,
            "content_ingestion_unchanged": True,
        },
    }
