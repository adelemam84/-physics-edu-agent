from __future__ import annotations

import html
from dataclasses import dataclass

import fitz


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _lines(value) -> str:
    return _esc(value).replace("\n", "<br>")


@dataclass(frozen=True)
class NavigationItem:
    label: str
    anchor: str
    level: int = 1


def navigation_items(pack: dict) -> list[NavigationItem]:
    items: list[NavigationItem] = []
    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    if sections:
        items.append(NavigationItem("شرح الدرس", "nav-lessons"))
        for index, section in enumerate(sections, 1):
            heading = str(section.get("heading") or f"فكرة {index}").strip()
            if heading:
                items.append(NavigationItem(heading, f"nav-section-{index}", 2))
    if pack.get("equations_or_rules"):
        items.append(NavigationItem("القوانين والعلاقات", "nav-laws"))
    if pack.get("source_visuals") or pack.get("diagram_specs"):
        items.append(NavigationItem("الرسومات والأشكال", "nav-visuals"))
    if pack.get("worked_examples"):
        items.append(NavigationItem("الأمثلة المحلولة", "nav-examples"))
    if pack.get("practice_questions"):
        items.append(NavigationItem("تدريبات الدرس", "nav-practice"))
    items.append(NavigationItem("المراجعة النهائية", "nav-final-review"))
    return items


def navigation_index_html(pack: dict) -> str:
    rows: list[str] = []
    for item in navigation_items(pack):
        cls = "toc-item toc-subitem" if item.level > 1 else "toc-item"
        rows.append(
            f'<div class="{cls}"><a class="toc-link" href="#{_esc(item.anchor)}">'
            f'<span class="toc-label">{_esc(item.label)}</span>'
            '<span class="toc-dots">................................</span></a></div>'
        )
    return (
        '<section class="toc-page page-break-before page-break-after">'
        '<div class="toc-kicker">دليل سريع للملزمة</div>'
        '<h2>فهرس الملزمة</h2>'
        '<p class="toc-note">في النسخة الرقمية اضغط على العنوان للانتقال مباشرة إلى الجزء المطلوب.</p>'
        + "".join(rows)
        + '</section>'
    )


def final_review_html(pack: dict) -> str:
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
    summary_html = (
        f'<div class="review-summary"><b>الخلاصة في سطرين:</b><div>{_lines(summary)}</div></div>'
        if summary else ""
    )
    quick_html = f'<div class="review-box"><h3>نقاط لازم تفتكرها</h3><ul>{quick_rows}</ul></div>' if quick_rows else ""
    laws_html = f'<div class="review-box"><h3>قوانين سريعة</h3><ul>{law_rows}</ul></div>' if law_rows else ""
    mistakes_html = f'<div class="review-box"><h3>قبل الامتحان: تجنب</h3><ul>{mistake_rows}</ul></div>' if mistake_rows else ""

    checklist = (
        '<div class="review-checklist"><h3>تأكد قبل ما تقفل الملزمة</h3>'
        '<div>□ أقدر أشرح الفكرة الأساسية بكلامي.</div>'
        '<div>□ أعرف متى أستخدم كل قانون موجود في الدرس.</div>'
        '<div>□ حليت التدريب بدون الرجوع للحل.</div>'
        '<div>□ راجعت الأخطاء الشائعة مرة أخيرة.</div></div>'
    )
    return (
        '<section class="final-review page-break-before" id="nav-final-review">'
        '<div class="review-kicker">آخر صفحة للمذاكرة</div>'
        '<h2>المراجعة النهائية</h2>'
        '<p class="review-lead">استخدم الصفحة دي كمراجعة سريعة قبل الحل أو الاختبار.</p>'
        + summary_html + quick_html + laws_html + mistakes_html + checklist
        + '</section>'
    )


def navigation_css() -> str:
    return '''
      .page-break-after { page-break-after:always; }
      .toc-page { min-height:690px; border:1px solid #d0d5dd; padding:18px 22px; box-sizing:border-box; }
      .toc-kicker,.review-kicker { color:#667085; font-size:9pt; font-weight:700; }
      .toc-page h2,.final-review h2 { font-size:20pt; margin-top:8px; }
      .toc-note,.review-lead { color:#667085; font-size:9.5pt; }
      .toc-item { margin:10px 0; padding:6px 0; border-bottom:1px solid #eaecf0; font-weight:700; }
      .toc-subitem { margin-right:22px; font-weight:500; font-size:10.5pt; }
      .toc-link { display:flex; align-items:center; gap:8px; color:#172033; text-decoration:none; }
      .toc-label { white-space:nowrap; }
      .toc-dots { color:#d0d5dd; overflow:hidden; direction:ltr; flex:1; }
      .final-review { min-height:680px; border:1.5px solid #667085; padding:16px 19px; box-sizing:border-box; background:#fbfcfe; }
      .review-summary { margin:10px 0 12px; padding:10px 12px; border-right:5px solid #1d4ed8; background:#f8fafc; }
      .review-box { margin:9px 0; padding:8px 11px; border:1px solid #d0d5dd; background:white; break-inside:avoid-page; }
      .review-box h3,.review-checklist h3 { margin:0 0 6px; }
      .review-checklist { margin-top:11px; padding:9px 11px; border:1px dashed #98a2b3; break-inside:avoid-page; }
      .review-checklist div { margin:6px 0; }
    '''


def enhance_document_html(base_html: str, pack: dict) -> str:
    """Inject same-document anchors, index and final review before rendering."""
    out = str(base_html)
    cover_end = out.find("</header>")
    if cover_end < 0:
        raise RuntimeError("Lesson Pack cover marker is missing")
    cover_end += len("</header>")
    out = out[:cover_end] + navigation_index_html(pack) + out[cover_end:]

    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    if sections:
        out = out.replace(
            '<section class="lesson-section">',
            '<section class="lesson-section" id="nav-lessons">',
            1,
        )
        for index, section in enumerate(sections, 1):
            heading = _esc(section.get("heading") or f"فكرة {index}")
            old = f'<h2>{heading}</h2>'
            new = f'<h2 id="nav-section-{index}">{heading}</h2>'
            out = out.replace(old, new, 1)

    if pack.get("equations_or_rules"):
        out = out.replace(
            '<section class="laws"><h2>',
            '<section class="laws"><h2 id="nav-laws">',
            1,
        )
    if pack.get("source_visuals"):
        out = out.replace(
            '<section class="source-visuals"><h2>',
            '<section class="source-visuals"><h2 id="nav-visuals">',
            1,
        )
    elif pack.get("diagram_specs"):
        out = out.replace(
            '<section class="diagrams"><h2>',
            '<section class="diagrams"><h2 id="nav-visuals">',
            1,
        )
    if pack.get("worked_examples"):
        out = out.replace(
            '<section class="examples"><h2>',
            '<section class="examples"><h2 id="nav-examples">',
            1,
        )
    if pack.get("practice_questions"):
        out = out.replace(
            '<section class="practice page-break-before"><h2>',
            '<section class="practice page-break-before"><h2 id="nav-practice">',
            1,
        )

    notes_marker = '<section class="notes">'
    notes_pos = out.find(notes_marker)
    if notes_pos >= 0:
        out = out[:notes_pos] + final_review_html(pack) + out[notes_pos:]
    else:
        footer_pos = out.find("<footer>")
        insertion = footer_pos if footer_pos >= 0 else len(out)
        out = out[:insertion] + final_review_html(pack) + out[insertion:]
    return out


def add_pdf_navigation(data: bytes, pack: dict) -> bytes:
    """Build PDF outline from native same-document GoTo links; never text-search Arabic glyphs."""
    expected = navigation_items(pack)
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        internal_links: list[dict] = []
        for page in doc:
            for link in page.get_links():
                if link.get("kind") == fitz.LINK_GOTO and isinstance(link.get("page"), int):
                    internal_links.append(link)
        if not internal_links:
            return data

        outline: list[list] = [[1, str(pack.get("title") or "ملزمة الدرس"), 1]]
        for item, link in zip(expected, internal_links):
            target_page = int(link["page"]) + 1
            outline.append([item.level, item.label, target_page])
        if len(outline) > 1:
            doc.set_toc(outline)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
