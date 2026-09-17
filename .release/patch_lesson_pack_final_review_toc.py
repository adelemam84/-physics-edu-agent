from pathlib import Path

p = Path('app/services/lesson_pack_student_renderer.py')
s = p.read_text()
repls = [
    (
        'from .storage import get_bytes\n',
        'from .storage import get_bytes\nfrom .lesson_pack_pdf_navigation import add_pdf_navigation, final_review_html, navigation_css, navigation_index_html\n',
    ),
    (
        '      {_cover_html(pack)}\n      {_lesson_map_html(pack)}',
        '      {_cover_html(pack)}\n      {navigation_index_html(pack)}\n      {_lesson_map_html(pack)}',
    ),
    (
        '      {_revision_html(pack)}\n      {_notes_html()}',
        '      {_revision_html(pack)}\n      {final_review_html(pack)}\n      {_notes_html()}',
    ),
    (
        '            user_css=_css(),\n',
        '            user_css=_css() + navigation_css(),\n',
    ),
    (
        '    data = _render(pack)\n    return _stamp(data, str(pack.get("title") or "ملزمة الدرس"))\n',
        '    data = _render(pack)\n    data = add_pdf_navigation(data, pack)\n    return _stamp(data, str(pack.get("title") or "ملزمة الدرس"))\n',
    ),
]
for old, new in repls:
    if old not in s:
        raise SystemExit(f'Patch marker not found: {old[:80]!r}')
    s = s.replace(old, new, 1)
p.write_text(s)
