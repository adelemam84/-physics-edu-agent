from __future__ import annotations

import copy
import json
import re
from typing import Any

from . import lesson_presentation_studio
from .services import lesson_presentation_editor as base_editor

_DUPLICATE_ID = re.compile(r"^dup-[A-Za-z0-9_-]{1,96}-[A-Fa-f0-9]{8,32}$")
_MAX_SLIDES = 40
_MAX_DUPLICATES = 10


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _clean_for_compare(value: dict) -> dict:
    out = copy.deepcopy(value)
    out.pop("preflight", None)
    out.pop("approval_state", None)
    for slide in out.get("slides") or []:
        if isinstance(slide, dict):
            slide.pop("order", None)
    return out


def _table_blockers(before: list[dict], after: list[dict]) -> list[str]:
    blockers: list[str] = []
    if len(before) != len(after):
        return ["table_spec_shape_changed"]
    for old, new in zip(before, after):
        if not isinstance(old, dict) or not isinstance(new, dict):
            blockers.append("table_spec_invalid")
            continue
        if str(old.get("kind") or "") != str(new.get("kind") or ""):
            blockers.append("table_kind_immutable")
        old_cols = [str(x) for x in (old.get("columns") or [])]
        new_cols = [str(x) for x in (new.get("columns") or [])]
        if old_cols != new_cols:
            blockers.append("table_columns_immutable")
        old_rows = [x for x in (old.get("rows") or []) if isinstance(x, dict)]
        new_rows = [x for x in (new.get("rows") or []) if isinstance(x, dict)]
        if len(old_rows) != len(new_rows):
            blockers.append("table_row_shape_changed")
            continue
        allowed = set(old_cols) | {"source_refs"}
        for old_row, new_row in zip(old_rows, new_rows):
            if list(old_row.get("source_refs") or []) != list(new_row.get("source_refs") or []):
                blockers.append("table_source_refs_immutable")
            if set(new_row) - allowed:
                blockers.append("table_row_fields_immutable")
            if set(old_row) - allowed:
                blockers.append("table_row_fields_unsupported")
    return blockers


def validate_presentation_productivity_edits(
    base_blueprint: dict,
    edited_blueprint: dict,
    *,
    supplied_base_hash: str | None = None,
) -> dict:
    original_hash = base_editor.presentation_editor_base_hash(base_blueprint)
    early_blockers: list[str] = []
    if not supplied_base_hash:
        early_blockers.append("editor_base_hash_required")
    elif supplied_base_hash != original_hash:
        early_blockers.append("stale_editor_base")
    if not isinstance(edited_blueprint, dict):
        return base_editor.validate_presentation_edits(
            base_blueprint,
            edited_blueprint,
            supplied_base_hash=supplied_base_hash,
        )

    base_slides = [x for x in (base_blueprint.get("slides") or []) if isinstance(x, dict)]
    edited_slides = [x for x in (edited_blueprint.get("slides") or []) if isinstance(x, dict)]
    base_by_id = {str(x.get("slide_id") or ""): x for x in base_slides}
    if len(edited_slides) > _MAX_SLIDES:
        early_blockers.append("editor_slide_limit")

    augmented = copy.deepcopy(base_blueprint)
    augmented_slides = [x for x in (augmented.get("slides") or []) if isinstance(x, dict)]
    augmented_by_id = {str(x.get("slide_id") or ""): x for x in augmented_slides}
    duplicate_count = 0

    for edited in edited_slides:
        sid = str(edited.get("slide_id") or "")
        if sid in base_by_id:
            continue
        duplicate_count += 1
        source_id = str(edited.get("duplicate_of") or "")
        source = base_by_id.get(source_id)
        if not source or not _DUPLICATE_ID.match(sid):
            early_blockers.append("unsafe_duplicate_slide")
            continue
        duplicated = copy.deepcopy(source)
        duplicated["slide_id"] = sid
        duplicated["duplicate_of"] = source_id
        duplicated["order"] = edited.get("order")
        augmented_slides.append(duplicated)
        augmented_by_id[sid] = duplicated

    if duplicate_count > _MAX_DUPLICATES:
        early_blockers.append("editor_duplicate_limit")
    augmented["slides"] = augmented_slides

    # Validate Smart Table edits before relaxing the old immutable-table rule.
    for edited in edited_slides:
        sid = str(edited.get("slide_id") or "")
        baseline = augmented_by_id.get(sid)
        if not baseline:
            continue
        old_tables = [x for x in (baseline.get("table_specs") or []) if isinstance(x, dict)]
        new_tables = [x for x in (edited.get("table_specs") or []) if isinstance(x, dict)]
        early_blockers.extend(_table_blockers(old_tables, new_tables))
        # Once structure/provenance is verified, let the base validator see cell edits as baseline.
        baseline["table_specs"] = copy.deepcopy(new_tables)

    augmented_hash = base_editor.presentation_editor_base_hash(augmented)
    report = base_editor.validate_presentation_edits(
        augmented,
        edited_blueprint,
        supplied_base_hash=augmented_hash,
    )

    blockers = list(dict.fromkeys(early_blockers + list(report.get("blocking_failures") or [])))
    changed = _canonical(_clean_for_compare(base_blueprint)) != _canonical(_clean_for_compare(edited_blueprint))
    prepared = report.get("prepared_blueprint")
    if isinstance(prepared, dict):
        base_revision = int((base_blueprint.get("approval_state") or {}).get("revision") or 1)
        prepared["approval_state"] = {
            "teacher_approved": False if changed else bool((base_blueprint.get("approval_state") or {}).get("teacher_approved")),
            "revision": base_revision + (1 if changed else 0),
            "edited": changed,
        }

    report["ready"] = not blockers
    report["blocking_failures"] = blockers
    report["base_hash"] = original_hash
    report["edit_digest"] = base_editor.presentation_edit_digest(original_hash, edited_blueprint)
    report["changed"] = changed
    report["teacher_reapproval_required"] = changed
    report["prepared_blueprint"] = prepared
    report["duplicate_slide_count"] = duplicate_count
    report["smart_table_editing"] = True
    report["official_question_bank_write"] = False
    report["content_ingestion_unchanged"] = True
    return report


# lesson_presentation_studio imported the validator by name. Replace that runtime
# binding so editor preflight and export use the enhanced validator without
# changing the official content-ingestion path.
lesson_presentation_studio.validate_presentation_edits = validate_presentation_productivity_edits
