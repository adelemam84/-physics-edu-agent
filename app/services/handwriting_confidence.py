from __future__ import annotations

import re


UNCLEAR_MARKERS = ('[غير واضح]', '[unclear]', '???')
SCIENCE_RE = re.compile(r'[=<>±×÷→←⇌∑∆ΔθλμΩ]|\d|[A-Za-z]{1,3}\d|[A-Z][a-z]?\d*')


SUBJECT_PROFILES = {
    'physics': {
        'preferred_visuals': ['simple_circuit','resistor_network','series_parallel_circuit','graph_axes','vector','ray_diagram','magnetic_field','solenoid_field','apparatus'],
        'priority_review': ['numbers','units','equations','directions','graph_scales'],
        'pdf_sections': ['definitions','laws','worked_examples','diagrams','warnings','summary'],
    },
    'chemistry': {
        'preferred_visuals': ['molecule_bond','atom_shell','chemistry_lab_setup','process','classification','comparison'],
        'priority_review': ['coefficients','charges','subscripts','reaction_arrows','states_of_matter'],
        'pdf_sections': ['definitions','equations','reactions','experiments','diagrams','warnings','summary'],
    },
    'science': {
        'preferred_visuals': ['process','classification','cycle','food_chain','anatomy_block','graph_axes','apparatus','comparison'],
        'priority_review': ['labels','arrows','measurements','classification_relationships'],
        'pdf_sections': ['concepts','observations','experiments','diagrams','comparisons','summary'],
    },
}


def _line_score(base_score: float, conflict: dict | None, text: str) -> tuple[float, str, list[str]]:
    reasons: list[str] = []
    score = max(0.0, min(1.0, float(base_score or 0.0)))
    severity = str((conflict or {}).get('severity') or '')
    kind = str((conflict or {}).get('kind') or '')
    if severity == 'critical':
        score = min(score, 0.35)
        reasons.append(kind or 'critical_ocr_conflict')
    elif severity == 'review':
        score = min(score, 0.68)
        reasons.append(kind or 'ocr_difference')
    if any(marker.lower() in (text or '').lower() for marker in UNCLEAR_MARKERS):
        score = min(score, 0.2)
        reasons.append('unclear_source_marker')
    if SCIENCE_RE.search(text or '') and score < 0.95:
        reasons.append('science_sensitive_line')
    if score >= 0.95 and not reasons:
        band = 'green'
    elif score >= 0.72 and not any(r in {'unclear_source_marker','scientific_notation_conflict'} for r in reasons):
        band = 'yellow'
    else:
        band = 'red'
    return round(score, 4), band, reasons


def build_confidence_map(text: str, source_score: float, conflicts: list[dict] | None = None) -> dict:
    lines = (text or '').splitlines() or ['']
    conflict_by_line = {int(x.get('line_number') or 0): x for x in (conflicts or []) if int(x.get('line_number') or 0) > 0}
    zones = []
    for i, line in enumerate(lines, 1):
        score, band, reasons = _line_score(source_score, conflict_by_line.get(i), line)
        zones.append({
            'line_number': i,
            'text': line,
            'score': score,
            'band': band,
            'requires_review': band != 'green',
            'reasons': reasons,
        })
    return {
        'zones': zones,
        'summary': {
            'total_lines': len(zones),
            'green': sum(1 for x in zones if x['band'] == 'green'),
            'yellow': sum(1 for x in zones if x['band'] == 'yellow'),
            'red': sum(1 for x in zones if x['band'] == 'red'),
            'review_required': sum(1 for x in zones if x['requires_review']),
        },
        'policy': {
            'line_level_only': True,
            'no_text_rewrite': True,
            'science_sensitive_lines_are_conservative': True,
        },
    }


def subject_profile(subject: str) -> dict:
    key = (subject or '').strip().lower()
    return {'subject': key, **SUBJECT_PROFILES.get(key, SUBJECT_PROFILES['science'])}


def golden_page_contract() -> dict:
    return {
        'required_cases': [
            'arabic_handwriting_clean',
            'arabic_handwriting_shadowed',
            'physics_equation_with_units',
            'chemistry_reaction_with_subscripts_and_charge',
            'hand_drawn_scientific_diagram',
            'mixed_arabic_latin_numbers',
        ],
        'must_preserve': ['numbers','operators','units','coefficients','charges','subscripts','arrows','source_order'],
        'must_block_on': ['unreadable_scientific_value','equation_operator_conflict','unresolved_diagram_relationship'],
        'auto_publish': False,
    }
