from __future__ import annotations

from html import escape
from math import cos, pi, sin


ADVANCED_KINDS = {
    'resistor_network',
    'series_parallel_circuit',
    'magnetic_field',
    'solenoid_field',
    'molecule_bond',
    'chemistry_lab_setup',
}


def _start(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}"><style>'
        'text{font-family:Arial,sans-serif;fill:#172033}.line{stroke:#344054;stroke-width:2;fill:none}'
        '.wire{stroke:#101828;stroke-width:2;fill:none}.node{fill:#fff;stroke:#344054;stroke-width:2}'
        '.soft{fill:#f8fafc;stroke:#98a2b3;stroke-width:1.5}.muted{fill:#667085}</style>'
    )


def _resistor(x: float, y: float, label: str) -> str:
    return (
        f'<line class="wire" x1="{x-55}" y1="{y}" x2="{x-38}" y2="{y}"/>'
        f'<path class="wire" d="M{x-38} {y} l10 -11 14 22 14 -22 14 22 14 -22 10 11"/>'
        f'<line class="wire" x1="{x+38}" y1="{y}" x2="{x+55}" y2="{y}"/>'
        f'<text x="{x}" y="{y-18}" text-anchor="middle" font-size="13">{escape(label)}</text>'
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
        p.append(f'<line class="wire" x1="150" y1="{y}" x2="250" y2="{y}"/>')
        p.append(_resistor(305, y, label))
        p.append(f'<line class="wire" x1="360" y1="{y}" x2="570" y2="{y}"/>')
    p.append('<circle cx="75" cy="165" r="5" fill="#101828"/><circle cx="645" cy="165" r="5" fill="#101828"/>')
    p.append('<text class="muted" x="360" y="300" text-anchor="middle" font-size="11">المواضع والقيم النهائية تُراجع مع المصدر قبل الاعتماد</text></svg>')
    return ''.join(p)


def render_series_parallel_circuit(title: str, labels: tuple[str, ...]) -> str:
    labels = labels or ('R1', 'R2', 'R3')
    r1 = labels[0] if len(labels) > 0 else 'R1'
    r2 = labels[1] if len(labels) > 1 else 'R2'
    r3 = labels[2] if len(labels) > 2 else 'R3'
    width, height = 760, 360
    p = [_start(width, height, title), f'<text x="380" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    p.append('<line class="wire" x1="70" y1="180" x2="165" y2="180"/>')
    p.append(_resistor(220, 180, r1))
    p.append('<line class="wire" x1="275" y1="180" x2="330" y2="180"/>')
    p.append('<line class="wire" x1="330" y1="110" x2="330" y2="250"/><line class="wire" x1="650" y1="110" x2="650" y2="250"/>')
    p.append('<line class="wire" x1="330" y1="125" x2="420" y2="125"/>')
    p.append(_resistor(475, 125, r2))
    p.append('<line class="wire" x1="530" y1="125" x2="650" y2="125"/>')
    p.append('<line class="wire" x1="330" y1="235" x2="420" y2="235"/>')
    p.append(_resistor(475, 235, r3))
    p.append('<line class="wire" x1="530" y1="235" x2="650" y2="235"/>')
    p.append('<line class="wire" x1="650" y1="180" x2="700" y2="180"/>')
    p.append('<text class="muted" x="380" y="330" text-anchor="middle" font-size="11">ترتيب الفروع ورموز العناصر يجب مطابقتهما للمصدر</text></svg>')
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


def render_solenoid_field(title: str, labels: tuple[str, ...]) -> str:
    coil = labels[0] if labels else 'ملف لولبي'
    field = labels[1] if len(labels) > 1 else 'B'
    width, height = 760, 330
    p = [_start(width, height, title), f'<text x="380" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    x0, y0 = 210, 165
    for i in range(10):
        x = x0 + i * 34
        p.append(f'<ellipse class="line" cx="{x}" cy="{y0}" rx="18" ry="68"/>')
    p.append('<line class="wire" x1="130" y1="97" x2="210" y2="97"/><line class="wire" x1="516" y1="233" x2="630" y2="233"/>')
    p.append(f'<text x="380" y="260" text-anchor="middle" font-size="13">{escape(coil)}</text>')
    p.append('<line class="line" x1="165" y1="165" x2="595" y2="165"/>')
    p.append('<path class="line" d="M585 157 L600 165 L585 173"/>')
    p.append(f'<text x="610" y="160" font-size="14">{escape(field)}</text>')
    p.append('<text class="muted" x="380" y="305" text-anchor="middle" font-size="11">قطبية الملف واتجاه المجال والتيار تحتاج مراجعة مع المرجع</text></svg>')
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
    for x, y, atom in positions[1:]:
        p.append(f'<circle class="node" cx="{x}" cy="{y}" r="30"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="14">{escape(atom)}</text>')
    p.append('<text class="muted" x="310" y="282" text-anchor="middle" font-size="11">نوع الرابطة والزوايا الدقيقة تحتاج مراجعة علمية قبل الاعتماد</text></svg>')
    return ''.join(p)


def render_chemistry_lab_setup(title: str, labels: tuple[str, ...]) -> str:
    labels = labels or ('دورق', 'أنبوب توصيل', 'وعاء تجميع')
    a = labels[0] if len(labels) > 0 else 'دورق'
    b = labels[1] if len(labels) > 1 else 'أنبوب توصيل'
    c = labels[2] if len(labels) > 2 else 'وعاء تجميع'
    width, height = 760, 360
    p = [_start(width, height, title), f'<text x="380" y="30" text-anchor="middle" font-size="19" font-weight="700">{escape(title)}</text>']
    p.append('<path class="line" d="M155 105 L195 105 L215 175 Q215 240 155 250 Q95 240 95 175 L115 105 L155 105"/>')
    p.append(f'<text x="155" y="280" text-anchor="middle" font-size="13">{escape(a)}</text>')
    p.append('<path class="line" d="M195 105 C300 90 350 105 430 145 L520 145"/>')
    p.append(f'<text x="360" y="92" text-anchor="middle" font-size="13">{escape(b)}</text>')
    p.append('<rect class="soft" x="520" y="120" width="120" height="150" rx="10"/>')
    p.append('<line class="line" x1="545" y1="145" x2="545" y2="230"/>')
    p.append(f'<text x="580" y="292" text-anchor="middle" font-size="13">{escape(c)}</text>')
    p.append('<text class="muted" x="380" y="335" text-anchor="middle" font-size="11">نوع المواد واتجاه الغاز/السائل ووصلات الجهاز يجب مراجعتها مع المصدر</text></svg>')
    return ''.join(p)


def render_advanced(kind: str, title: str, labels: tuple[str, ...]) -> dict | None:
    if kind == 'resistor_network':
        svg = render_resistor_network(title, labels)
    elif kind == 'series_parallel_circuit':
        svg = render_series_parallel_circuit(title, labels)
    elif kind == 'magnetic_field':
        svg = render_magnetic_field(title, labels)
    elif kind == 'solenoid_field':
        svg = render_solenoid_field(title, labels)
    elif kind == 'molecule_bond':
        svg = render_molecule_bond(title, labels)
    elif kind == 'chemistry_lab_setup':
        svg = render_chemistry_lab_setup(title, labels)
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
