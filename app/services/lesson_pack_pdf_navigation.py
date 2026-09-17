from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass

import fitz


FINAL_REVIEW_STYLES = {"balanced", "exam_focus", "concept_focus"}


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _lines(value) -> str:
    return _esc(value).replace("\n", "<br>")


def _marker_token(role: str, anchor: str) -> str:
    digest = hashlib.sha1(str(anchor).encode("utf-8")).hexdigest()[:8].upper()
    return f"LPN{role}{digest}"


def _marker_html(role: str, anchor: str) -> str:
    return f'<span class="nav-marker">{_marker_token(role, anchor)}</span>'


def _flag(raw: dict, key: str, default: bool = True) -> bool:
    if key not in raw:
        return default
    value = raw.get(key)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _review_style_for_pack(pack: dict) -> str:
    raw = pack.get("final_review") if isinstance(pack.get("final_review"), dict) else {}
    configured = str(raw.get("style") or "").strip().lower()
    if configured in FINAL_REVIEW_STYLES:
        return configured
    return {
        "exam_revision": "exam_focus",
        "concept_mastery": "concept_focus",
    }.get(str(pack.get("pack_mode") or "").strip().lower(), "balanced")


def normalize_final_review_settings(pack: dict) -> dict:
    """Return bounded presentation settings without adding new scientific content."""
    raw = pack.get("final_review") if isinstance(pack.get("final_review"), dict) else {}
    style = _review_style_for_pack(pack)
    presets = {
        "balanced": {
            "title": "المراجعة النهائية",
            "lead": "استخدم الصفحة دي كمراجعة سريعة قبل الحل أو الاختبار.",
        },
        "exam_focus": {
            "title": "مراجعة ما قبل الاختبار",
            "lead": "راجع القوانين ونقاط الخطأ بسرعة، ثم اختبر نفسك بدون الرجوع للشرح.",
        },
        "concept_focus": {
            "title": "ثبّت فهمك قبل ما تنهي الدرس",
            "lead": "راجع الفكرة الأساسية واربطها بالقوانين والأخطاء الشائعة قبل الانتقال للتدريب.",
        },
    }
    preset = presets[style]
    title = " ".join(str(raw.get("title") or preset["title"]).strip().split())[:80]
    lead = " ".join(str(raw.get("lead") or preset["lead"]).strip().split())[:220]
    return {
        "style": style,
        "title": title or preset["title"],
        "lead": lead or preset["lead"],
        "show_summary": _flag(raw, "show_summary"),
        "show_quick_revision": _flag(raw, "show_quick_revision"),
        "show_laws": _flag(raw, "show_laws"),
        "show_mistakes": _flag(raw, "show_mistakes"),
        "show_checklist": _flag(raw, "show_checklist"),
    }


@dataclass(frozen=True)
class NavigationItem:
    label: str
    anchor: str


def navigation_items(pack: dict) -> list[NavigationItem]:
    """Keep the printable index compact: major study surfaces only."""
    items: list[NavigationItem] = []
    if pack.get("sections"):
        items.append(NavigationItem("شرح الدرس", "nav-lessons"))
    if pack.get("equations_or_rules"):
        items.append(NavigationItem("القوانين والعلاقات", "nav-laws"))
    if pack.get("source_visuals") or pack.get("diagram_specs"):
        items.append(NavigationItem("الرسومات والأشكال", "nav-visuals"))
    if pack.get("worked_examples"):
        items.append(NavigationItem("الأمثلة المحلولة", "nav-examples"))
    if pack.get("practice_questions"):
        items.append(NavigationItem("تدريبات الدرس", "nav-practice"))
    items.append(NavigationItem(normalize_final_review_settings(pack)["title"], "nav-final-review"))
    return items


def _question_items(pack: dict) -> list[NavigationItem]:
    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    return [NavigationItem(f"سؤال {i}", f"nav-question-{i}") for i in range(1, len(questions) + 1)]


def navigation_index_html(pack: dict) -> str:
    rows = "".join(
        '<div class="toc-item">'
        f'<span class="toc-label">{_esc(item.label)}</span>'
        '<span class="toc-dots">................................</span></div>'
        for item in navigation_items(pack)
    )
    return (
        '<section class="toc-page page-break-before page-break-after">'
        + _marker_html("I", "nav-index")
        + '<div class="toc-kicker">دليل سريع للملزمة</div>'
        '<h2>فهرس الملزمة</h2>'
        '<p class="toc-note">في النسخة الرقمية اضغط على العنوان للانتقال مباشرة إلى الجزء المطلوب.</p>'
        + rows
        + '</section>'
    )


def question_navigation_html(pack: dict) -> str:
    items = _question_items(pack)
    if not items:
        return ""
    jumps = "".join(
        f'<span class="question-jump">{_marker_html("S", item.anchor)}{_esc(item.label)}</span>'
        for item in items
    )
    return (
        '<div class="question-map">'
        + _marker_html("M", "nav-question-map")
        + '<b>انتقل مباشرة إلى سؤال:</b><div class="question-jumps">'
        + jumps
        + '</div></div>'
    )


def _review_checklist(style: str) -> list[str]:
    if style == "exam_focus":
        return [
            "أعرف القانون المناسب قبل بدء التعويض.",
            "أراجع الوحدات والتحويلات قبل كتابة الناتج.",
            "أحل تدريبًا كاملًا بدون الرجوع للمثال المحلول.",
            "أراجع الأخطاء الشائعة مرة أخيرة.",
        ]
    if style == "concept_focus":
        return [
            "أقدر أشرح الفكرة الأساسية بكلامي.",
            "أربط كل قانون بالفكرة التي يصفها.",
            "أقدر أفسر الرسم أو الشكل المرتبط بالدرس.",
            "أحل سؤالًا تطبيقيًا بدون الرجوع للشرح.",
        ]
    return [
        "أقدر أشرح الفكرة الأساسية بكلامي.",
        "أعرف متى أستخدم كل قانون موجود في الدرس.",
        "حليت التدريب بدون الرجوع للحل.",
        "راجعت الأخطاء الشائعة مرة أخيرة.",
    ]


def final_review_html(pack: dict) -> str:
    settings = normalize_final_review_settings(pack)
    quick = [x for x in (pack.get("quick_revision") or []) if isinstance(x, dict)]
    laws = [x for x in (pack.get("equations_or_rules") or []) if isinstance(x, dict)]
    mistakes = [x for x in (pack.get("common_mistakes") or []) if isinstance(x, dict)]
    summary = str(pack.get("summary") or "").strip()

    quick_rows = "".join(
        f'<li>{_esc(item.get("text"))}</li>'
        for item in quick
        if str(item.get("text") or "").strip()
    )
    law_rows = "".join(
        '<li><b>' + _esc(item.get("label") or "القانون") + ':</b> '
        + _esc(item.get("expression") or "") + '</li>'
        for item in laws
        if str(item.get("expression") or "").strip()
    )
    mistake_rows = "".join(
        f'<li>{_esc(item.get("text"))}</li>'
        for item in mistakes
        if str(item.get("text") or "").strip()
    )
    blocks = {
        "summary": (
            f'<div class="review-summary"><b>الخلاصة في سطرين:</b><div>{_lines(summary)}</div></div>'
            if summary and settings["show_summary"] else ""
        ),
        "quick": (
            f'<div class="review-box"><h3>نقاط لازم تفتكرها</h3><ul>{quick_rows}</ul></div>'
            if quick_rows and settings["show_quick_revision"] else ""
        ),
        "laws": (
            f'<div class="review-box"><h3>قوانين سريعة</h3><ul>{law_rows}</ul></div>'
            if law_rows and settings["show_laws"] else ""
        ),
        "mistakes": (
            f'<div class="review-box"><h3>قبل الامتحان: تجنب</h3><ul>{mistake_rows}</ul></div>'
            if mistake_rows and settings["show_mistakes"] else ""
        ),
    }
    order = {
        "exam_focus": ("laws", "mistakes", "quick", "summary"),
        "concept_focus": ("summary", "quick", "mistakes", "laws"),
        "balanced": ("summary", "quick", "laws", "mistakes"),
    }[settings["style"]]
    body = "".join(blocks[key] for key in order)
    checklist = ""
    if settings["show_checklist"]:
        rows = "".join(f'<div>□ {_esc(item)}</div>' for item in _review_checklist(settings["style"]))
        checklist = '<div class="review-checklist"><h3>تأكد قبل ما تقفل الملزمة</h3>' + rows + '</div>'
    return (
        f'<section class="final-review final-review-{settings["style"]} page-break-before">'
        + _marker_html("T", "nav-final-review")
        + '<div class="review-kicker">آخر صفحة للمذاكرة</div>'
        + f'<h2>{_esc(settings["title"])}</h2>'
        + f'<p class="review-lead">{_esc(settings["lead"])}</p>'
        + body + checklist
        + '</section>'
    )


def navigation_css() -> str:
    return '''
      .page-break-after { page-break-after:always; }
      .nav-marker { color:#ffffff; font-size:5px; line-height:5px; font-weight:400; white-space:nowrap; }
      .toc-page { min-height:690px; border:1px solid #d0d5dd; padding:18px 22px; box-sizing:border-box; }
      .toc-kicker,.review-kicker { color:#667085; font-size:9pt; font-weight:700; }
      .toc-page h2,.final-review h2 { font-size:20pt; margin-top:8px; }
      .toc-note,.review-lead { color:#667085; font-size:9.5pt; margin-bottom:10px; }
      .toc-item { display:flex; align-items:center; gap:8px; height:22px; margin:0; padding:6px 0; border-bottom:1px solid #eaecf0; font-weight:700; }
      .toc-label { white-space:nowrap; }
      .toc-dots { color:#d0d5dd; overflow:hidden; direction:ltr; flex:1; }
      .question-map { margin:10px 0 14px; padding:9px 11px; border:1px solid #d0d5dd; background:#f8fafc; break-inside:avoid-page; }
      .question-jumps { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
      .question-jump,.question-back { display:inline-block; border:1px solid #98a2b3; border-radius:12px; padding:3px 8px; font-size:8.5pt; color:#344054; }
      .question-back { margin-bottom:6px; border-style:dashed; }
      .final-review { min-height:680px; border:1.5px solid #667085; padding:16px 19px; box-sizing:border-box; background:#fbfcfe; }
      .final-review-exam_focus { border-right:6px solid #b54708; }
      .final-review-concept_focus { border-right:6px solid #175cd3; }
      .review-summary { margin:10px 0 12px; padding:10px 12px; border-right:5px solid #1d4ed8; background:#f8fafc; }
      .review-box { margin:9px 0; padding:8px 11px; border:1px solid #d0d5dd; background:white; break-inside:avoid-page; }
      .review-box h3,.review-checklist h3 { margin:0 0 6px; }
      .review-checklist { margin-top:11px; padding:9px 11px; border:1px dashed #98a2b3; break-inside:avoid-page; }
      .review-checklist div { margin:6px 0; }
    '''


def _inject_question_navigation(out: str, pack: dict) -> str:
    questions = _question_items(pack)
    if not questions:
        return out
    card = '<div class="question-card">'
    first = out.find(card)
    if first < 0:
        return out
    out = out[:first] + question_navigation_html(pack) + out[first:]
    search_from = first + len(question_navigation_html(pack))
    for item in questions:
        pos = out.find(card, search_from)
        if pos < 0:
            break
        decorated = (
            card
            + _marker_html("T", item.anchor)
            + f'<div class="question-back">{_marker_html("B", item.anchor)}↩ خريطة الأسئلة</div>'
        )
        out = out[:pos] + decorated + out[pos + len(card):]
        search_from = pos + len(decorated)
    return out


def enhance_document_html(base_html: str, pack: dict) -> str:
    """Inject compact index plus exact targets for sections and practice questions."""
    out = str(base_html)
    cover_end = out.find("</header>")
    if cover_end < 0:
        raise RuntimeError("Lesson Pack cover marker is missing")
    cover_end += len("</header>")
    out = out[:cover_end] + navigation_index_html(pack) + out[cover_end:]

    if pack.get("sections"):
        out = out.replace(
            '<section class="lesson-section">',
            '<section class="lesson-section">' + _marker_html("T", "nav-lessons"),
            1,
        )
    if pack.get("equations_or_rules"):
        out = out.replace('<section class="laws"><h2>', '<section class="laws"><h2>' + _marker_html("T", "nav-laws"), 1)
    if pack.get("source_visuals"):
        out = out.replace('<section class="source-visuals"><h2>', '<section class="source-visuals"><h2>' + _marker_html("T", "nav-visuals"), 1)
    elif pack.get("diagram_specs"):
        out = out.replace('<section class="diagrams"><h2>', '<section class="diagrams"><h2>' + _marker_html("T", "nav-visuals"), 1)
    if pack.get("worked_examples"):
        out = out.replace('<section class="examples"><h2>', '<section class="examples"><h2>' + _marker_html("T", "nav-examples"), 1)
    if pack.get("practice_questions"):
        out = out.replace('<section class="practice page-break-before"><h2>', '<section class="practice page-break-before"><h2>' + _marker_html("T", "nav-practice"), 1)
        out = _inject_question_navigation(out, pack)
    return out


def _locate_marker(doc: fitz.Document, token: str) -> tuple[int, fitz.Rect] | None:
    for page_index, page in enumerate(doc):
        rects = page.search_for(token)
        if rects:
            return page_index, fitz.Rect(rects[0])
    return None


def _toc_row_rect(page: fitz.Page, index_marker: fitz.Rect, row_index: int) -> fitz.Rect:
    y0 = index_marker.y1 + 78 + (row_index * 34)
    return fitz.Rect(
        page.rect.x0 + 36,
        max(page.rect.y0 + 20, y0),
        page.rect.x1 - 36,
        min(page.rect.y1 - 20, y0 + 32),
    )


def _expand_link_rect(page: fitz.Page, rect: fitz.Rect, *, left: float = 28, right: float = 8) -> fitz.Rect:
    expanded = fitz.Rect(rect.x0 - left, rect.y0 - 6, rect.x1 + right, rect.y1 + 6)
    return expanded & page.rect


def _target_point(marker: fitz.Rect | None) -> fitz.Point:
    if marker is None:
        return fitz.Point(0, 0)
    return fitz.Point(0, max(0, marker.y0 - 14))


def add_pdf_navigation(data: bytes, pack: dict, _positions=None) -> bytes:
    """Build main navigation, per-question links/bookmarks, and return-to-question-map links."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        index = _locate_marker(doc, _marker_token("I", "nav-index"))
        if not index:
            return data
        index_page, index_marker = index

        resolved: list[tuple[NavigationItem, int, fitz.Rect | None]] = []
        marker_rects: dict[int, list[fitz.Rect]] = {index_page: [index_marker]}
        for item in navigation_items(pack):
            if item.anchor == "nav-final-review":
                resolved.append((item, doc.page_count - 1, None))
                continue
            target = _locate_marker(doc, _marker_token("T", item.anchor))
            if not target:
                continue
            target_page, target_marker = target
            resolved.append((item, target_page, target_marker))
            marker_rects.setdefault(target_page, []).append(target_marker)

        question_map = _locate_marker(doc, _marker_token("M", "nav-question-map"))
        question_resolved: list[tuple[NavigationItem, int, fitz.Rect, int, fitz.Rect, int | None, fitz.Rect | None]] = []
        if question_map:
            marker_rects.setdefault(question_map[0], []).append(question_map[1])
        for item in _question_items(pack):
            target = _locate_marker(doc, _marker_token("T", item.anchor))
            source = _locate_marker(doc, _marker_token("S", item.anchor))
            back = _locate_marker(doc, _marker_token("B", item.anchor))
            if not target or not source:
                continue
            target_page, target_marker = target
            source_page, source_marker = source
            back_page, back_marker = back if back else (None, None)
            question_resolved.append(
                (item, target_page, target_marker, source_page, source_marker, back_page, back_marker)
            )
            marker_rects.setdefault(target_page, []).append(target_marker)
            marker_rects.setdefault(source_page, []).append(source_marker)
            if back_page is not None and back_marker is not None:
                marker_rects.setdefault(back_page, []).append(back_marker)

        for page_index, rects in marker_rects.items():
            page = doc[page_index]
            for rect in rects:
                page.add_redact_annot(rect + (-0.5, -0.5, 0.5, 0.5), fill=None)
            page.apply_redactions()

        outline: list[list] = [[1, str(pack.get("title") or "ملزمة الدرس"), 1]]
        for row_index, (item, target_page, target_marker) in enumerate(resolved):
            outline.append([1, item.label, target_page + 1])
            click_rect = _toc_row_rect(doc[index_page], index_marker, row_index)
            if not click_rect.is_empty and not click_rect.is_infinite:
                doc[index_page].insert_link({
                    "kind": fitz.LINK_GOTO,
                    "from": click_rect,
                    "page": target_page,
                    "to": _target_point(target_marker),
                })
            if item.anchor == "nav-practice":
                for q_item, q_page, _q_marker, *_ in question_resolved:
                    outline.append([2, q_item.label, q_page + 1])

        for item, target_page, target_marker, source_page, source_marker, back_page, back_marker in question_resolved:
            source_rect = _expand_link_rect(doc[source_page], source_marker, left=10, right=34)
            if not source_rect.is_empty:
                doc[source_page].insert_link({
                    "kind": fitz.LINK_GOTO,
                    "from": source_rect,
                    "page": target_page,
                    "to": _target_point(target_marker),
                })
            if question_map and back_page is not None and back_marker is not None:
                back_rect = _expand_link_rect(doc[back_page], back_marker, left=8, right=58)
                if not back_rect.is_empty:
                    doc[back_page].insert_link({
                        "kind": fitz.LINK_GOTO,
                        "from": back_rect,
                        "page": question_map[0],
                        "to": _target_point(question_map[1]),
                    })

        if len(outline) > 1:
            doc.set_toc(outline)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
