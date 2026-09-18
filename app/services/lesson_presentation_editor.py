from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .lesson_presentation_blueprint import presentation_preflight


_IMMUTABLE_TOP_LEVEL = (
    "deck_id",
    "source_lesson_pack_id",
    "subject",
    "grade_label",
    "request",
    "objectives",
    "feature_capabilities",
    "generated_content_policy",
)

_IMMUTABLE_BLOCK_FIELDS = (
    "kind",
    "source_refs",
    "teacher_only",
    "question_id",
    "official_question_bank",
    "question_bank_eligible",
    "generated",
    "objective_id",
)
_EDITABLE_BLOCK_FIELDS = {"text", "notes"}

_IMMUTABLE_VISUAL_FIELDS = (
    "kind",
    "source_refs",
    "object_key",
    "approved",
    "generated",
    "label",
    "scientific_labels",
    "parameters",
    "routing",
    "diagram_engine",
)
_EDITABLE_VISUAL_FIELDS = {"title", "description", "nodes", "steps", "items", "labels"}
_EDITABLE_SLIDE_FIELDS = {
    "slide_id",
    "order",
    "kind",
    "title",
    "content_blocks",
    "source_refs",
    "objective_ids",
    "visual_specs",
    "table_specs",
    "speaker_notes",
    "hidden",
    "translation_required",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def presentation_editor_base_hash(blueprint: dict) -> str:
    base = copy.deepcopy(blueprint)
    base.pop("preflight", None)
    base.pop("approval_state", None)
    return hashlib.sha256(_canonical(base).encode("utf-8")).hexdigest()


def presentation_edit_digest(base_hash: str, edited_blueprint: dict) -> str:
    edited = copy.deepcopy(edited_blueprint)
    edited.pop("preflight", None)
    edited.pop("approval_state", None)
    raw = base_hash + "|" + _canonical(edited)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _same(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def validate_presentation_edits(
    base_blueprint: dict,
    edited_blueprint: dict,
    *,
    supplied_base_hash: str | None = None,
) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    base_hash = presentation_editor_base_hash(base_blueprint)

    if not supplied_base_hash:
        blockers.append("editor_base_hash_required")
    elif supplied_base_hash != base_hash:
        blockers.append("stale_editor_base")

    if not isinstance(edited_blueprint, dict):
        return {
            "ready": False,
            "blocking_failures": ["edited_blueprint_required"],
            "warnings": [],
            "base_hash": base_hash,
            "edit_digest": "",
            "changed": False,
            "teacher_reapproval_required": False,
            "prepared_blueprint": None,
        }

    for key in _IMMUTABLE_TOP_LEVEL:
        if not _same(base_blueprint.get(key), edited_blueprint.get(key)):
            blockers.append(f"immutable_{key}")

    base_slides = [x for x in (base_blueprint.get("slides") or []) if isinstance(x, dict)]
    edited_slides = [x for x in (edited_blueprint.get("slides") or []) if isinstance(x, dict)]
    base_by_id = {str(x.get("slide_id") or ""): x for x in base_slides}
    edited_ids = [str(x.get("slide_id") or "") for x in edited_slides]

    if len(edited_ids) != len(set(edited_ids)) or any(not x for x in edited_ids):
        blockers.append("unique_slide_ids")
    if set(edited_ids) != set(base_by_id):
        blockers.append("slide_identity_set_changed")

    for slide in edited_slides:
        sid = str(slide.get("slide_id") or "")
        original = base_by_id.get(sid)
        if not original:
            continue
        for key in slide:
            if key not in _EDITABLE_SLIDE_FIELDS and not _same(original.get(key), slide.get(key)):
                blockers.append(f"unsupported_slide_edit_{key}")
        for key in ("kind", "source_refs", "objective_ids", "translation_required"):
            if not _same(original.get(key), slide.get(key)):
                blockers.append(f"immutable_slide_{key}")

        base_blocks = [x for x in (original.get("content_blocks") or []) if isinstance(x, dict)]
        new_blocks = [x for x in (slide.get("content_blocks") or []) if isinstance(x, dict)]
        if len(base_blocks) != len(new_blocks):
            blockers.append("content_block_shape_changed")
        else:
            for before, after in zip(base_blocks, new_blocks):
                for key in _IMMUTABLE_BLOCK_FIELDS:
                    if not _same(before.get(key), after.get(key)):
                        blockers.append(f"immutable_block_{key}")
                for key in after:
                    if key in _IMMUTABLE_BLOCK_FIELDS or key in _EDITABLE_BLOCK_FIELDS:
                        continue
                    if not _same(before.get(key), after.get(key)):
                        blockers.append(f"unsupported_block_edit_{key}")
                if "text" in after and not str(after.get("text") or "").strip() and str(before.get("text") or "").strip():
                    warnings.append("empty_edited_block_text")

        base_visuals = [x for x in (original.get("visual_specs") or []) if isinstance(x, dict)]
        new_visuals = [x for x in (slide.get("visual_specs") or []) if isinstance(x, dict)]
        if len(base_visuals) != len(new_visuals):
            blockers.append("visual_shape_changed")
        else:
            for before, after in zip(base_visuals, new_visuals):
                for key in _IMMUTABLE_VISUAL_FIELDS:
                    if not _same(before.get(key), after.get(key)):
                        blockers.append(f"immutable_visual_{key}")
                for key in after:
                    if key in _IMMUTABLE_VISUAL_FIELDS or key in _EDITABLE_VISUAL_FIELDS:
                        continue
                    if not _same(before.get(key), after.get(key)):
                        blockers.append(f"unsupported_visual_edit_{key}")

        # Smart tables remain source-derived and immutable in this editor phase.
        if not _same(original.get("table_specs"), slide.get("table_specs")):
            blockers.append("table_specs_immutable")

    prepared = copy.deepcopy(edited_blueprint)
    visible = [x for x in (prepared.get("slides") or []) if isinstance(x, dict) and not bool(x.get("hidden"))]
    if not visible:
        blockers.append("at_least_one_visible_slide")
    for order, slide in enumerate(visible, 1):
        slide["order"] = order
        slide.pop("hidden", None)
    prepared["slides"] = visible

    changed = not _same(
        [{k: v for k, v in x.items() if k not in {"order"}} for x in base_slides],
        [{k: v for k, v in x.items() if k not in {"order"}} for x in edited_slides],
    ) or [str(x.get("slide_id") or "") for x in base_slides] != edited_ids

    base_revision = int((base_blueprint.get("approval_state") or {}).get("revision") or 1)
    prepared["approval_state"] = {
        "teacher_approved": False if changed else bool((base_blueprint.get("approval_state") or {}).get("teacher_approved")),
        "revision": base_revision + (1 if changed else 0),
        "edited": changed,
    }

    preflight = presentation_preflight(prepared)
    blockers.extend(preflight.get("blocking_failures") or [])
    warnings.extend(preflight.get("warnings") or [])
    if changed:
        warnings.append("teacher_reapproval_required")

    digest = presentation_edit_digest(base_hash, edited_blueprint)
    return {
        "ready": not blockers,
        "blocking_failures": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "base_hash": base_hash,
        "edit_digest": digest,
        "changed": changed,
        "teacher_reapproval_required": changed,
        "visible_slide_count": len(visible),
        "hidden_slide_count": len(edited_slides) - len(visible),
        "prepared_blueprint": prepared,
        "official_question_bank_write": False,
        "content_ingestion_unchanged": True,
    }
