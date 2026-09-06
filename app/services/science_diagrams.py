from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable


@dataclass(frozen=True)
class DiagramSpec:
    kind: str
    title: str
    labels: tuple[str, ...] = ()
    description: str = ''
    subject: str = 'science'


SUPPORTED_KINDS = {
    'process',
    'classification',
    'comparison',
    'vector',
    'graph_axes',
    'simple_circuit',
    'apparatus',
}


def validate_spec(spec: DiagramSpec) -> dict:
    issues: list[str] = []
    if spec.kind not in SUPPORTED_KINDS:
        issues.append('unsupported_kind')
    if not spec.title.strip():
        issues.append('missing_title')
    if len(spec.labels) > 12:
        issues.append('too_many_labels')
    return {
        'valid': not issues,
        'issues': issues,
        'deterministic': spec.kind in SUPPORTED_KINDS,
        'review_required': bool(issues),
    }


def _svg_start(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.box{fill:#fff;stroke:#344054;stroke-width:2}'
        '.line{stroke:#344054;stroke-width:2;fill:none}.muted{fill:#667085}.axis{stroke:#101828;stroke-width:2}</style>'
    )


def _end() -> str:
    return '</svg>'


def render_process(spec: DiagramSpec) -> str:
    labels = spec.labels or ('الخطوة 1', 'الخطوة 2', 'الخطوة 3')
    width = 760
    height = 170
    box_w = 180
    gap = 50
    x0 = 25
    y = 58
    parts = [_svg_start(width, height, spec.title), f'<text x="25" y="28" font-size="18" font-weight="700">{escape(spec.title)}</text>']
    for i, label in enumerate(labels[:4]):
        x = x0 + i * (box_w + gap)
        parts.append(f'<rect class="box" x="{x}" y="{y}" rx="12" width="{box_w}" height="62"/>')
        parts.append(f'<text x="{x + box_w/2}" y="{y+37}" text-anchor="middle" font-size="15">{escape(label)}</text>')
        if i < min(len(labels[:4]), 4) - 1:
            x1 = x + box_w
            x2 = x + box_w + gap - 8
            parts.append(f'<line class="line" x1="{x1}" y1="{y+31}" x2="{x2}" y2="{y+31}"/>')
            parts.append(f'<path d="M {x2-10} {y+23} L {x2} {y+31} L {x2-10} {y+39}" class="line"/>')
    parts.append(_end())
    return ''.join(parts)


def render_classification(spec: DiagramSpec) -> str:
    labels = spec.labels or ('فرع أ', 'فرع ب', 'فرع ج')
    width, height = 720, 260
    parts = [_svg_start(width, height, spec.title)]
    parts.append(f'<text x="360" y="32" text-anchor="middle" font-size="19" font-weight="700">{escape(spec.title)}</text>')
    parts.append('<rect class="box" x="270" y="55" width="180" height="55" rx="12"/>')
    parts.append(f'<text x="360" y="88" text-anchor="middle" font-size="15">{escape(spec.title)}</text>')
    n = min(len(labels), 4)
    positions = [110, 280, 450, 620][:n]
    for x, label in zip(positions, labels[:n]):
        parts.append(f'<line class="line" x1="360" y1="110" x2="{x}" y2="160"/>')
        parts.append(f'<rect class="box" x="{x-75}" y="160" width="150" height="55" rx="10"/>')
        parts.append(f'<text x="{x}" y="193" text-anchor="middle" font-size="14">{escape(label)}</text>')
    parts.append(_end())
    return ''.join(parts)


def render_vector(spec: DiagramSpec) -> str:
    label = spec.labels[0] if spec.labels else 'المتجه'
    width, height = 520, 180
    parts = [_svg_start(width, height, spec.title)]
    parts.append(f'<text x="20" y="30" font-size="18" font-weight="700">{escape(spec.title)}</text>')
    parts.append('<line class="line" x1="90" y1="110" x2="410" y2="110"/>')
    parts.append('<path d="M 392 96 L 410 110 L 392 124" class="line"/>')
    parts.append(f'<text x="250" y="90" text-anchor="middle" font-size="16">{escape(label)}</text>')
    parts.append('<circle cx="90" cy="110" r="5" fill="#344054"/>')
    parts.append(_end())
    return ''.join(parts)


def render_graph_axes(spec: DiagramSpec) -> str:
    x_label = spec.labels[0] if len(spec.labels) > 0 else 'x'
    y_label = spec.labels[1] if len(spec.labels) > 1 else 'y'
    width, height = 520, 330
    parts = [_svg_start(width, height, spec.title)]
    parts.append(f'<text x="20" y="30" font-size="18" font-weight="700">{escape(spec.title)}</text>')
    parts.append('<line class="axis" x1="75" y1="275" x2="455" y2="275"/>')
    parts.append('<line class="axis" x1="75" y1="275" x2="75" y2="60"/>')
    parts.append('<path d="M 442 266 L 455 275 L 442 284" class="line"/>')
    parts.append('<path d="M 66 73 L 75 60 L 84 73" class="line"/>')
    parts.append(f'<text x="455" y="305" text-anchor="end" font-size="15">{escape(x_label)}</text>')
    parts.append(f'<text x="55" y="65" text-anchor="end" font-size="15">{escape(y_label)}</text>')
    parts.append(_end())
    return ''.join(parts)


def render_simple_circuit(spec: DiagramSpec) -> str:
    labels = list(spec.labels)
    battery = labels[0] if labels else 'مصدر'
    load = labels[1] if len(labels) > 1 else 'مقاومة'
    width, height = 640, 260
    parts = [_svg_start(width, height, spec.title)]
    parts.append(f'<text x="20" y="30" font-size="18" font-weight="700">{escape(spec.title)}</text>')
    # closed rectangular loop
    parts.append('<path d="M110 80 H260 M380 80 H520 V200 H110 V80" class="line"/>')
    # battery symbol
    parts.append('<line class="line" x1="280" y1="58" x2="280" y2="102"/>')
    parts.append('<line class="line" x1="320" y1="68" x2="320" y2="92"/>')
    parts.append('<line class="line" x1="260" y1="80" x2="280" y2="80"/>')
    parts.append('<line class="line" x1="320" y1="80" x2="380" y2="80"/>')
    # resistor
    parts.append('<path d="M205 200 l12 -14 16 28 16 -28 16 28 16 -28 12 14" class="line"/>')
    parts.append(f'<text x="300" y="48" text-anchor="middle" font-size="14">{escape(battery)}</text>')
    parts.append(f'<text x="250" y="238" text-anchor="middle" font-size="14">{escape(load)}</text>')
    parts.append(_end())
    return ''.join(parts)


def render(spec: DiagramSpec) -> dict:
    check = validate_spec(spec)
    if not check['valid']:
        return {'svg': None, **check}
    if spec.kind == 'process':
        svg = render_process(spec)
    elif spec.kind == 'classification':
        svg = render_classification(spec)
    elif spec.kind == 'vector':
        svg = render_vector(spec)
    elif spec.kind == 'graph_axes':
        svg = render_graph_axes(spec)
    elif spec.kind == 'simple_circuit':
        svg = render_simple_circuit(spec)
    elif spec.kind in {'comparison', 'apparatus'}:
        # Placeholder deterministic shell: safe to render layout, but factual labels still require review.
        shell = DiagramSpec('process', spec.title, spec.labels, spec.description, spec.subject)
        svg = render_process(shell)
        check['review_required'] = True
    else:
        svg = None
    return {'svg': svg, **check}


def supported_kinds() -> Iterable[str]:
    return tuple(sorted(SUPPORTED_KINDS))
