from __future__ import annotations

from typing import Any

CANVA_MASTER_DESIGN_ID = "DAHUkN3i5p4"

CANVA_MASTER_TEXT_FIELDS = (
    "LESSON_TITLE",
    "SUBJECT_GRADE",
    "OVERVIEW_TITLE",
    "OVERVIEW_BODY",
    "MINDMAP_TITLE",
    "MINDMAP_BRANCH_1_TITLE",
    "MINDMAP_BRANCH_1_BODY",
    "MINDMAP_BRANCH_2_TITLE",
    "MINDMAP_BRANCH_2_BODY",
    "MINDMAP_BRANCH_3_TITLE",
    "MINDMAP_BRANCH_3_BODY",
    "MINDMAP_CORE",
    "PROCESS_TITLE",
    "PROCESS_STEP_1_TITLE",
    "PROCESS_STEP_1_BODY",
    "PROCESS_STEP_2_TITLE",
    "PROCESS_STEP_2_BODY",
    "COMPARISON_TITLE",
    "COMPARE_A_TITLE",
    "COMPARE_A_BODY",
    "COMPARE_B_TITLE",
    "COMPARE_B_BODY",
    "EQUATIONS_TITLE",
    "EQUATIONS_BODY",
    "FIGURE_TITLE",
    "FIGURE_CALLOUT_1",
    "FIGURE_CALLOUT_2",
    "EXAMPLE_TITLE",
    "EXAMPLE_PROBLEM",
    "EXAMPLE_SOLUTION",
    "EXAMPLE_METHOD",
    "EXAM_NOTES",
    "TIPS_TITLE",
    "COMMON_MISTAKE",
    "EXAM_TIP",
    "GOLDEN_HINT",
    "SUMMARY_TITLE",
    "SUMMARY_FOOTER",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def canva_master_values(summary: dict) -> dict[str, str]:
    """Build the source-grounded Canva autofill payload.

    Fields unsupported by the uploaded lesson are intentionally left blank.
    This prevents the visual layer from silently inventing examples, tips,
    misconceptions, or scientific facts.
    """
    sections = list(summary.get("sections") or [])
    equations = list(summary.get("equations") or [])
    diagrams = list(summary.get("diagrams") or [])

    def sec(i: int) -> dict:
        return sections[i] if i < len(sections) else {}

    def sec_title(i: int) -> str:
        return _text(sec(i).get("title"))

    def sec_body(i: int) -> str:
        return _text(sec(i).get("summary"))

    subject_grade = " · ".join(
        x for x in (_text(summary.get("subject")), _text(summary.get("grade_label"))) if x
    )

    equation_lines: list[str] = []
    for item in equations[:6]:
        label = _text(item.get("label"))
        expression = _text(item.get("expression"))
        notes = _text(item.get("notes"))
        line = ": ".join(x for x in (label, expression) if x)
        if notes:
            line = f"{line} — {notes}" if line else notes
        if line:
            equation_lines.append(line)

    figure1 = diagrams[0] if diagrams else {}
    figure2 = diagrams[1] if len(diagrams) > 1 else {}
    labels = " ← ".join(_text(x) for x in (figure1.get("labels") or []) if _text(x))
    figure1_body = _text(figure1.get("description"))
    if labels:
        figure1_body = f"{figure1_body}\n{labels}".strip()

    values = {
        "LESSON_TITLE": _text(summary.get("title")),
        "SUBJECT_GRADE": subject_grade,
        "OVERVIEW_TITLE": "نظرة عامة على الدرس",
        "OVERVIEW_BODY": "\n".join(
            f"{i}. {_text(item.get('title'))}"
            for i, item in enumerate(sections[:6], 1)
            if _text(item.get("title"))
        ),
        "MINDMAP_TITLE": "الخريطة الذهنية",
        "MINDMAP_BRANCH_1_TITLE": sec_title(0),
        "MINDMAP_BRANCH_1_BODY": sec_body(0),
        "MINDMAP_BRANCH_2_TITLE": sec_title(1),
        "MINDMAP_BRANCH_2_BODY": sec_body(1),
        "MINDMAP_BRANCH_3_TITLE": sec_title(2),
        "MINDMAP_BRANCH_3_BODY": sec_body(2),
        "MINDMAP_CORE": _text(summary.get("summary")),
        "PROCESS_TITLE": "تسلسل الدرس",
        "PROCESS_STEP_1_TITLE": sec_title(0),
        "PROCESS_STEP_1_BODY": sec_body(0),
        "PROCESS_STEP_2_TITLE": sec_title(1),
        "PROCESS_STEP_2_BODY": sec_body(1),
        "COMPARISON_TITLE": "مقارنة علمية" if len(sections) >= 2 else "",
        "COMPARE_A_TITLE": sec_title(0) if len(sections) >= 2 else "",
        "COMPARE_A_BODY": sec_body(0) if len(sections) >= 2 else "",
        "COMPARE_B_TITLE": sec_title(1) if len(sections) >= 2 else "",
        "COMPARE_B_BODY": sec_body(1) if len(sections) >= 2 else "",
        "EQUATIONS_TITLE": "القوانين والمعادلات" if equation_lines else "",
        "EQUATIONS_BODY": "\n".join(equation_lines),
        "FIGURE_TITLE": _text(figure1.get("title")),
        "FIGURE_CALLOUT_1": figure1_body,
        "FIGURE_CALLOUT_2": _text(figure2.get("description")),
        # These stay blank until explicitly supported by the uploaded source.
        "EXAMPLE_TITLE": "",
        "EXAMPLE_PROBLEM": "",
        "EXAMPLE_SOLUTION": "",
        "EXAMPLE_METHOD": "",
        "EXAM_NOTES": "",
        "TIPS_TITLE": "",
        "COMMON_MISTAKE": "",
        "EXAM_TIP": "",
        "GOLDEN_HINT": "",
        "SUMMARY_TITLE": "ملخص الإتقان",
        "SUMMARY_FOOTER": _text(summary.get("summary")),
    }
    return {field: values.get(field, "") for field in CANVA_MASTER_TEXT_FIELDS}
