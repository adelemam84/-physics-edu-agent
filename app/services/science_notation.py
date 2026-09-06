from __future__ import annotations

from dataclasses import dataclass, asdict
import re


@dataclass(frozen=True)
class NotationItem:
    raw: str
    kind: str
    confidence: float
    requires_review: bool

    def as_dict(self) -> dict:
        return asdict(self)


_CHEM_ARROW = re.compile(r'(?:→|⇌|->|<->)')
_EQUATION = re.compile(r'^[^\n]{1,120}=[^\n]{1,120}$')
_UNIT_HINT = re.compile(r'\b(?:V|A|Ω|W|J|N|Pa|Hz|T|C|mol|kg|m/s|m/s²|cm|mm|nm)\b')
# Allows a stoichiometric coefficient before a formula (e.g. 2H2, 3NaCl)
# while still extracting the chemical formula itself for reaction detection.
_CHEM_TOKEN = re.compile(r'(?<![A-Za-z])(?:\d+\s*)?(?:[A-Z][a-z]?\d*){1,8}(?![a-z])')


def classify_notation(raw: str) -> NotationItem:
    """Classify notation for presentation without normalizing or rewriting it."""
    text = (raw or '').strip()
    if not text:
        return NotationItem(raw=text, kind='empty', confidence=1.0, requires_review=False)
    if '[غير واضح]' in text or '???' in text:
        return NotationItem(raw=text, kind='uncertain', confidence=0.2, requires_review=True)
    if _CHEM_ARROW.search(text) and len(_CHEM_TOKEN.findall(text)) >= 2:
        return NotationItem(raw=text, kind='chemical_equation', confidence=0.95, requires_review=False)
    if _EQUATION.match(text) and (re.search(r'[A-Za-zΑ-Ωα-ω]', text) or _UNIT_HINT.search(text)):
        return NotationItem(raw=text, kind='physics_or_math_equation', confidence=0.92, requires_review=False)
    if _UNIT_HINT.search(text) and re.search(r'\d', text):
        return NotationItem(raw=text, kind='quantity_with_unit', confidence=0.88, requires_review=False)
    if len(_CHEM_TOKEN.findall(text)) >= 1 and re.search(r'\d', text):
        return NotationItem(raw=text, kind='chemical_formula_candidate', confidence=0.75, requires_review=True)
    return NotationItem(raw=text, kind='plain_text', confidence=0.8, requires_review=False)


def analyze_notation_items(items: list[dict]) -> dict:
    analyzed = []
    for item in items or []:
        expression = str(item.get('expression') or '')
        classification = classify_notation(expression)
        analyzed.append({**item, 'notation': classification.as_dict()})
    return {
        'items': analyzed,
        'review_required': sum(1 for x in analyzed if x['notation']['requires_review']),
        'policy': 'classification_only_no_semantic_rewrite',
    }
