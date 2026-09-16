from __future__ import annotations

import html
import io
import os

import fitz

from .science_notation_presentation import notation_html


BRAND_NAME = os.getenv("LESSON_STUDIO_BRAND_NAME", "Science Education Platform").strip() or "Science Education Platform"
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
MARGIN_X = 38.0
MARGIN_Y = 42.0


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _lines(value) -> str:
    return _esc(value).replace("\n", "<br>")


def _objectives_html(pack: dict) -> str:
    items = [str(x) for x in (pack.get("learning_objectives") or []) if str(x).strip()]
    if not items:
        return ""
    rows = "".join(f"<li>{_esc(item)}</li>" for item in items)
    return f'<section class="panel objectives"><h2>بعد مذاكرة الدرس ستستطيع أن</h2><ul>{rows}</ul></section>'


def _lesson_map_html(pack: dict) -> str:
    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    if not sections:
        return ""
    rows = "".join(
        f'<li><span class="step">{i}</span><span>{_esc(section.get("heading") or f"فكرة {i}")}</span></li>'
        for i, section in enumerate(sections, 1)
    )
    return (
        '<section class="lesson-map"><h2>خريطة مذاكرة الحصة</h2>'
        '<p>ذاكر الأفكار بالترتيب، ثم راجع القوانين والأمثلة قبل حل تدريبات آخر الملزمة.</p>'
        f'<ol>{rows}</ol></section>'
    )


def _key_terms_html(pack: dict) -> str:
    items = [x for x in (pack.get("key_terms") or []) if isinstance(x, dict)]
    if not items:
        return ""
    cards = "".join(
        '<div class="term-card">'
        f'<div class="term">{_esc(item.get("term"))}</div>'
        f'<div class="definition">{_esc(item.get("definition"))}</div>'
        '</div>'
        for item in items
    )
    return f'<section class="terms"><h2>مصطلحات لازم تكون واضحة</h2><div class="term-grid">{cards}</div></section>'


def _sections_html(pack: dict) -> str:
    sections = [x for x in (pack.get("sections") or []) if isinstance(x, dict)]
    rows: list[str] = []
    for index, section in enumerate(sections, 1):
        body = _lines(section.get("body"))
        key_point = str(section.get("key_point") or "").strip()
        check = str(section.get("check_yourself") or "").strip()
        extras = ""
        if key_point:
            extras += f'<div class="remember"><b>ثبّت الفكرة:</b> {_esc(key_point)}</div>'
        if check:
            extras += f'<div class="self-check"><b>اختبر فهمك:</b> {_esc(check)}<div class="answer-line"></div></div>'
        rows.append(
            '<section class="lesson-section">'
            f'<div class="section-number">{index}</div>'
            f'<h2>{_esc(section.get("heading") or f"فكرة {index}")}</h2>'
            f'<div class="lesson-body">{body}</div>{extras}'
            '</section>'
        )
    return "".join(rows)


def _equations_html(pack: dict) -> str:
    items = [x for x in (pack.get("equations_or_rules") or []) if isinstance(x, dict)]
    if not items:
        return ""
    rows: list[str] = []
    for item in items:
        notation = item.get("notation") or {}
        expression = notation_html(
            str(item.get("expression") or ""),
            str(notation.get("kind") or "plain_text"),
        )
        rows.append(
            '<div class="law-card">'
            f'<div class="law-title">{_esc(item.get("label") or "القانون")}</div>'
            f'<div class="law-expression" dir="ltr"><bdi dir="ltr">{expression}</bdi></div>'
            f'<div class="law-note">{_lines(item.get("notes"))}</div>'
            '</div>'
        )
    return '<section class="laws"><h2>القوانين والعلاقات المهمة</h2>' + "".join(rows) + '</section>'


def _diagrams_html(pack: dict) -> str:
    items = [x for x in (pack.get("diagram_specs") or []) if isinstance(x, dict)]
    cards: list[str] = []
    for item in items:
        engine = item.get("diagram_engine") or {}
        svg = engine.get("svg") or ""
        if not svg or engine.get("review_required"):
            continue
        labels = "، ".join(_esc(x) for x in (item.get("scientific_labels") or []))
        cards.append(
            '<div class="diagram-card">'
            f'<h3>{_esc(item.get("title") or "رسم توضيحي")}</h3>'
            f'<div class="diagram-description">{_lines(item.get("description"))}</div>'
            f'<div class="svgbox">{svg}</div>'
            f'<div class="diagram-labels">{labels}</div>'
            '<div class="visual-note">رسم توضيحي تعليمي مبني على بيانات المصدر.</div>'
            '</div>'
        )
    if not cards:
        return ""
    return '<section class="diagrams"><h2>افهمها بالرسم</h2>' + "".join(cards) + '</section>'


def _worked_examples_html(pack: dict) -> str:
    items = [x for x in (pack.get("worked_examples") or []) if isinstance(x, dict)]
    if not items:
        return ""
    cards: list[str] = []
    for index, item in enumerate(items, 1):
        steps = "".join(
            f'<li>{_esc(step)}</li>' for step in (item.get("solution_steps") or []) if str(step).strip()
        )
        answer = str(item.get("answer") or "").strip()
        answer_html = f'<div class="final-answer"><b>الإجابة النهائية:</b> {_esc(answer)}</div>' if answer else ""
        cards.append(
            '<div class="example-card">'
            f'<div class="example-tag">مثال محلول {index}</div>'
            f'<h3>{_esc(item.get("title") or "تطبيق")}</h3>'
            f'<div class="problem"><b>المطلوب:</b> {_lines(item.get("problem"))}</div>'
            f'<ol class="solution-steps">{steps}</ol>{answer_html}'
            '</div>'
        )
    return '<section class="examples"><h2>أمثلة محلولة خطوة بخطوة</h2>' + "".join(cards) + '</section>'


def _mistakes_html(pack: dict) -> str:
    items = [x for x in (pack.get("common_mistakes") or []) if isinstance(x, dict)]
    if not items:
        return ""
    rows = "".join(f'<li>{_esc(item.get("text"))}</li>' for item in items if str(item.get("text") or "").strip())
    if not rows:
        return ""
    return f'<section class="panel mistakes"><h2>خلي بالك من الأخطاء دي</h2><ul>{rows}</ul></section>'


def _practice_html(pack: dict) -> str:
    items = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    if not items:
        return ""
    letters = ["أ", "ب", "ج", "د", "هـ", "و"]
    cards: list[str] = []
    difficulty_map = {"easy": "سهل", "medium": "متوسط", "hard": "متقدم"}
    for index, item in enumerate(items, 1):
        options = [str(x) for x in (item.get("options") or [])]
        option_html = ""
        if options:
            option_html = '<ol class="options">' + "".join(
                f'<li><span class="choice">{letters[i] if i < len(letters) else i + 1}</span>{_esc(option)}</li>'
                for i, option in enumerate(options)
            ) + '</ol>'
        else:
            option_html = '<div class="solution-space"><span>مساحة الحل</span><div></div><div></div><div></div></div>'
        level = difficulty_map.get(str(item.get("difficulty") or "medium").lower(), "متوسط")
        cards.append(
            '<div class="question-card">'
            f'<div class="question-head"><span>سؤال {index}</span><span class="level">{level}</span></div>'
            f'<div class="question-text">{_lines(item.get("prompt"))}</div>{option_html}'
            '</div>'
        )
    return (
        '<section class="practice page-break-before"><h2>تدريبات الدرس</h2>'
        '<p class="practice-note">تدريبات إضافية مولدة من محتوى الدرس للممارسة، وليست أسئلة منقولة حرفيًا من المصدر.</p>'
        + "".join(cards) + '</section>'
    )


def _revision_html(pack: dict) -> str:
    items = [x for x in (pack.get("quick_revision") or []) if isinstance(x, dict)]
    rows = "".join(f'<li>{_esc(item.get("text"))}</li>' for item in items if str(item.get("text") or "").strip())
    summary = str(pack.get("summary") or "").strip()
    if not rows and not summary:
        return ""
    summary_html = f'<div class="final-summary"><b>الخلاصة:</b> {_esc(summary)}</div>' if summary else ""
    return f'<section class="revision"><h2>مراجعة سريعة قبل ما تقفل الملزمة</h2><ul>{rows}</ul>{summary_html}</section>'


def _notes_html() -> str:
    return (
        '<section class="notes"><h2>ملاحظاتي وأسئلتي</h2>'
        '<div class="note-line"></div><div class="note-line"></div><div class="note-line"></div>'
        '<div class="note-line"></div><div class="note-line"></div></section>'
    )


def _document_html(pack: dict) -> str:
    title = _esc(pack.get("title") or "ملزمة الدرس")
    subject = _esc(pack.get("subject") or "")
    grade = _esc(pack.get("grade_label") or "")
    return f'''<article dir="rtl" lang="ar">
      <header class="cover">
        <div class="brand">{_esc(BRAND_NAME)}</div>
        <div class="cover-badge">ملزمة الطالب للحصة</div>
        <h1>{title}</h1>
        <div class="meta">{subject}{(' · ' + grade) if grade else ''}</div>
        <div class="identity"><span>اسم الطالب: ...................................................</span><span>التاريخ: ........ / ........ / ........</span></div>
        <div class="cover-copy">شرح منظم للمذاكرة + قوانين ورسومات + أمثلة محلولة + تدريبات متدرجة</div>
      </header>
      {_lesson_map_html(pack)}
      {_objectives_html(pack)}
      {_key_terms_html(pack)}
      {_sections_html(pack)}
      {_equations_html(pack)}
      {_diagrams_html(pack)}
      {_worked_examples_html(pack)}
      {_mistakes_html(pack)}
      {_practice_html(pack)}
      {_revision_html(pack)}
      {_notes_html()}
      <footer>ملزمة مذاكرة للطالب مبنية على محتوى الدرس المرفوع والمعتمد قبل التصدير.</footer>
    </article>'''


def _css() -> str:
    return '''
      body { font-family:sans-serif; font-size:11.7pt; line-height:1.72; color:#172033; }
      article { direction:rtl; }
      h1 { font-size:27pt; line-height:1.2; margin:8px 0 10px; }
      h2 { font-size:15.5pt; margin:17px 0 8px; padding-bottom:5px; border-bottom:1.4px solid #98a2b3; }
      h3 { font-size:13pt; margin:5px 0 7px; }
      p { margin:5px 0 9px; }
      ul,ol { margin:6px 20px 10px 0; }
      .cover { border:1.5px solid #344054; border-right:7px solid #1d4ed8; padding:18px 20px; margin:0 0 16px; background:#ffffff; page-break-inside:avoid; }
      .brand { color:#344054; font-size:9pt; font-weight:700; }
      .cover-badge { display:inline-block; margin-top:8px; padding:3px 8px; border:1px solid #98a2b3; border-radius:12px; font-size:9pt; font-weight:700; }
      .meta { color:#475467; font-weight:700; }
      .identity { margin-top:16px; border-top:1px solid #d0d5dd; padding-top:10px; font-size:10pt; }
      .identity span { display:block; margin:4px 0; }
      .cover-copy { margin-top:10px; color:#475467; font-size:9.4pt; }
      .lesson-map,.panel,.terms,.laws,.diagrams,.examples,.practice,.revision,.notes { margin:14px 0; }
      .lesson-map { background:#f8fafc; border:1px solid #d0d5dd; padding:10px 13px; page-break-inside:avoid; }
      .lesson-map ol { list-style:none; margin-right:0; padding-right:0; }
      .lesson-map li { margin:5px 0; }
      .step { display:inline-block; min-width:20px; height:20px; text-align:center; margin-left:7px; border:1px solid #667085; border-radius:50%; font-size:9pt; font-weight:700; }
      .panel { border:1px solid #d0d5dd; padding:9px 13px; background:#fbfcfe; page-break-inside:avoid; }
      .term-card { border-right:4px solid #667085; padding:7px 10px; margin:7px 0; background:#f8fafc; page-break-inside:avoid; }
      .term { font-weight:700; }
      .definition { color:#344054; }
      .lesson-section { position:relative; margin:13px 0 17px; padding:8px 12px 11px; border:1px solid #d0d5dd; border-radius:6px; }
      .section-number { float:right; margin:-2px 0 0 8px; min-width:24px; height:24px; text-align:center; border-radius:50%; background:#344054; color:white; font-weight:700; }
      .lesson-section h2 { margin-top:2px; border-bottom:0; padding-bottom:2px; }
      .lesson-body { margin-top:5px; }
      .remember { margin:10px 0 4px; padding:7px 10px; background:#f8fafc; border-right:4px solid #1d4ed8; }
      .self-check { margin:9px 0 3px; padding:7px 10px; border:1px dashed #98a2b3; }
      .answer-line { border-bottom:1px dotted #98a2b3; height:18px; }
      .law-card { border:1.5px solid #98a2b3; padding:10px 12px; margin:9px 0; text-align:center; page-break-inside:avoid; }
      .law-title { text-align:right; font-weight:700; }
      .law-expression { font-size:17pt; font-weight:700; padding:8px; }
      .law-note { text-align:right; color:#475467; }
      .diagram-card { border:1px solid #d0d5dd; padding:10px; margin:10px 0; page-break-inside:avoid; }
      .svgbox { text-align:center; margin:8px auto; }
      .svgbox svg { max-width:100%; height:auto; }
      .diagram-labels,.visual-note { color:#667085; font-size:8.8pt; }
      .example-card { border:1px solid #98a2b3; border-right:5px solid #475467; padding:10px 13px; margin:11px 0; page-break-inside:avoid; }
      .example-tag { font-size:9pt; font-weight:700; color:#475467; }
      .problem { margin:7px 0; }
      .solution-steps { margin-top:7px; }
      .final-answer { margin-top:8px; padding:7px 9px; background:#f2f4f7; border:1px solid #d0d5dd; }
      .mistakes { border-right:5px solid #b54708; }
      .page-break-before { page-break-before:always; }
      .practice-note { color:#667085; font-size:9pt; }
      .question-card { margin:11px 0 16px; padding:9px 11px; border:1px solid #d0d5dd; page-break-inside:avoid; }
      .question-head { display:flex; justify-content:space-between; font-weight:700; font-size:9.5pt; }
      .level { color:#475467; }
      .question-text { margin:7px 0; font-weight:600; }
      .options { list-style:none; padding:0; margin:6px 0; }
      .options li { margin:5px 0; }
      .choice { display:inline-block; width:20px; font-weight:700; }
      .solution-space { color:#667085; font-size:9pt; margin-top:8px; }
      .solution-space div { height:22px; border-bottom:1px dotted #98a2b3; }
      .revision { border:1.5px solid #667085; padding:10px 13px; background:#f8fafc; page-break-inside:avoid; }
      .final-summary { margin-top:9px; border-top:1px solid #d0d5dd; padding-top:8px; }
      .notes { page-break-inside:avoid; }
      .note-line { height:24px; border-bottom:1px dotted #98a2b3; }
      footer { margin-top:20px; border-top:1px solid #d0d5dd; padding-top:7px; color:#667085; font-size:8.5pt; }
    '''


def _render(pack: dict) -> bytes:
    media = fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)
    content = fitz.Rect(MARGIN_X, MARGIN_Y, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - MARGIN_Y)

    def rectfn(rect_num, filled):
        if rect_num > 200:
            raise RuntimeError("Student handout exceeded safe page limit")
        return media, content, None

    def contentfn(_positions):
        return _document_html(pack)

    out = io.BytesIO()
    writer = fitz.DocumentWriter(out)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=_css(),
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = out.getvalue()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("Invalid Student Handout PDF")
    return data


def _stamp(data: bytes, title: str) -> bytes:
    doc = fitz.open(stream=data, filetype="pdf")
    total = doc.page_count
    header = f"{BRAND_NAME} · {title}"[:72]
    for index, page in enumerate(doc, 1):
        page.insert_text((MARGIN_X, 16), header, fontsize=8, color=(0.38, 0.38, 0.38))
        page.insert_text((PAGE_WIDTH - MARGIN_X - 30, PAGE_HEIGHT - 13), f"{index} / {total}", fontsize=8, color=(0.38, 0.38, 0.38))
    result = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return result


def render_student_handout_pdf(pack: dict) -> bytes:
    """Render the final A4 study handout used by students after the lesson."""
    data = _render(pack)
    return _stamp(data, str(pack.get("title") or "ملزمة الدرس"))
