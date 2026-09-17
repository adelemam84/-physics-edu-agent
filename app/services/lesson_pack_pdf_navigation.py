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
    target: str
    level: int = 1


def navigation_items(pack: dict) -> list[NavigationItem]:
    items: list[NavigationItem] = []
    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    if sections:
        items.append(NavigationItem("شرح الدرس", str(sections[0].get("heading") or "فكرة 1")))
        for index, section in enumerate(sections, 1):
            heading = str(section.get("heading") or f"فكرة {index}").strip()
            if heading:
                items.append(NavigationItem(heading, heading, 2))
    if pack.get("equations_or_rules"):
        items.append(NavigationItem("القوانين والعلاقات", "القوانين والعلاقات المهمة"))
    if pack.get("source_visuals") or pack.get("diagram_specs"):
        target = "من المصدر الأصلي" if pack.get("source_visuals") else "افهمها بالرسم"
        items.append(NavigationItem("الرسومات والأشكال", target))
    if pack.get("worked_examples"):
        items.append(NavigationItem("الأمثلة المحلولة", "أمثلة محلولة خطوة بخطوة"))
    if pack.get("practice_questions"):
        items.append(NavigationItem("تدريبات الدرس", "تدريبات الدرس"))
    items.append(NavigationItem("المراجعة النهائية", "المراجعة النهائية"))
    return items


def navigation_index_html(pack: dict) -> str:
    rows: list[str] = []
    for item in navigation_items(pack):
        cls = "toc-item toc-subitem" if item.level > 1 else "toc-item"
        rows.append(
            f'<div class="{cls}"><span class="toc-label">{_esc(item.label)}</span>'
            '<span class="toc-dots">................................</span></div>'
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
        '<section class="final-review page-break-before">'
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
      .toc-item { display:flex; align-items:center; gap:8px; margin:10px 0; padding:6px 0; border-bottom:1px solid #eaecf0; font-weight:700; }
      .toc-subitem { margin-right:22px; font-weight:500; font-size:10.5pt; }
      .toc-label { white-space:nowrap; }
      .toc-dots { color:#d0d5dd; overflow:hidden; direction:ltr; flex:1; }
      .final-review { min-height:680px; border:1.5px solid #667085; padding:16px 19px; box-sizing:border-box; background:#fbfcfe; }
      .review-summary { margin:10px 0 12px; padding:10px 12px; border-right:5px solid #1d4ed8; background:#f8fafc; }
      .review-box { margin:9px 0; padding:8px 11px; border:1px solid #d0d5dd; background:white; break-inside:avoid-page; }
      .review-box h3,.review-checklist h3 { margin:0 0 6px; }
      .review-checklist { margin-top:11px; padding:9px 11px; border:1px dashed #98a2b3; break-inside:avoid-page; }
      .review-checklist div { margin:6px 0; }
    '''


def _find_target_page(doc: fitz.Document, text: str, start: int = 0) -> int | None:
    needle = str(text or "").strip()
    if not needle:
        return None
    for page_index in range(max(0, start), doc.page_count):
        try:
            if doc[page_index].search_for(needle):
                return page_index
        except Exception:
            continue
    return None


def add_pdf_navigation(data: bytes, pack: dict) -> bytes:
    """Add PDF outline/bookmarks and internal GoTo links without changing scientific content."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        index_page = _find_target_page(doc, "فهرس الملزمة")
        if index_page is None:
            return data

        outline: list[list] = [[1, str(pack.get("title") or "ملزمة الدرس"), 1]]
        seen_targets: set[tuple[int, str]] = set()
        for item in navigation_items(pack):
            target_page = _find_target_page(doc, item.target, start=index_page + 1)
            if target_page is None:
                continue
            target_key = (target_page, item.target)
            if target_key not in seen_targets:
                outline.append([item.level, item.label, target_page + 1])
                seen_targets.add(target_key)

            rects = doc[index_page].search_for(item.label)
            for rect in rects:
                try:
                    doc[index_page].insert_link(
                        {
                            "kind": fitz.LINK_GOTO,
                            "from": rect,
                            "page": target_page,
                            "to": fitz.Point(0, 0),
                        }
                    )
                except Exception:
                    continue

        if len(outline) > 1:
            doc.set_toc(outline)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
