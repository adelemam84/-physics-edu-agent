from __future__ import annotations

import html
import io

import fitz


MODE_LABELS = {
    'teacher_notes': 'مذكرة مدرس',
    'student_simple': 'شرح مبسط للطالب',
    'quick_revision': 'مراجعة سريعة',
}


def _esc(value) -> str:
    return html.escape(str(value or ''))


def _section_html(section: dict) -> str:
    refs = section.get('source_refs') or []
    source_html = ''
    if refs:
        source_html = '<div class="source">المصدر: ' + '، '.join(_esc(x) for x in refs) + '</div>'
    body = _esc(section.get('body')).replace('\n', '<br>')
    return f'<section><h2>{_esc(section.get("heading"))}</h2><p>{body}</p>{source_html}</section>'


def _list_block(title: str, values: list) -> str:
    if not values:
        return ''
    items = ''.join(f'<li>{_esc(x)}</li>' for x in values)
    return f'<section><h2>{_esc(title)}</h2><ul>{items}</ul></section>'


def _equations_html(items: list[dict]) -> str:
    if not items:
        return ''
    rows = []
    for x in items:
        rows.append(
            '<div class="equation">'
            f'<div class="eq-label">{_esc(x.get("label"))}</div>'
            f'<div class="eq-expression" dir="ltr">{_esc(x.get("expression"))}</div>'
            f'<div class="eq-notes">{_esc(x.get("notes"))}</div>'
            '</div>'
        )
    return '<section><h2>القوانين والمعادلات</h2>' + ''.join(rows) + '</section>'


def _diagrams_html(items: list[dict]) -> str:
    if not items:
        return ''
    rows = []
    for x in items:
        engine = x.get('diagram_engine') or {}
        labels = '، '.join(_esc(v) for v in (x.get('scientific_labels') or []))
        status = 'رسم برمجي جاهز' if engine.get('svg') and not engine.get('review_required') else 'يتطلب مراجعة/استكمال الرسم'
        svg = engine.get('svg') or ''
        svg_html = f'<div class="svgbox">{svg}</div>' if svg else ''
        rows.append(
            '<div class="diagram-card">'
            f'<h3>{_esc(x.get("title"))}</h3>'
            f'<p>{_esc(x.get("description"))}</p>'
            f'<div class="labels">{labels}</div>'
            f'<div class="diagram-status">{_esc(status)}</div>{svg_html}'
            '</div>'
        )
    return '<section><h2>الرسومات التوضيحية</h2>' + ''.join(rows) + '</section>'


def lesson_html(structured: dict, *, mode: str | None = None) -> str:
    title = _esc(structured.get('title') or 'درس علوم')
    grade = _esc(structured.get('grade_label') or '')
    subject = _esc(structured.get('subject') or '')
    output_mode = mode or str(structured.get('mode') or 'teacher_notes')
    mode_label = MODE_LABELS.get(output_mode, output_mode)
    objectives = _list_block('أهداف التعلم', structured.get('learning_objectives') or [])
    sections = ''.join(_section_html(x) for x in (structured.get('sections') or []))
    equations = _equations_html(structured.get('equations_or_rules') or [])
    diagrams = _diagrams_html(structured.get('diagram_specs') or [])
    warnings = _list_block('ملاحظات للمدرس', structured.get('teacher_warnings') or []) if output_mode == 'teacher_notes' else ''
    uncertain = _list_block('عناصر تحتاج مراجعة', structured.get('uncertain_items') or [])
    summary = _esc(structured.get('summary') or '')
    return f'''<article dir="rtl">
      <header class="cover"><div class="eyebrow">Smart Science Lesson Studio</div><h1>{title}</h1>
      <div class="meta">{subject} {('· ' + grade) if grade else ''} · {_esc(mode_label)}</div></header>
      {objectives}{sections}{equations}{diagrams}{warnings}{uncertain}
      <section class="summary"><h2>الملخص</h2><p>{summary}</p></section>
      <footer>نسخة تعليمية مُنشأة من مصدر المدرس — راجع المحتوى قبل التوزيع.</footer>
    </article>'''


def lesson_css(mode: str | None = None) -> str:
    compact = mode == 'quick_revision'
    font_size = '11pt' if compact else '12pt'
    return f'''
      @page {{ size: A4; }}
      body {{ font-family: sans-serif; font-size:{font_size}; line-height:1.75; color:#172033; }}
      article {{ direction:rtl; }}
      .cover {{ padding:18px 0 20px; border-bottom:2px solid #344054; margin-bottom:16px; }}
      .eyebrow,.meta,.source,.labels,.diagram-status,footer {{ color:#667085; font-size:9pt; }}
      h1 {{ font-size:24pt; margin:4px 0 8px; }}
      h2 {{ font-size:16pt; margin:18px 0 8px; border-bottom:1px solid #d0d5dd; padding-bottom:5px; }}
      h3 {{ font-size:13pt; margin:5px 0; }}
      p {{ margin:5px 0 10px; }}
      ul {{ margin:5px 18px 10px 0; }}
      .equation {{ border:1px solid #d0d5dd; border-radius:8px; padding:10px; margin:8px 0; page-break-inside:avoid; }}
      .eq-expression {{ font-size:15pt; text-align:center; padding:8px; }}
      .eq-label {{ font-weight:700; }} .eq-notes {{ color:#475467; }}
      .diagram-card {{ border:1px solid #d0d5dd; padding:10px; margin:10px 0; page-break-inside:avoid; }}
      .svgbox {{ margin:8px auto; text-align:center; }} .svgbox svg {{ max-width:100%; height:auto; }}
      .summary {{ background:#f2f4f7; padding:10px 14px; page-break-inside:avoid; }}
      footer {{ margin-top:20px; border-top:1px solid #d0d5dd; padding-top:8px; }}
    '''


def render_lesson_pdf(structured: dict) -> bytes:
    """Render a multi-page A4 PDF using PyMuPDF Story flow layout."""
    mode = str(structured.get('mode') or 'teacher_notes')
    story = fitz.Story(html=lesson_html(structured, mode=mode), user_css=lesson_css(mode), em=11)
    media = fitz.paper_rect('a4')
    content = fitz.Rect(media.x0 + 40, media.y0 + 40, media.x1 - 40, media.y1 - 42)
    output = io.BytesIO()
    writer = fitz.DocumentWriter(output)
    more = 1
    page_count = 0
    try:
        while more:
            page_count += 1
            if page_count > 200:
                raise RuntimeError('Lesson PDF exceeded safe page limit')
            device = writer.begin_page(media)
            more, _ = story.place(content)
            story.draw(device)
            writer.end_page()
    finally:
        writer.close()
    data = output.getvalue()
    if not data.startswith(b'%PDF'):
        raise RuntimeError('Invalid PDF render output')
    return data
