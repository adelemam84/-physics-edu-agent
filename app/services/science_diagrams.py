from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import cos, pi, sin
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
    'cycle',
    'food_chain',
    'anatomy_block',
    'atom_shell',
    'ray_diagram',
}

REVIEW_BY_DEFAULT = {
    'comparison',
    'apparatus',
    'food_chain',
    'anatomy_block',
    'atom_shell',
    'ray_diagram',
}


def validate_spec(spec: DiagramSpec) -> dict:
    issues: list[str] = []
    if spec.kind not in SUPPORTED_KINDS:
        issues.append('unsupported_kind')
    if not spec.title.strip():
        issues.append('missing_title')
    if len(spec.labels) > 12:
        issues.append('too_many_labels')
    review_required = bool(issues) or spec.kind in REVIEW_BY_DEFAULT
    return {
        'valid': not issues,
        'issues': issues,
        'deterministic': spec.kind in SUPPORTED_KINDS,
        'review_required': review_required,
        'review_reason': 'scientific_relationship_requires_teacher_check' if spec.kind in REVIEW_BY_DEFAULT else None,
    }


def _svg_start(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.box{fill:#fff;stroke:#344054;stroke-width:2}'
        '.line{stroke:#344054;stroke-width:2;fill:none}.muted{fill:#667085}.axis{stroke:#101828;stroke-width:2}'
        '.node{fill:#fff;stroke:#475467;stroke-width:2}.soft{fill:#f2f4f7;stroke:#98a2b3;stroke-width:1.5}</style>'
    )


def _end() -> str:
    return '</svg>'


def _arrow(parts: list[str], x1: float, y1: float, x2: float, y2: float) -> None:
    parts.append(f'<line class="line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    angle = __import__('math').atan2(y2-y1, x2-x1)
    size = 10
    a1 = angle + pi * 0.82
    a2 = angle - pi * 0.82
    p1 = (x2 + size*cos(a1), y2 + size*sin(a1))
    p2 = (x2 + size*cos(a2), y2 + size*sin(a2))
    parts.append(f'<path d="M {p1[0]} {p1[1]} L {x2} {y2} L {p2[0]} {p2[1]}" class="line"/>')


def render_process(spec: DiagramSpec) -> str:
    labels = spec.labels or ('الخطوة 1', 'الخطوة 2', 'الخطوة 3')
    width = 760
    height = 170
    box_w = 165
    gap = 22
    count = min(len(labels), 4)
    total = count*box_w + max(0, count-1)*gap
    x0 = max(20, (width-total)/2)
    y = 58
    parts = [_svg_start(width, height, spec.title), f'<text x="25" y="28" font-size="18" font-weight="700">{escape(spec.title)}</text>']
    for i, label in enumerate(labels[:4]):
        x = x0 + i * (box_w + gap)
        parts.append(f'<rect class="box" x="{x}" y="{y}" rx="12" width="{box_w}" height="62"/>')
        parts.append(f'<text x="{x + box_w/2}" y="{y+37}" text-anchor="middle" font-size="14">{escape(label)}</text>')
        if i < count - 1:
            _arrow(parts, x+box_w, y+31, x+box_w+gap-4, y+31)
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
    _arrow(parts, 90, 110, 410, 110)
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
    _arrow(parts, 75, 275, 455, 275)
    _arrow(parts, 75, 275, 75, 60)
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
    parts.append('<path d="M110 80 H260 M380 80 H520 V200 H110 V80" class="line"/>')
    parts.append('<line class="line" x1="280" y1="58" x2="280" y2="102"/>')
    parts.append('<line class="line" x1="320" y1="68" x2="320" y2="92"/>')
    parts.append('<line class="line" x1="260" y1="80" x2="280" y2="80"/>')
    parts.append('<line class="line" x1="320" y1="80" x2="380" y2="80"/>')
    parts.append('<path d="M205 200 l12 -14 16 28 16 -28 16 28 16 -28 12 14" class="line"/>')
    parts.append(f'<text x="300" y="48" text-anchor="middle" font-size="14">{escape(battery)}</text>')
    parts.append(f'<text x="250" y="238" text-anchor="middle" font-size="14">{escape(load)}</text>')
    parts.append(_end())
    return ''.join(parts)


def render_cycle(spec: DiagramSpec) -> str:
    labels = spec.labels or ('مرحلة 1', 'مرحلة 2', 'مرحلة 3', 'مرحلة 4')
    labels = labels[:6]
    width, height = 560, 430
    cx, cy, radius = 280, 225, 135
    parts = [_svg_start(width, height, spec.title), f'<text x="280" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(spec.title)}</text>']
    coords = []
    for i, label in enumerate(labels):
        ang = -pi/2 + (2*pi*i/len(labels))
        x, y = cx+radius*cos(ang), cy+radius*sin(ang)
        coords.append((x,y))
        parts.append(f'<circle class="node" cx="{x}" cy="{y}" r="52"/>')
        parts.append(f'<text x="{x}" y="{y+5}" text-anchor="middle" font-size="13">{escape(label)}</text>')
    for i, (x1,y1) in enumerate(coords):
        x2,y2 = coords[(i+1)%len(coords)]
        dx,dy=x2-x1,y2-y1
        length=(dx*dx+dy*dy)**0.5 or 1
        _arrow(parts,x1+dx/length*56,y1+dy/length*56,x2-dx/length*56,y2-dy/length*56)
    parts.append(_end())
    return ''.join(parts)


def render_food_chain(spec: DiagramSpec) -> str:
    shell = DiagramSpec('process', spec.title, spec.labels, spec.description, spec.subject)
    return render_process(shell)


def render_anatomy_block(spec: DiagramSpec) -> str:
    labels = spec.labels or ('جزء 1', 'جزء 2', 'جزء 3')
    width, height = 620, 360
    parts=[_svg_start(width,height,spec.title),f'<text x="310" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(spec.title)}</text>']
    parts.append('<ellipse class="soft" cx="310" cy="185" rx="100" ry="135"/>')
    ys=[95,185,275]
    for i,label in enumerate(labels[:3]):
        y=ys[i]
        parts.append(f'<rect class="box" x="420" y="{y-24}" width="160" height="48" rx="9"/>')
        parts.append(f'<text x="500" y="{y+5}" text-anchor="middle" font-size="13">{escape(label)}</text>')
        parts.append(f'<line class="line" x1="410" y1="{y}" x2="350" y2="{y}"/>')
    parts.append(_end())
    return ''.join(parts)


def render_atom_shell(spec: DiagramSpec) -> str:
    labels = spec.labels or ('المستوى الأول', 'المستوى الثاني')
    width,height=520,360
    cx,cy=260,190
    parts=[_svg_start(width,height,spec.title),f'<text x="260" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(spec.title)}</text>']
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="24" fill="#d0d5dd" stroke="#344054"/>')
    for i,label in enumerate(labels[:4],1):
        r=45+i*30
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" class="line"/>')
        parts.append(f'<text x="{cx+r+8}" y="{cy-4}" font-size="12">{escape(label)}</text>')
    parts.append(_end())
    return ''.join(parts)


def render_ray_diagram(spec: DiagramSpec) -> str:
    labels=list(spec.labels)
    left=labels[0] if labels else 'الجسم'
    center=labels[1] if len(labels)>1 else 'العنصر البصري'
    right=labels[2] if len(labels)>2 else 'الصورة/الاتجاه'
    width,height=680,300
    parts=[_svg_start(width,height,spec.title),f'<text x="340" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(spec.title)}</text>']
    parts.append('<line class="axis" x1="55" y1="175" x2="625" y2="175"/>')
    parts.append('<line class="line" x1="340" y1="65" x2="340" y2="250"/>')
    parts.append(f'<text x="110" y="160" font-size="13">{escape(left)}</text>')
    parts.append(f'<text x="340" y="55" text-anchor="middle" font-size="13">{escape(center)}</text>')
    parts.append(f'<text x="530" y="160" font-size="13">{escape(right)}</text>')
    parts.append('<text class="muted" x="340" y="285" text-anchor="middle" font-size="11">المسارات الدقيقة تُراجع قبل الاعتماد</text>')
    parts.append(_end())
    return ''.join(parts)


def render(spec: DiagramSpec) -> dict:
    check = validate_spec(spec)
    if not check['valid']:
        return {'svg': None, **check}
    renderer = {
        'process': render_process,
        'classification': render_classification,
        'vector': render_vector,
        'graph_axes': render_graph_axes,
        'simple_circuit': render_simple_circuit,
        'cycle': render_cycle,
        'food_chain': render_food_chain,
        'anatomy_block': render_anatomy_block,
        'atom_shell': render_atom_shell,
        'ray_diagram': render_ray_diagram,
    }.get(spec.kind)
    if renderer:
        svg = renderer(spec)
    elif spec.kind in {'comparison', 'apparatus'}:
        shell = DiagramSpec('process', spec.title, spec.labels, spec.description, spec.subject)
        svg = render_process(shell)
    else:
        svg = None
    return {'svg': svg, **check}


def supported_kinds() -> Iterable[str]:
    return tuple(sorted(SUPPORTED_KINDS))
