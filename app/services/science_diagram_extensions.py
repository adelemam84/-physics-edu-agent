from __future__ import annotations

from html import escape
from math import cos, pi, sin


ADVANCED_KINDS = {'resistor_network', 'magnetic_field', 'molecule_bond'}


def _start(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}"><style>'
        'text{font-family:Arial,sans-serif;fill:#172033}.line{stroke:#344054;stroke-width:2;fill:none}'
        '.wire{stroke:#101828;stroke-width:2;fill:none}.node{fill:#fff;stroke:#344054;stroke-width:2}'
        '.muted{fill:#667085}</style>'
    )


def render_resistor_network(title: str, labels: tuple[str, ...]) -> str:
    labels = labels or ('R1', 'R2', 'R3')
    width, height = 720, 330
    p = [_start(width, height, title), f'<text x="360" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    p.append('<line class="wire" x1="75" y1="165" x2="150" y2="165"/><line class="wire" x1="570" y1="165" x2="645" y2="165"/>')
    p.append('<line class="wire" x1="150" y1="95" x2="150" y2="235"/><line class="wire" x1="570" y1="95" x2="570" y2="235"/>')
    ys = [105, 165, 225]
    for i, y in enumerate(ys):
        label = labels[i] if i < len(labels) else f'R{i+1}'
        p.append(f'<line class="wire" x1="150" y1="{y}" x2="245" y2="{y}"/>')
        p.append(f'<path class="wire" d="M245 {y} l14 -12 18 24 18 -24 18 24 18 -24 14 12"/>')
        p.append(f'<line class="wire" x1="335" y1="{y}" x2="570" y2="{y}"/>')
        p.append(f'<text x="290" y="{y-18}" text-anchor="middle" font-size="13">{escape(label)}</text>')
    p.append('<circle cx="75" cy="165" r="5" fill="#101828"/><circle cx="645" cy="165" r="5" fill="#101828"/>')
    p.append('<text class="muted" x="360" y="300" text-anchor="middle" font-size="11">المواضع والقيم النهائية تُراجع مع المصدر قبل الاعتماد</text></svg>')
    return ''.join(p)


def render_magnetic_field(title: str, labels: tuple[str, ...]) -> str:
    conductor = labels[0] if labels else 'موصل يمر به تيار'
    width, height = 560, 390
    cx, cy = 280, 205
    p = [_start(width, height, title), f'<text x="280" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    p.append(f'<circle class="node" cx="{cx}" cy="{cy}" r="30"/><circle cx="{cx}" cy="{cy}" r="5" fill="#101828"/>')
    p.append(f'<text x="{cx}" y="{cy+55}" text-anchor="middle" font-size="13">{escape(conductor)}</text>')
    for radius in (70, 110, 150):
        p.append(f'<circle class="line" cx="{cx}" cy="{cy}" r="{radius}"/>')
        ang = -0.35
        x, y = cx + radius*cos(ang), cy + radius*sin(ang)
        p.append(f'<path class="line" d="M {x-12} {y-9} L {x} {y} L {x-13} {y+5}"/>')
    p.append('<text class="muted" x="280" y="375" text-anchor="middle" font-size="11">اتجاه المجال واتجاه التيار يجب مطابقتهما للمصدر</text></svg>')
    return ''.join(p)


def render_molecule_bond(title: str, labels: tuple[str, ...]) -> str:
    labels = labels or ('A', 'B')
    atoms = labels[:4]
    width, height = 620, 300
    cx, cy = 310, 165
    p = [_start(width, height, title), f'<text x="310" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    if len(atoms) == 1:
        atoms = (atoms[0], 'B')
    positions = []
    n = len(atoms)
    for i, atom in enumerate(atoms):
        angle = 2*pi*i/n
        x, y = cx + 105*cos(angle), cy + 72*sin(angle)
        positions.append((x, y, atom))
    for x, y, _ in positions:
        p.append(f'<line class="line" x1="{cx}" y1="{cy}" x2="{x}" y2="{y}"/>')
    p.append(f'<circle class="node" cx="{cx}" cy="{cy}" r="34"/><text x="{cx}" y="{cy+5}" text-anchor="middle" font-size="15">{escape(atoms[0])}</text>')
    for idx, (x, y, atom) in enumerate(positions[1:], 1):
        p.append(f'<circle class="node" cx="{x}" cy="{y}" r="30"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="14">{escape(atom)}</text>')
    p.append('<text class="muted" x="310" y="282" text-anchor="middle" font-size="11">نوع الرابطة والزوايا الدقيقة تحتاج مراجعة علمية قبل الاعتماد</text></svg>')
    return ''.join(p)


def render_advanced(kind: str, title: str, labels: tuple[str, ...]) -> dict | None:
    if kind == 'resistor_network':
        svg = render_resistor_network(title, labels)
    elif kind == 'magnetic_field':
        svg = render_magnetic_field(title, labels)
    elif kind == 'molecule_bond':
        svg = render_molecule_bond(title, labels)
    else:
        return None
    return {
        'svg': svg,
        'valid': True,
        'issues': [],
        'deterministic': True,
        'review_required': True,
        'review_reason': 'advanced_scientific_relationship_requires_teacher_check',
        'extension_renderer': kind,
    }
