from __future__ import annotations

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import re


@dataclass(frozen=True)
class OCRConflict:
    line_number: int
    primary: str
    secondary: str
    similarity: float
    severity: str
    kind: str


@dataclass(frozen=True)
class OCRConsensusResult:
    text: str
    confidence_band: str
    score: float
    conflicts: tuple[OCRConflict, ...]
    requires_review: bool

    def as_dict(self) -> dict:
        return {
            'text': self.text,
            'confidence_band': self.confidence_band,
            'score': self.score,
            'conflicts': [asdict(x) for x in self.conflicts],
            'requires_review': self.requires_review,
        }


_SCIENCE_SYMBOL_RE = re.compile(r"[=<>±×÷→←⇌∑∆ΔθλμΩ]|\d|[A-Za-z]{1,3}\d|[A-Z][a-z]?\d*")
_EQUATION_MARK_RE = re.compile(r"[=→←⇌±×÷/]|")
_UNCLEAR_MARKERS = ('[غير واضح]', '[unclear]', '???')


def _normalize_line(value: str) -> str:
    value = value.replace('\u00a0', ' ').strip()
    value = re.sub(r'\s+', ' ', value)
    return value


def _science_sensitive(value: str) -> bool:
    return bool(_SCIENCE_SYMBOL_RE.search(value))


def _line_similarity(a: str, b: str) -> float:
    a = _normalize_line(a)
    b = _normalize_line(b)
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _looks_like_equation(value: str) -> bool:
    value = _normalize_line(value)
    return bool(re.search(r'[=→←⇌]', value)) and bool(re.search(r'[A-Za-z0-9Α-Ωα-ω]', value))


def _compact_science(value: str) -> str:
    return re.sub(r'\s+', '', _normalize_line(value))


def _severity(primary: str, secondary: str, similarity: float) -> tuple[str, str]:
    joined = f'{primary} {secondary}'.lower()
    if any(marker.lower() in joined for marker in _UNCLEAR_MARKERS):
        return 'critical', 'unclear_source'
    # Equations / reaction expressions are exact-content sensitive: changing an
    # operator, denominator, coefficient or arrow may change the scientific meaning.
    if (_looks_like_equation(primary) or _looks_like_equation(secondary)) and _compact_science(primary) != _compact_science(secondary):
        return 'critical', 'scientific_notation_conflict'
    if _science_sensitive(primary) or _science_sensitive(secondary):
        if similarity < 0.92:
            return 'critical', 'scientific_notation_conflict'
        if similarity < 0.97:
            return 'review', 'scientific_notation_minor_difference'
    if similarity < 0.72:
        return 'critical', 'text_conflict'
    if similarity < 0.90:
        return 'review', 'text_difference'
    return 'info', 'minor_formatting_difference'


def compare_ocr(primary: str, secondary: str) -> OCRConsensusResult:
    """Compare two OCR transcripts without inventing a merged scientific reading.

    The primary transcript remains authoritative in the returned text. The secondary
    transcript is used only to calculate review/conflict signals. This prevents a
    consensus layer from silently changing equations or scientific symbols.
    """
    p_lines = [_normalize_line(x) for x in (primary or '').splitlines()]
    s_lines = [_normalize_line(x) for x in (secondary or '').splitlines()]
    count = max(len(p_lines), len(s_lines))
    conflicts: list[OCRConflict] = []
    similarities: list[float] = []

    for i in range(count):
        p = p_lines[i] if i < len(p_lines) else ''
        s = s_lines[i] if i < len(s_lines) else ''
        sim = _line_similarity(p, s)
        similarities.append(sim)
        if p == s:
            continue
        severity, kind = _severity(p, s, sim)
        if severity != 'info':
            conflicts.append(OCRConflict(i + 1, p, s, round(sim, 4), severity, kind))

    score = round(sum(similarities) / len(similarities), 4) if similarities else 1.0
    has_critical = any(x.severity == 'critical' for x in conflicts)
    has_review = bool(conflicts)
    if has_critical or score < 0.82:
        band = 'red'
    elif has_review or score < 0.95:
        band = 'yellow'
    else:
        band = 'green'
    return OCRConsensusResult(
        text=primary or '',
        confidence_band=band,
        score=score,
        conflicts=tuple(conflicts),
        requires_review=(band != 'green'),
    )


def single_provider_result(text: str, confidence: float | None = None) -> OCRConsensusResult:
    """Return an explicit one-provider result; it can never claim dual verification."""
    if confidence is None:
        score = 0.80 if text and not any(x in text for x in _UNCLEAR_MARKERS) else 0.55
    else:
        score = max(0.0, min(1.0, float(confidence)))
    band = 'green' if score >= 0.95 else ('yellow' if score >= 0.75 else 'red')
    return OCRConsensusResult(
        text=text or '',
        confidence_band=band,
        score=round(score, 4),
        conflicts=(),
        requires_review=(band != 'green'),
    )
