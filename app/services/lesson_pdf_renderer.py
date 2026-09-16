from __future__ import annotations

import html
import io
import os

import fitz

from .science_notation_presentation import notation_html


MODE_LABELS = {
    'teacher_notes': 'مذكرة مدرس',
    'student_simple': 'شرح مبسط للطالب',
    'quick_revision': 'مراجعة سريعة',
}

PDF_THEMES = {
    'classic_academic': {'label':'Classic Academic','accent':'#344054','soft':'#f8fafc','cover':'#ffffff','summary':'#f2f4f7','border':'#d0d5dd'},
    'modern_classroom': {'label':'Modern Classroom','accent':'#175cd3','soft':'#eff8ff','cover':'#f5faff','summary':'#eef4ff','border':'#b2ccff'},
    'exam_revision': {'label':'Exam Revision','accent':'#7a2e0e','soft':'#fff7ed','cover':'#fffbeb','summary':'#fef3c7','border':'#fed7aa'},
    'student_handout': {'label':'Student Handout','accent':'#1d4ed8','soft':'#f8fbff','cover':'#ffffff','summary':'#f8fafc','border':'#cbd5e1'},
}

DEFAULT_THEME = os.getenv('LESSON_STUDIO_PDF_THEME', 'classic_academic').strip() or 'classic_academic'
BRAND_NAME = os.getenv('LESSON_STUDIO_BRAND_NAME', 'Science Education Platform').strip() or 'Science Education Platform'
BRAND_TAGLINE = os.getenv('LESSON_STUDIO_BRAND_TAGLINE', 'Smart Science Lesson Studio').strip() or 'Smart Science Lesson Studio'

PDF_PRESETS = {
    'a4': {'width': 595.0, 'height': 842.0, 'margin_x': 40.0, 'margin_y': 40.0, 'font_scale': 1.0},
    'mobile': {'width': 360.0, 'height': 640.0, 'margin_x': 24.0, 'margin_y': 24.0, 'font_scale': 1.08},
}


def _esc(value) -> str:
    return html.escape(str(value or ''))


def _callout_role(heading: str) -> str:
    text = (heading or '').strip().lower()
    mapping = [
        ('law', ('قانون', 'قاعدة', 'law', 'rule')),
        ('definition', ('تعريف', 'مفهوم', 'definition', 'concept')),
        ('example', ('مثال', 'تطبيق', 'example', 'application')),
        ('warning', ('تنبيه', 'ملحوظة', 'ملاحظة', 'خطأ شائع', 'warning', 'note')),
        ('experiment', ('تجربة', 'نشاط', 'experiment', 'activity')),
        ('practice', ('تدريبات', 'اختبر نفسك', 'أسئلة', 'practice', 'questions')),
        ('revision', ('مراجعة في دقيقة', 'خلاصة الحصة', 'revision', 'recap')),
    ]
    for role, words in mapping:
        if any(w in text for w in words):
            return role
    return 'normal'


def _section_html(section: dict, *, anchor_id: str = '') -> str:
    refs = section.get('source_refs') or []
    source_html = ''
    if refs:
        source_html = '<div class="source">المصدر: ' + '، '.join(_esc(x) for x in refs) + '</div>'
    body = _esc(section.get('body')).replace('\n', '<br>')
    heading = str(section.get('heading') or '')
    role = _callout_role(heading)
    cls = 'section-block' if role == 'normal' else f'section-block callout callout-{role}'
    anchor = f' id="{_esc(anchor_id)}"' if anchor_id else ''
    return f'<section class="{cls}"><h2{anchor}>{_esc(heading)}</h2><p>{body}</p>{source_html}</section>'


def _list_block(title: str, values: list, *, css_class: str = '') -> str:
    if not values:
        return ''
    items = ''.join(f'<li>{_esc(x)}</li>' for x in values)
    extra = f' {css_class}' if css_class else ''
    return f'<section class="list-block{extra}"><h2>{_esc(title)}</h2><ul>{items}</ul></section>'



def _lesson_map_html(structured: dict) -> str:
    sections = [x for x in (structured.get('sections') or []) if isinstance(x, dict)]
    if not sections:
        return ''
    items = ''.join(
        f'<li><span class="map-num">{i}</span><span>{_esc(section.get("heading") or f"فكرة {i}")}</span></li>'
        for i, section in enumerate(sections, 1)
    )
    return (
        '<section class="lesson-map"><h2>خريطة الدرس</h2>'
        '<p class="map-intro">امشِ مع الدرس بالترتيب التالي، ثم ارجع للتدريبات في النهاية.</p>'
        '<ol>' + items + '</ol></section>'
    )


def _key_terms_html(items: list[dict], *, anchor_id: str = 'key-terms') -> str:
    cards = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        refs = item.get('source_refs') or []
        source_html = ''
        if refs:
            source_html = '<div class="source">المصدر: ' + '، '.join(_esc(x) for x in refs) + '</div>'
        cards.append(
            '<div class="term-card">'
            f'<div class="term">{_esc(item.get("term"))}</div>'
            f'<div class="definition">{_esc(item.get("definition"))}</div>'
            f'{source_html}</div>'
        )
    if not cards:
        return ''
    return (
        f'<section class="key-terms"><h2 id="{_esc(anchor_id)}">المفاهيم والمصطلحات الأساسية</h2>'
        '<div class="term-grid">' + ''.join(cards) + '</div></section>'
    )


def _student_notes_html() -> str:
    lines = ''.join('<div class="note-line"></div>' for _ in range(6))
    return (
        '<section class="student-notes"><h2>مساحة ملاحظاتي</h2>'
        '<p>اكتب هنا نقطة تحتاج مراجعتها، سؤالًا للمدرس، أو ملحوظة تساعدك على التذكر.</p>'
        + lines + '</section>'
    )


def _equations_html(items: list[dict], *, anchor_id: str = 'equations') -> str:
    if not items:
        return ''
    rows = []
    for x in items:
        rows.append(
            '<div class="equation">'
            f'<div class="eq-label">{_esc(x.get("label"))}</div>'
            f'<div class="eq-expression" dir="ltr"><bdi dir="ltr">{notation_html(str(x.get("expression") or ""), str((x.get("notation") or {}).get("kind") or "plain_text"))}</bdi></div>'
            f'<div class="eq-notes">{_esc(x.get("notes"))}</div>'
            '</div>'
        )
    return f'<section class="equation-section"><h2 id="{_esc(anchor_id)}">القوانين والمعادلات</h2>' + ''.join(rows) + '</section>'


def _diagrams_html(items: list[dict], *, anchor_id: str = 'diagrams') -> str:
    if not items:
        return ''
    rows = []
    for x in items:
        engine = x.get('diagram_engine') or {}
        labels = '، '.join(_esc(v) for v in (x.get('scientific_labels') or []))
        status = 'رسم برمجي جاهز' if engine.get('svg') and not engine.get('review_required') else 'تمت مراجعته/يتطلب اعتمادًا قبل النسخة النهائية'
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
    return f'<section class="diagram-section"><h2 id="{_esc(anchor_id)}">الرسومات التوضيحية</h2>' + ''.join(rows) + '</section>'


def _toc_entries(structured: dict) -> list[tuple[str, str]]:
    sections = list(structured.get('sections') or [])
    entries = [
        (f'section-{i}', str(section.get('heading') or f'قسم {i}'))
        for i, section in enumerate(sections, 1)
    ]
    if structured.get('key_terms'):
        entries.append(('key-terms', 'المفاهيم والمصطلحات الأساسية'))
    if structured.get('equations_or_rules'):
        entries.append(('equations', 'القوانين والمعادلات'))
    if structured.get('diagram_specs'):
        entries.append(('diagrams', 'الرسومات التوضيحية'))
    entries.append(('summary', 'الملخص'))
    return entries


def _toc_html(structured: dict, page_map: dict[str, int] | None = None) -> str:
    sections = list(structured.get('sections') or [])
    if len(sections) < 4:
        return ''
    page_map = page_map or {}
    rows = []
    for anchor, label in _toc_entries(structured):
        page = page_map.get(anchor)
        page_html = f'<span class="toc-page">{page}</span>' if page else '<span class="toc-page">—</span>'
        rows.append(
            f'<li><a href="#{_esc(anchor)}"><span class="toc-label">{_esc(label)}</span>{page_html}</a></li>'
        )
    return '<section class="toc"><h2>المحتويات</h2><ol>' + ''.join(rows) + '</ol></section>'


def lesson_html(structured: dict, *, mode: str | None = None, theme: str = DEFAULT_THEME, page_map: dict[str, int] | None = None) -> str:
    title = _esc(structured.get('title') or 'درس علوم')
    grade = _esc(structured.get('grade_label') or '')
    subject = _esc(structured.get('subject') or '')
    output_mode = mode or str(structured.get('mode') or 'teacher_notes')
    mode_label = MODE_LABELS.get(output_mode, output_mode)
    if theme not in PDF_THEMES:
        raise ValueError('Unsupported PDF theme')
    toc = _toc_html(structured, page_map)
    objectives = _list_block('أهداف الحصة', structured.get('learning_objectives') or [], css_class='objectives')
    lesson_map = _lesson_map_html(structured)
    key_terms = _key_terms_html(structured.get('key_terms') or [])
    sections = ''.join(_section_html(x, anchor_id=f'section-{i}') for i, x in enumerate(structured.get('sections') or [], 1) if isinstance(x, dict))
    equations = _equations_html(structured.get('equations_or_rules') or [])
    diagrams = _diagrams_html(structured.get('diagram_specs') or [])
    warnings = _list_block('ملاحظات للمدرس', structured.get('teacher_warnings') or [], css_class='teacher-notes') if output_mode == 'teacher_notes' else ''
    uncertain = _list_block('عناصر تحتاج مراجعة', structured.get('uncertain_items') or [], css_class='review-items') if output_mode == 'teacher_notes' else ''
    student_notes = _student_notes_html() if output_mode == 'student_simple' else ''
    summary = _esc(structured.get('summary') or '')
    cover_kind = 'ملزمة الطالب للحصة' if output_mode == 'student_simple' else _esc(mode_label)
    identity = (
        '<div class="student-identity"><span>اسم الطالب: ........................................</span>'
        '<span>التاريخ: ........ / ........ / ........</span></div>'
        if output_mode == 'student_simple' else ''
    )
    footer_text = (
        'ملزمة الطالب — شرح وتدريبات مبنية على مصدر الدرس المعتمد.'
        if output_mode == 'student_simple'
        else 'نسخة تعليمية مُنشأة من مصدر المدرس — المحتوى العلمي لا يُعدّل تلقائيًا.'
    )
    return f'''<article class="mode-{_esc(output_mode)}" dir="rtl" lang="ar">
      <header class="cover"><div class="brand">{_esc(BRAND_NAME)}</div><div class="eyebrow">{cover_kind}</div><h1>{title}</h1>
      <div class="meta">{subject} {('· ' + grade) if grade else ''}</div>{identity}
      <div class="cover-rule"></div></header>
      {lesson_map}{toc}{objectives}{key_terms}{sections}{equations}{diagrams}{warnings}{uncertain}
      <section class="summary"><h2 id="summary">خلاصة الحصة</h2><p>{summary}</p></section>
      {student_notes}
      <footer>{footer_text}</footer>
    </article>'''


def lesson_css(mode: str | None = None, *, preset: str = 'a4', theme: str = DEFAULT_THEME) -> str:
    if preset not in PDF_PRESETS:
        raise ValueError('Unsupported PDF preset')
    if theme not in PDF_THEMES:
        raise ValueError('Unsupported PDF theme')
    palette = PDF_THEMES[theme]
    compact = mode == 'quick_revision'
    scale = PDF_PRESETS[preset]['font_scale']
    base = (10.8 if compact else 12.0) * scale
    h1 = (22.0 if compact else 24.0) * scale
    h2 = 15.5 * scale
    h3 = 13.0 * scale
    eq = 15.0 * scale
    line_height = 1.62 if compact else (1.72 if preset == 'mobile' else 1.75)
    return f'''
      body {{ font-family: sans-serif; font-size:{base:.2f}pt; line-height:{line_height}; color:#172033; }}
      article {{ direction:rtl; }}
      .cover {{ padding:14px 0 18px; margin-bottom:16px; }}
      .cover-rule {{ height:3px; background:#344054; margin-top:14px; }}
      .eyebrow {{ font-weight:700; letter-spacing:.2px; }}
      .eyebrow,.meta,.source,.labels,.diagram-status,footer {{ color:#667085; font-size:{9.0 * scale:.2f}pt; }}
      h1 {{ font-size:{h1:.2f}pt; margin:4px 0 8px; line-height:1.25; }}
      h2 {{ font-size:{h2:.2f}pt; margin:17px 0 8px; border-bottom:1px solid #d0d5dd; padding-bottom:5px; }}
      h3 {{ font-size:{h3:.2f}pt; margin:5px 0; }}
      p {{ margin:5px 0 10px; }}
      ul,ol {{ margin:5px 18px 10px 0; }}
      .toc,.objectives {{ background:#f8fafc; border:1px solid #e4e7ec; padding:9px 12px; margin-bottom:14px; page-break-inside:avoid; }}
      .section-block {{ margin:6px 0 12px; }}
      .callout {{ border:1px solid #d0d5dd; border-right-width:5px; border-radius:8px; padding:6px 12px 9px; margin:12px 0; page-break-inside:avoid; }}
      .callout h2 {{ margin-top:5px; }}
      .callout-law {{ border-right-color:#175cd3; background:#f5faff; }}
      .callout-definition {{ border-right-color:#039855; background:#f6fef9; }}
      .callout-example {{ border-right-color:#7f56d9; background:#f9f5ff; }}
      .callout-warning {{ border-right-color:#f79009; background:#fffaeb; }}
      .callout-experiment {{ border-right-color:#0891b2; background:#ecfeff; }}
      .equation-section {{ page-break-inside:auto; }}
      .equation {{ border:1px solid #b2ccff; border-radius:8px; padding:10px; margin:8px 0; background:#f5f8ff; page-break-inside:avoid; }}
      .eq-expression {{ font-size:{eq:.2f}pt; text-align:center; padding:8px; font-weight:700; }}
      .eq-label {{ font-weight:700; }} .eq-notes {{ color:#475467; }}
      .diagram-card {{ border:1px solid #d0d5dd; padding:10px; margin:10px 0; border-radius:8px; page-break-inside:avoid; }}
      .svgbox {{ margin:8px auto; text-align:center; }} .svgbox svg {{ max-width:100%; height:auto; }}
      .teacher-notes {{ background:#fffaeb; border:1px solid #fedf89; padding:8px 12px; }}
      .review-items {{ background:#fef3f2; border:1px solid #fecdca; padding:8px 12px; }}
      .summary {{ background:#f2f4f7; border-right:5px solid #475467; padding:10px 14px; page-break-inside:avoid; }}
      .mode-student_simple .source {{ display:none; }}
      .mode-quick_revision .section-block {{ margin-bottom:7px; }}
      .mode-quick_revision .diagram-card {{ padding:7px; }}
      footer {{ margin-top:20px; border-top:1px solid #d0d5dd; padding-top:8px; }}
    '''


def _stamp_pages(data: bytes, *, preset: str, title: str = '', theme: str = DEFAULT_THEME) -> bytes:
    doc = fitz.open(stream=data, filetype='pdf')
    total = doc.page_count
    cfg = PDF_PRESETS[preset]
    font_size = 7.5 if preset == 'mobile' else 8.5
    header = f'{BRAND_NAME} · {title or BRAND_TAGLINE}'[:64]
    for i, page in enumerate(doc, 1):
        page.insert_text((cfg['margin_x'], 15), header, fontsize=font_size, color=(0.4, 0.4, 0.4))
        label = f'{i} / {total}'
        page.insert_text((page.rect.width - cfg['margin_x'] - 28, page.rect.height - 12), label, fontsize=font_size, color=(0.4, 0.4, 0.4))
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


def _page_map_from_positions(positions) -> dict[str, int]:
    result: dict[str, int] = {}
    wanted = set()
    for position in positions or []:
        anchor = getattr(position, 'id', None)
        if anchor and (getattr(position, 'open_close', 0) & 1):
            wanted.add(anchor)
            page_num = int(getattr(position, 'page_num', 0) or 0)
            if page_num > 0:
                result[anchor] = page_num
    return result


def _render_stabilized_pdf(structured: dict, *, preset: str, theme: str, mode: str) -> bytes:
    cfg = PDF_PRESETS[preset]
    media = fitz.Rect(0, 0, cfg['width'], cfg['height'])
    content = fitz.Rect(
        media.x0 + cfg['margin_x'], media.y0 + cfg['margin_y'],
        media.x1 - cfg['margin_x'], media.y1 - cfg['margin_y'],
    )

    def rectfn(rect_num, filled):
        if rect_num > 300:
            raise RuntimeError('Lesson PDF exceeded safe page limit')
        return media, content, None

    def contentfn(positions):
        page_map = _page_map_from_positions(positions)
        return lesson_html(structured, mode=mode, theme=theme, page_map=page_map)

    output = io.BytesIO()
    writer = fitz.DocumentWriter(output)
    try:
        fitz.Story.write_stabilized(
            writer,
            contentfn,
            rectfn,
            user_css=lesson_css(mode, preset=preset, theme=theme),
            em=11,
            add_header_ids=False,
        )
    finally:
        writer.close()
    data = output.getvalue()
    if not data.startswith(b'%PDF'):
        raise RuntimeError('Invalid stabilized PDF render output')
    return data


def render_lesson_pdf(structured: dict, *, preset: str = 'a4', theme: str = DEFAULT_THEME) -> bytes:
    """Render a stabilized multi-page lesson PDF with real TOC page mapping."""
    if preset not in PDF_PRESETS:
        raise ValueError('Unsupported PDF preset')
    if theme not in PDF_THEMES:
        raise ValueError('Unsupported PDF theme')
    mode = str(structured.get('mode') or 'teacher_notes')
    data = _render_stabilized_pdf(structured, preset=preset, theme=theme, mode=mode)
    data = _stamp_pages(data, preset=preset, title=str(structured.get('title') or ''), theme=theme)
    if not data.startswith(b'%PDF'):
        raise RuntimeError('Invalid stamped PDF output')
    return data
