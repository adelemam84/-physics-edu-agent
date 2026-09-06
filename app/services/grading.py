from __future__ import annotations

import math
import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUM_EXPR = re.compile(
    r"""(?ix)
    [-+]?\d+(?:\.\d+)?\s*[x*]\s*10\s*(?:\^\s*)?[-+]?\d+
    |[-+]?\d+(?:\.\d+)?\s*/\s*(?:π|pi|\d+(?:\.\d+)?)
    |[-+]?(?:\d+(?:\.\d+)?)?\s*√\s*2
    |[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?
    """
)

def _ascii(value: str | None) -> str:
    if value is None:
        return ""
    return (
        str(value).translate(_DIGITS)
        .replace("−", "-").replace("–", "-").replace("—", "-")
        .replace("×", "x")
    )

def normalize_answer(value: str | None) -> str:
    v = _ascii(value).strip().casefold()
    v = v.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    v = v.replace("ى", "ي").replace("ة", "ه")
    v = re.sub(r"[\s،,.;:()\[\]{}]+", "", v)
    return v

def _parse_number(token: str) -> float | None:
    t = _ascii(token).strip().lower().replace(" ", "")
    try:
        m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)x10\^?([-+]?\d+)", t)
        if m:
            return float(m.group(1)) * (10 ** int(m.group(2)))
        m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)/(π|pi|\d+(?:\.\d+)?)", t)
        if m:
            den = math.pi if m.group(2) in {"π", "pi"} else float(m.group(2))
            return float(m.group(1)) / den
        m = re.fullmatch(r"([-+]?\d*(?:\.\d+)?)√2", t)
        if m:
            coeff = m.group(1)
            if coeff in {"", "+", "-"}:
                coeff = coeff + "1" if coeff in {"+", "-"} else "1"
            return float(coeff) * math.sqrt(2)
        return float(t)
    except (TypeError, ValueError, ZeroDivisionError):
        return None

def extract_numeric_values(value: str | None) -> list[float]:
    text = _ascii(value)
    out: list[float] = []
    for m in _NUM_EXPR.finditer(text):
        v = _parse_number(m.group(0))
        if v is not None and math.isfinite(v):
            out.append(v)
    return out

def _close(a: float, b: float, rel_tol: float = 0.02, abs_tol: float = 1e-9) -> bool:
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= max(abs_tol, rel_tol * scale)

def _numeric_contains(expected: list[float], actual: list[float]) -> bool:
    if not expected or not actual:
        return False
    used: set[int] = set()
    for e in expected:
        match = None
        for i, a in enumerate(actual):
            if i in used:
                continue
            if _close(e, a):
                match = i
                break
        if match is None:
            return False
        used.add(match)
    return True

def _required_text_anchors(accepted: str) -> list[str]:
    a = normalize_answer(accepted)
    anchors = []
    for token in (
        "يمين", "يسار", "اعلي", "اسفل", "عكس", "مععقارب",
        "تجاذب", "تنافر", "لاتنبعث", "ينبعث", "مفتوح", "مغلق"
    ):
        if token in a:
            anchors.append(token)
    return anchors

def _grade_single(student_answer: str | None, accepted_answer: str) -> bool:
    s_norm = normalize_answer(student_answer)
    a_norm = normalize_answer(accepted_answer)
    if not a_norm:
        return False
    if s_norm == a_norm:
        return True
    # Natural short textual answers are accepted when one normalized form clearly contains the other.
    if len(s_norm) >= 4 and (s_norm in a_norm or a_norm in s_norm):
        return True

    expected = extract_numeric_values(accepted_answer)
    actual = extract_numeric_values(student_answer)
    if expected and _numeric_contains(expected, actual):
        # Preserve qualitative meaning when the source answer includes a direction/state.
        for anchor in _required_text_anchors(accepted_answer):
            if anchor not in s_norm:
                return False
        return True
    return False

def grade_answer(student_answer: str | None, accepted_answer: str | None) -> bool | None:
    if not accepted_answer or not str(accepted_answer).strip():
        return None
    alternatives = [x.strip() for x in re.split(r"\s*\|\s*", str(accepted_answer)) if x.strip()]
    return any(_grade_single(student_answer, option) for option in alternatives)

def grade_exact(student_answer: str | None, accepted_answer: str | None) -> bool | None:
    # Backward-compatible entrypoint used by older modules.
    return grade_answer(student_answer, accepted_answer)
