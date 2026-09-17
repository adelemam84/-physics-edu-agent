from __future__ import annotations

import re
from typing import Any

import fitz

from .lesson_pack_core import validate_pack_provenance
from .lesson_pack_pdf_navigation import navigation_items, normalize_final_review_settings
from .lesson_pack_practice_layout import (
    answer_sheet_html,
    practice_layout_settings,
    prepare_practice_pack,
    self_test_html,
    self_test_items,
    teacher_self_test_key_html,
)
from .lesson_pack_teacher_practice_appendix import TEACHER_SELF_TEST_BOOKMARK

MAX_EXPORT_PAGES = 240
_A4 = fitz.paper_rect("a4")
_NAV_MARKER_RE = re.compile(r"LPN[A-Z][0-9A-F]{8}")


def _check(
    check_id: str,
    passed: bool,
    *,
    blocking: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "blocking": bool(blocking),
        "details": details or {},
    }


def _report(kind: str, checks: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    blockers = [item["id"] for item in checks if item["blocking"] and not item["passed"]]
    return {
        "kind": kind,
        "ready": not blockers,
        "blocking_failures": blockers,
        "checks": checks,
        **extra,
    }


def pack_preflight(pack: dict, allowed_refs: list[str] | None = None) -> dict[str, Any]:
    """Validate export policy and deterministic practice structure without mutating the pack."""
    render_pack = prepare_practice_pack(pack)
    questions = [q for q in (render_pack.get("practice_questions") or []) if isinstance(q, dict)]
    checks: list[dict[str, Any]] = []

    policy_violations: list[str] = []
    for index, question in enumerate(questions, 1):
        if question.get("generated") is not True:
            policy_violations.append(f"practice_questions[{index}].generated")
        if question.get("official_question_bank") is not False:
            policy_violations.append(f"practice_questions[{index}].official_question_bank")
        if question.get("question_bank_eligible") is not False:
            policy_violations.append(f"practice_questions[{index}].question_bank_eligible")
        if question.get("teacher_review_required") is not True:
            policy_violations.append(f"practice_questions[{index}].teacher_review_required")
    question_policy = (
        render_pack.get("question_policy")
        if isinstance(render_pack.get("question_policy"), dict)
        else {}
    )
    if question_policy.get("official_question_bank_write") is not False:
        policy_violations.append("question_policy.official_question_bank_write")
    if question_policy.get("auto_publish") is not False:
        policy_violations.append("question_policy.auto_publish")
    checks.append(
        _check(
            "generated_practice_policy",
            bool(questions) and not policy_violations,
            details={"question_count": len(questions), "violations": policy_violations},
        )
    )

    ids = [str(q.get("id") or "").strip() for q in questions]
    duplicate_ids = sorted({value for value in ids if value and ids.count(value) > 1})
    checks.append(
        _check(
            "practice_question_identity",
            bool(questions) and all(ids) and not duplicate_ids,
            details={
                "duplicate_ids": duplicate_ids,
                "missing_id_count": sum(1 for value in ids if not value),
            },
        )
    )

    rank = {"easy": 0, "medium": 1, "hard": 2}
    difficulties = [str(q.get("difficulty") or "medium").strip().lower() for q in questions]
    ranks = [rank.get(value, 1) for value in difficulties]
    checks.append(
        _check(
            "deterministic_practice_order",
            ranks == sorted(ranks),
            details={"order": difficulties},
        )
    )

    selected = self_test_items(render_pack)
    selected_positions = [int(item["practice_no"]) for item in selected]
    settings = practice_layout_settings(render_pack)
    expected_count = settings["self_test_count"]
    checks.append(
        _check(
            "self_test_subset_consistency",
            len(selected) == expected_count
            and len(selected_positions) == len(set(selected_positions))
            and all(1 <= position <= len(questions) for position in selected_positions),
            details={
                "selected_count": len(selected),
                "expected_count": expected_count,
                "practice_positions": selected_positions,
            },
        )
    )

    student_self_test = self_test_html(render_pack)
    student_answer_sheet = answer_sheet_html(render_pack)
    teacher_key = teacher_self_test_key_html(render_pack)
    missing_practice_surfaces: list[str] = []
    if expected_count and not student_self_test:
        missing_practice_surfaces.append("student_self_test")
    if expected_count and settings["show_answer_sheet"] and not student_answer_sheet:
        missing_practice_surfaces.append("student_answer_sheet")
    if expected_count and not teacher_key:
        missing_practice_surfaces.append("teacher_self_test_key")
    checks.append(
        _check(
            "practice_surface_contract",
            not missing_practice_surfaces,
            details={"missing": missing_practice_surfaces},
        )
    )

    visuals = [x for x in (render_pack.get("source_visuals") or []) if isinstance(x, dict)]
    unresolved_visuals = [str(x.get("id") or "") for x in visuals if x.get("review_required")]
    broken_approved_visuals = [
        str(x.get("id") or "")
        for x in visuals
        if x.get("approved") and not x.get("object_key")
    ]
    checks.append(
        _check(
            "source_visual_review_complete",
            not unresolved_visuals and not broken_approved_visuals,
            details={
                "unresolved": unresolved_visuals,
                "approved_without_object": broken_approved_visuals,
            },
        )
    )

    artifact_policy = (
        render_pack.get("artifact_policy")
        if isinstance(render_pack.get("artifact_policy"), dict)
        else {}
    )
    checks.append(
        _check(
            "artifact_export_policy",
            artifact_policy.get("official_question_bank_write") is False
            and artifact_policy.get("teacher_approval_required_for_final_export") is True,
            details={
                "official_question_bank_write": artifact_policy.get("official_question_bank_write"),
                "teacher_approval_required_for_final_export": artifact_policy.get(
                    "teacher_approval_required_for_final_export"
                ),
            },
        )
    )

    if allowed_refs is not None:
        provenance = validate_pack_provenance(render_pack, allowed_refs)
        checks.append(
            _check(
                "source_provenance",
                bool(provenance.get("passed")),
                details=provenance,
            )
        )

    return _report(
        "lesson_pack",
        checks,
        question_count=len(questions),
        self_test_count=len(selected),
    )


def _pdf_text(doc: fitz.Document) -> str:
    return "\n".join(page.get_text() for page in doc)


def pdf_preflight(data: bytes, pack: dict, edition: str) -> dict[str, Any]:
    """Validate the exact rendered PDF bytes before preview/export storage or delivery."""
    if edition not in {"student", "teacher"}:
        raise ValueError("edition must be student or teacher")

    checks: list[dict[str, Any]] = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return _report(
            "lesson_pack_pdf",
            [_check("valid_pdf", False, details={"error": type(exc).__name__})],
            edition=edition,
            page_count=0,
        )

    try:
        page_count = doc.page_count
        checks.append(
            _check(
                "valid_pdf",
                data.startswith(b"%PDF") and 0 < page_count <= MAX_EXPORT_PAGES,
                details={"page_count": page_count, "max_pages": MAX_EXPORT_PAGES},
            )
        )

        non_a4: list[int] = []
        for index, page in enumerate(doc, 1):
            rect = page.rect
            if abs(rect.width - _A4.width) > 4 or abs(rect.height - _A4.height) > 4:
                non_a4.append(index)
        checks.append(
            _check(
                "a4_page_geometry",
                not non_a4,
                details={"non_a4_pages": non_a4},
            )
        )

        invalid_links: list[dict[str, int]] = []
        goto_count = 0
        for page_index, page in enumerate(doc):
            for link in page.get_links():
                if link.get("kind") != fitz.LINK_GOTO:
                    continue
                goto_count += 1
                target = int(link.get("page", -1))
                if target < 0 or target >= page_count:
                    invalid_links.append(
                        {"source_page": page_index + 1, "target_page": target + 1}
                    )
        checks.append(
            _check(
                "internal_link_destinations",
                not invalid_links,
                details={"goto_link_count": goto_count, "invalid_links": invalid_links},
            )
        )

        toc = doc.get_toc(simple=True)
        toc_titles = [str(item[1]) for item in toc if len(item) >= 3]
        invalid_toc = [
            {"title": str(item[1]), "page": int(item[2])}
            for item in toc
            if len(item) >= 3 and (int(item[2]) < 1 or int(item[2]) > page_count)
        ]
        checks.append(
            _check(
                "bookmark_destinations",
                not invalid_toc,
                details={"bookmark_count": len(toc), "invalid_bookmarks": invalid_toc},
            )
        )

        text = _pdf_text(doc)
        marker_tokens = sorted(set(_NAV_MARKER_RE.findall(text)))
        blocking_markers = [token for token in marker_tokens if not token.startswith("LPNS")]
        source_markers = [token for token in marker_tokens if token.startswith("LPNS")]
        checks.append(
            _check(
                "navigation_marker_cleanup",
                not blocking_markers,
                details={"remaining_blocking_markers": blocking_markers},
            )
        )
        checks.append(
            _check(
                "navigation_source_marker_cleanup",
                not source_markers,
                blocking=False,
                details={"remaining_source_markers": source_markers},
            )
        )

        render_pack = prepare_practice_pack(pack)
        practice = [
            q for q in (render_pack.get("practice_questions") or []) if isinstance(q, dict)
        ]
        selected = self_test_items(render_pack)

        if edition == "student":
            expected_titles = [item.label for item in navigation_items(render_pack)]
            title_set = set(toc_titles)
            missing_titles = [title for title in expected_titles if title not in title_set]
            checks.append(
                _check(
                    "student_main_navigation",
                    not missing_titles,
                    details={"missing_main_bookmarks": missing_titles},
                )
            )

            question_bookmarks = [
                item
                for item in toc
                if len(item) >= 3
                and int(item[0]) == 2
                and str(item[1]).startswith("سؤال ")
            ]
            checks.append(
                _check(
                    "student_question_navigation",
                    len(question_bookmarks) == len(practice),
                    blocking=False,
                    details={
                        "question_bookmark_count": len(question_bookmarks),
                        "expected_question_bookmarks": len(practice),
                    },
                )
            )

            checks.append(
                _check(
                    "student_teacher_appendix_absent",
                    TEACHER_SELF_TEST_BOOKMARK not in title_set,
                    details={"teacher_appendix_bookmark_present": TEACHER_SELF_TEST_BOOKMARK in title_set},
                )
            )

            review_title = normalize_final_review_settings(render_pack)["title"]
            review_rows = [
                item for item in toc if len(item) >= 3 and str(item[1]) == review_title
            ]
            checks.append(
                _check(
                    "final_review_is_last_page",
                    len(review_rows) == 1 and int(review_rows[0][2]) == page_count,
                    details={
                        "review_title": review_title,
                        "bookmark_pages": [int(item[2]) for item in review_rows],
                        "page_count": page_count,
                    },
                )
            )

        else:
            answer_rows = [
                item
                for item in toc
                if len(item) >= 3 and str(item[1]) == TEACHER_SELF_TEST_BOOKMARK
            ]
            checks.append(
                _check(
                    "teacher_answer_appendix",
                    not selected or len(answer_rows) == 1,
                    details={
                        "bookmark_count": len(answer_rows),
                        "self_test_count": len(selected),
                        "bookmark_pages": [int(item[2]) for item in answer_rows],
                    },
                )
            )

        return _report(
            "lesson_pack_pdf",
            checks,
            edition=edition,
            page_count=page_count,
        )
    finally:
        doc.close()
