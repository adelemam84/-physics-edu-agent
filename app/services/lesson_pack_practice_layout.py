from __future__ import annotations

import copy
import html


DIFFICULTY_ORDER = ("easy", "medium", "hard")
DIFFICULTY_LABELS = {
    "easy": "سهل",
    "medium": "متوسط",
    "hard": "متقدم",
}
DIFFICULTY_HEADINGS = {
    "easy": ("المستوى الأول", "ثبّت الأساسيات وابدأ بهدوء."),
    "medium": ("المستوى الثاني", "طبّق الفكرة والقانون في مواقف متنوعة."),
    "hard": ("المستوى المتقدم", "اختبر قدرتك على الربط والتحليل."),
}


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _lines(value) -> str:
    return _esc(value).replace("\n", "<br>")


def _difficulty(question: dict) -> str:
    value = str(question.get("difficulty") or "medium").strip().lower()
    return value if value in DIFFICULTY_ORDER else "medium"


def practice_layout_settings(pack: dict) -> dict:
    raw = pack.get("practice_layout") if isinstance(pack.get("practice_layout"), dict) else {}
    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    default_count = min(6, len(questions))
    requested = raw.get("self_test_count", default_count)
    try:
        count = int(requested)
    except (TypeError, ValueError):
        count = default_count
    if questions:
        count = max(1, min(12, count, len(questions)))
    else:
        count = 0
    return {
        "self_test_count": count,
        "show_answer_sheet": bool(raw.get("show_answer_sheet", True)),
        "group_by_difficulty": bool(raw.get("group_by_difficulty", True)),
    }


def prepare_practice_pack(pack: dict) -> dict:
    """Return a rendering copy with stable easy→medium→hard practice order.

    This changes presentation only. It never creates a question, changes scientific
    content, or alters question-bank policy flags on the persisted Lesson Pack.
    """
    out = copy.deepcopy(pack)
    questions = [x for x in (out.get("practice_questions") or []) if isinstance(x, dict)]
    indexed = list(enumerate(questions))
    indexed.sort(key=lambda pair: (DIFFICULTY_ORDER.index(_difficulty(pair[1])), pair[0]))
    out["practice_questions"] = [question for _, question in indexed]
    out["practice_layout"] = {
        **(out.get("practice_layout") if isinstance(out.get("practice_layout"), dict) else {}),
        **practice_layout_settings(out),
    }
    return out


def practice_groups(pack: dict) -> list[dict]:
    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    groups: list[dict] = []
    for difficulty in DIFFICULTY_ORDER:
        items = [question for question in questions if _difficulty(question) == difficulty]
        if items:
            heading, guidance = DIFFICULTY_HEADINGS[difficulty]
            groups.append(
                {
                    "difficulty": difficulty,
                    "label": DIFFICULTY_LABELS[difficulty],
                    "heading": heading,
                    "guidance": guidance,
                    "items": items,
                }
            )
    return groups


def self_test_items(pack: dict) -> list[dict]:
    """Choose a deterministic balanced mini-test from the existing practice only."""
    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    if not questions:
        return []
    count = practice_layout_settings(pack)["self_test_count"]
    positions = {id(question): index for index, question in enumerate(questions, 1)}
    queues = {
        difficulty: [q for q in questions if _difficulty(q) == difficulty]
        for difficulty in DIFFICULTY_ORDER
    }
    selected: list[dict] = []
    while len(selected) < count:
        progressed = False
        for difficulty in DIFFICULTY_ORDER:
            queue = queues[difficulty]
            if not queue:
                continue
            question = queue.pop(0)
            selected.append(
                {
                    "self_test_no": len(selected) + 1,
                    "practice_no": positions[id(question)],
                    "difficulty": difficulty,
                    "difficulty_label": DIFFICULTY_LABELS[difficulty],
                    "question": question,
                }
            )
            progressed = True
            if len(selected) >= count:
                break
        if not progressed:
            break
    return selected


def _option_html(question: dict) -> str:
    options = [str(x) for x in (question.get("options") or [])]
    if not options:
        return (
            '<div class="self-test-solution-space">'
            '<div></div><div></div><div></div>'
            '</div>'
        )
    letters = ["أ", "ب", "ج", "د", "هـ", "و"]
    rows = "".join(
        f'<li><span>{letters[index] if index < len(letters) else index + 1}</span>{_esc(option)}</li>'
        for index, option in enumerate(options)
    )
    return f'<ol class="self-test-options">{rows}</ol>'


def self_test_html(pack: dict) -> str:
    items = self_test_items(pack)
    if not items:
        return ""
    cards = "".join(
        '<div class="self-test-question">'
        f'<div class="self-test-head"><span>سؤال {item["self_test_no"]}</span>'
        f'<small>من تدريب {item["practice_no"]}</small></div>'
        f'<div class="self-test-prompt">{_lines(item["question"].get("prompt"))}</div>'
        f'{_option_html(item["question"])}'
        '</div>'
        for item in items
    )
    return (
        '<section class="self-test page-break-before">'
        '<div class="self-test-kicker">اختبار مصغر من نفس تدريبات الدرس</div>'
        '<h2>اختبر نفسك</h2>'
        '<p class="self-test-note">حل من غير الرجوع للشرح. هذه الأسئلة مختارة من تدريبات الملزمة نفسها؛ '
        'لا تُنشئ بنك أسئلة رسميًا ولا تُعامل كأسئلة منقولة من المصدر.</p>'
        + cards
        + '</section>'
    )


def answer_sheet_html(pack: dict) -> str:
    settings = practice_layout_settings(pack)
    items = self_test_items(pack)
    if not items or not settings["show_answer_sheet"]:
        return ""
    rows: list[str] = []
    letters = ["أ", "ب", "ج", "د", "هـ", "و"]
    for item in items:
        question = item["question"]
        options = [str(x) for x in (question.get("options") or [])]
        if options:
            bubbles = " ".join(
                f'<span class="answer-bubble">○ {letters[index] if index < len(letters) else index + 1}</span>'
                for index, _ in enumerate(options)
            )
            response = f'<div class="answer-choice-row">{bubbles}</div>'
        else:
            response = '<div class="answer-write-lines"><div></div><div></div><div></div></div>'
        rows.append(
            '<div class="answer-sheet-row">'
            f'<div class="answer-sheet-number">{item["self_test_no"]}</div>'
            f'<div class="answer-sheet-response">{response}</div>'
            '</div>'
        )
    return (
        '<section class="answer-sheet page-break-before">'
        '<div class="answer-sheet-top"><div><b>ورقة إجابة الطالب</b><br><small>اختبر نفسك</small></div>'
        '<div class="answer-sheet-score">الدرجة: ........ / ........</div></div>'
        '<div class="answer-sheet-identity">الاسم: .................................................... '
        '&nbsp;&nbsp;&nbsp; التاريخ: ........ / ........ / ........</div>'
        + "".join(rows)
        + '</section>'
    )


def teacher_self_test_key_html(pack: dict) -> str:
    items = self_test_items(pack)
    if not items:
        return ""
    cards: list[str] = []
    for item in items:
        question = item["question"]
        refs = "، ".join(str(x) for x in (question.get("source_refs") or []))
        cards.append(
            '<div class="teacher-key-card">'
            f'<h3>سؤال {item["self_test_no"]} <small>— تدريب {item["practice_no"]}</small></h3>'
            f'<div><b>الإجابة:</b> {_lines(question.get("answer"))}</div>'
            f'<div><b>التفسير:</b> {_lines(question.get("explanation"))}</div>'
            + (f'<div class="teacher-key-source"><b>المصدر:</b> {_esc(refs)}</div>' if refs else "")
            + '</div>'
        )
    return (
        '<article dir="rtl" lang="ar" class="teacher-self-test-key">'
        '<div class="teacher-key-kicker">نسخة المدرس فقط</div>'
        '<h1>نموذج إجابة «اختبر نفسك»</h1>'
        '<p>هذا النموذج يخص الاختبار المصغر في نسخة الطالب. الأسئلة تدريبية مولدة من محتوى الدرس '
        'ولا تُنقل إلى بنك الأسئلة الرسمي.</p>'
        + "".join(cards)
        + '<footer>نموذج إجابة للمدرس — Lesson Pack Studio</footer>'
        '</article>'
    )


def decorate_practice_html(document_html: str, pack: dict) -> str:
    """Add difficulty dividers plus student self-test/answer sheet to rendered HTML."""
    out = str(document_html)
    settings = practice_layout_settings(pack)
    questions = [x for x in (pack.get("practice_questions") or []) if isinstance(x, dict)]
    if not questions:
        return out
    if settings["group_by_difficulty"]:
        card = '<div class="question-card">'
        search_from = out.find('<section class="practice page-break-before">')
        if search_from >= 0:
            last_difficulty = None
            for question in questions:
                pos = out.find(card, search_from)
                if pos < 0:
                    break
                difficulty = _difficulty(question)
                if difficulty != last_difficulty:
                    heading, guidance = DIFFICULTY_HEADINGS[difficulty]
                    divider = (
                        f'<div class="difficulty-divider difficulty-{difficulty}">'
                        f'<span>{_esc(heading)}</span><b>{_esc(DIFFICULTY_LABELS[difficulty])}</b>'
                        f'<small>{_esc(guidance)}</small></div>'
                    )
                    out = out[:pos] + divider + out[pos:]
                    pos += len(divider)
                search_from = pos + len(card)
                last_difficulty = difficulty

    practice_start = out.find('<section class="practice page-break-before">')
    if practice_start < 0:
        return out
    practice_end = out.find('</section>', practice_start)
    if practice_end < 0:
        return out
    practice_end += len('</section>')
    appendix = self_test_html(pack) + answer_sheet_html(pack)
    return out[:practice_end] + appendix + out[practice_end:]


def practice_suite_css() -> str:
    return '''
      .difficulty-divider { margin:16px 0 8px; padding:8px 11px; border:1px solid #d0d5dd; border-right:5px solid #667085; background:#f8fafc; break-inside:avoid-page; }
      .difficulty-divider span { display:block; color:#667085; font-size:8.5pt; font-weight:700; }
      .difficulty-divider b { display:inline-block; margin-left:8px; font-size:12pt; }
      .difficulty-divider small { color:#475467; }
      .difficulty-easy { border-right-color:#027a48; }
      .difficulty-medium { border-right-color:#b54708; }
      .difficulty-hard { border-right-color:#b42318; }
      .self-test,.answer-sheet { margin:0; }
      .self-test-kicker,.teacher-key-kicker { color:#667085; font-size:9pt; font-weight:700; }
      .self-test h2 { font-size:20pt; margin:7px 0 8px; }
      .self-test-note { padding:8px 10px; border:1px solid #d0d5dd; background:#f8fafc; font-size:9pt; }
      .self-test-question { margin:10px 0; padding:10px 12px; border:1px solid #98a2b3; break-inside:avoid-page; }
      .self-test-head { display:flex; justify-content:space-between; gap:8px; font-weight:700; }
      .self-test-head small { color:#667085; font-weight:400; }
      .self-test-prompt { margin:7px 0; }
      .self-test-options { list-style:none; margin:5px 0; padding:0; }
      .self-test-options li { margin:5px 0; }
      .self-test-options li span { display:inline-block; min-width:20px; height:20px; text-align:center; margin-left:7px; border:1px solid #98a2b3; border-radius:50%; }
      .self-test-solution-space div,.answer-write-lines div { height:22px; border-bottom:1px dotted #98a2b3; }
      .answer-sheet { border:1.5px solid #667085; padding:15px 18px; box-sizing:border-box; min-height:680px; }
      .answer-sheet-top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; border-bottom:1px solid #d0d5dd; padding-bottom:10px; }
      .answer-sheet-score { border:1px solid #98a2b3; padding:7px 10px; }
      .answer-sheet-identity { margin:12px 0; padding:8px 0; border-bottom:1px solid #eaecf0; }
      .answer-sheet-row { display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-bottom:1px solid #eaecf0; break-inside:avoid-page; }
      .answer-sheet-number { width:28px; height:28px; border:1px solid #667085; border-radius:50%; text-align:center; line-height:28px; font-weight:700; flex:0 0 auto; }
      .answer-sheet-response { flex:1; }
      .answer-bubble { display:inline-block; margin:2px 8px 2px 0; direction:rtl; }
      .teacher-self-test-key { direction:rtl; font-family:sans-serif; font-size:11pt; line-height:1.6; color:#172033; }
      .teacher-self-test-key h1 { font-size:22pt; }
      .teacher-key-card { margin:10px 0; padding:10px 12px; border:1px solid #98a2b3; break-inside:avoid-page; }
      .teacher-key-card h3 { margin:0 0 7px; }
      .teacher-key-card small,.teacher-key-source { color:#667085; }
    '''
