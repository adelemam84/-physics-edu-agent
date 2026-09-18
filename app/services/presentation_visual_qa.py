from __future__ import annotations

from typing import Any

from .lesson_diagram_integrity import diagram_spec_hash
from .science_diagram_specs import SPEC_DOMAINS, SPEC_MODELS, preview_diagram_spec, validate_diagram_spec
from .science_subject_profiles import normalize_subject, subject_profile, visual_domain_allowed


def presentation_visual_preflight(blueprint: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    subject = str(blueprint.get("subject") or "")
    subject_family = normalize_subject(subject)
    profile = subject_profile(subject)

    for slide_index, slide in enumerate(blueprint.get("slides") or [], 1):
        if not isinstance(slide, dict):
            continue
        for visual_index, raw in enumerate(slide.get("visual_specs") or [], 1):
            if not isinstance(raw, dict):
                continue
            visual = dict(raw)
            kind = str(visual.get("kind") or "").strip()
            generated = bool(visual.get("generated"))
            source_refs = [str(x) for x in (visual.get("source_refs") or []) if str(x).strip()]
            strict = kind in SPEC_MODELS
            domain = SPEC_DOMAINS.get(kind, "cross_science")
            issue_codes: list[str] = []
            advisory_codes: list[str] = []
            validation: dict[str, Any] | None = None
            preview: dict[str, Any] | None = None
            spec_hash = ""
            approval_fresh: bool | None = None

            if generated and not source_refs:
                blockers.append("visual_source_grounding")
                issue_codes.append("visual_source_grounding")

            if strict:
                params = visual.get("parameters")
                if not isinstance(params, dict) or not params:
                    blockers.append("visual_parameters_required")
                    issue_codes.append("visual_parameters_required")
                else:
                    validation = validate_diagram_spec(kind, params)
                    if not validation.get("valid"):
                        blockers.append("visual_schema_invalid")
                        issue_codes.append("visual_schema_invalid")
                    else:
                        preview = preview_diagram_spec(kind, str(visual.get("title") or "رسم علمي"), params)
                        if not preview.get("valid") or not preview.get("renderer_called") or not preview.get("svg"):
                            blockers.append("visual_renderer_failed")
                            issue_codes.append("visual_renderer_failed")

                engine = dict(visual.get("diagram_engine") or {})
                spec_hash = diagram_spec_hash({"kind": kind, "parameters": visual.get("parameters") or {}})
                approved_hash = str(engine.get("approved_spec_hash") or "")
                if engine.get("review_required"):
                    blockers.append("visual_teacher_review_required")
                    issue_codes.append("visual_teacher_review_required")
                    approval_fresh = False
                elif engine.get("teacher_reviewed"):
                    approval_fresh = bool(approved_hash and approved_hash == spec_hash)
                    if approved_hash and not approval_fresh:
                        blockers.append("visual_approval_stale")
                        issue_codes.append("visual_approval_stale")
                    elif not approved_hash:
                        warnings.append("visual_approval_hash_missing")
                        advisory_codes.append("visual_approval_hash_missing")
                else:
                    # A strict generated scientific visual cannot silently become
                    # final-export ready just because the renderer succeeded.
                    blockers.append("visual_teacher_review_required")
                    issue_codes.append("visual_teacher_review_required")
                    approval_fresh = False

                if validation and validation.get("valid") and not engine.get("schema_validated"):
                    warnings.append("visual_schema_validation_marker_missing")
                    advisory_codes.append("visual_schema_validation_marker_missing")

                if not visual_domain_allowed(subject, domain):
                    warnings.append("visual_domain_subject_mismatch")
                    advisory_codes.append("visual_domain_subject_mismatch")

            elif generated:
                warnings.append("visual_kind_not_strictly_parameterized")
                advisory_codes.append("visual_kind_not_strictly_parameterized")

            items.append(
                {
                    "slide_index": slide_index,
                    "slide_id": str(slide.get("slide_id") or ""),
                    "visual_index": visual_index,
                    "kind": kind,
                    "domain": domain,
                    "strict_schema": strict,
                    "generated": generated,
                    "source_grounded": bool(source_refs),
                    "schema_valid": None if validation is None else bool(validation.get("valid")),
                    "renderer_ready": None if preview is None else bool(preview.get("valid") and preview.get("renderer_called") and preview.get("svg")),
                    "spec_hash": spec_hash,
                    "approval_fresh": approval_fresh,
                    "blocking_failures": list(dict.fromkeys(issue_codes)),
                    "warnings": list(dict.fromkeys(advisory_codes)),
                }
            )

    strict_total = sum(1 for x in items if x["strict_schema"])
    generated_total = sum(1 for x in items if x["generated"])
    reviewed_total = sum(1 for x in items if x.get("approval_fresh") is True)
    return {
        "ready": not blockers,
        "blocking_failures": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "items": items,
        "visual_total": len(items),
        "generated_visual_total": generated_total,
        "strict_visual_total": strict_total,
        "strict_reviewed_total": reviewed_total,
        "subject_family": subject_family,
        "subject_profile_id": profile.get("id"),
        "allowed_visual_domains": list(profile.get("visual_domains") or []),
        "policy": {
            "source_grounded_only": True,
            "strict_science_visuals_require_schema_validation": True,
            "strict_science_visuals_require_teacher_review": True,
            "approval_is_bound_to_exact_kind_and_parameters": True,
            "no_silent_scientific_correction": True,
            "official_question_bank_write": False,
            "content_ingestion_unchanged": True,
        },
    }
