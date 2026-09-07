from __future__ import annotations

import html
import re


_STATE = re.compile(r'\((aq|s|l|g)\)', re.I)
_EXPLICIT_EXP = re.compile(r'\^([+-]?\d+|[A-Za-zΑ-Ωα-ω]+)')
_CHEM_ELEMENT = re.compile(r'[A-Z][a-z]?')
_CHEM_FORMULA = re.compile(r'^(?:\d+\s*)?(?:[A-Z][a-z]?\d*)+(?:\((?:aq|s|l|g)\))?(?:\^?[0-9]*[+-])?$')


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _explicit_superscripts(text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in _EXPLICIT_EXP.finditer(text):
        parts.append(_esc(text[last:match.start()]))
        parts.append(f'<sup>{_esc(match.group(1))}</sup>')
        last = match.end()
    parts.append(_esc(text[last:]))
    return ''.join(parts)


def _chemical_token_html(token: str) -> str:
    """Typography only: convert explicitly present formula digits/charge/state to markup."""
    state_match = _STATE.search(token)
    state = state_match.group(0) if state_match else ''
    core = token[:state_match.start()] + token[state_match.end():] if state_match else token

    charge = ''
    charge_match = re.search(r'(\^?[0-9]*[+-])$', core)
    if charge_match:
        charge = charge_match.group(1)
        core = core[:charge_match.start()]

    prefix_match = re.match(r'^(\d+\s*)', core)
    prefix = prefix_match.group(1) if prefix_match else ''
    formula = core[prefix_match.end():] if prefix_match else core

    chunks: list[str] = [_esc(prefix)]
    pos = 0
    while pos < len(formula):
        element = _CHEM_ELEMENT.match(formula, pos)
        if not element:
            chunks.append(_esc(formula[pos:]))
            break
        symbol = element.group(0)
        chunks.append(_esc(symbol))
        pos = element.end()
        digits = re.match(r'\d+', formula[pos:])
        if digits:
            value = digits.group(0)
            chunks.append(f'<sub>{_esc(value)}</sub>')
            pos += len(value)

    if state:
        chunks.append(f'<span class="chem-state">{_esc(state)}</span>')
    if charge:
        shown = charge[1:] if charge.startswith('^') else charge
        chunks.append(f'<sup class="chem-charge">{_esc(shown)}</sup>')
    return ''.join(chunks)


def _chemical_expression_html(raw: str) -> str:
    # Preserve separators/arrows/operators verbatim while styling only safe formula tokens.
    token_re = re.compile(r'(?:\d+\s*)?(?:[A-Z][a-z]?\d*)+(?:\((?:aq|s|l|g)\))?(?:\^?[0-9]*[+-])?', re.I)
    out: list[str] = []
    last = 0
    for match in token_re.finditer(raw):
        candidate = match.group(0)
        # Case-insensitive regex can overmatch normal words; require strict chemical token.
        if not _CHEM_FORMULA.match(candidate):
            continue
        out.append(_esc(raw[last:match.start()]))
        out.append(_chemical_token_html(candidate))
        last = match.end()
    out.append(_esc(raw[last:]))
    return ''.join(out)


def notation_html(raw: str, kind: str) -> str:
    """Return presentation markup without altering or normalizing the underlying notation."""
    value = str(raw or '')
    if not value:
        return ''
    if kind in {'chemical_equation', 'chemical_formula_candidate'}:
        body = _chemical_expression_html(value)
    elif kind in {'physics_or_math_equation', 'quantity_with_unit'}:
        body = _explicit_superscripts(value)
    else:
        body = _esc(value)
    return f'<span class="scientific-notation" data-raw="{_esc(value)}">{body}</span>'


def presentation_contract() -> dict:
    return {
        'policy': 'presentation_only_preserve_raw',
        'chemical_subscripts': 'explicit_digits_only',
        'charges': 'explicit_suffix_only',
        'states': ['(s)', '(l)', '(g)', '(aq)'],
        'math_superscripts': 'explicit_caret_only',
        'semantic_rewrite': False,
    }
