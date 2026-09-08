from __future__ import annotations

from html import escape
from math import atan2, cos, pi, sin


PARAMETERIZED_KINDS = {
    'resistor_network',
    'series_parallel_circuit',
    'ray_diagram',
    'magnetic_field',
    'solenoid_field',
    'molecule_bond',
    'chemistry_lab_setup',
}


def _svg_start(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.wire{stroke:#101828;stroke-width:2;fill:none}.line{stroke:#344054;stroke-width:2;fill:none}.node{fill:#fff;stroke:#344054;stroke-width:2}.soft{fill:#f8fafc;stroke:#98a2b3;stroke-width:1.5}.muted{fill:#667085}</style>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" font-weight="700">{escape(title)}</text>',
    ]


def _num(value, *, lo: float, hi: float) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def _arrow(parts: list[str], x1: float, y1: float, x2: float, y2: float) -> None:
    parts.append(f'<line class="line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    angle = atan2(y2-y1, x2-x1)
    size = 9
    a1, a2 = angle + pi*0.82, angle - pi*0.82
    p1=(x2+size*cos(a1),y2+size*sin(a1));p2=(x2+size*cos(a2),y2+size*sin(a2))
    parts.append(f'<path class="line" d="M {p1[0]} {p1[1]} L {x2} {y2} L {p2[0]} {p2[1]}"/>')


def _resistor_between(parts: list[str], a: tuple[float,float], b: tuple[float,float], label: str) -> None:
    x1,y1=a;x2,y2=b
    dx,dy=x2-x1,y2-y1
    length=(dx*dx+dy*dy)**0.5
    if length < 55:
        parts.append(f'<line class="wire" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
        return
    ux,uy=dx/length,dy/length
    px,py=-uy,ux
    lead=length*0.23
    sx,sy=x1+ux*lead,y1+uy*lead
    ex,ey=x2-ux*lead,y2-uy*lead
    parts.append(f'<line class="wire" x1="{x1}" y1="{y1}" x2="{sx}" y2="{sy}"/>')
    pts=[]
    segments=8
    for i in range(segments+1):
        t=i/segments
        bx=sx+(ex-sx)*t;by=sy+(ey-sy)*t
        offset=0 if i in (0,segments) else (9 if i%2 else -9)
        pts.append(f'{bx+px*offset},{by+py*offset}')
    parts.append(f'<polyline class="wire" points="{" ".join(pts)}"/>')
    parts.append(f'<line class="wire" x1="{ex}" y1="{ey}" x2="{x2}" y2="{y2}"/>')
    mx,my=(x1+x2)/2,(y1+y2)/2
    parts.append(f'<text x="{mx+px*18}" y="{my+py*18}" text-anchor="middle" font-size="12">{escape(label)}</text>')


def render_resistor_graph(title: str, parameters: dict) -> dict:
    nodes=parameters.get('nodes')
    components=parameters.get('components')
    if not isinstance(nodes,list) or not isinstance(components,list) or len(nodes)<2 or not components:
        return {'ready':False,'issues':['missing_explicit_nodes_or_components']}
    pos={}
    for node in nodes[:16]:
        if not isinstance(node,dict) or not str(node.get('id') or '').strip():
            return {'ready':False,'issues':['invalid_node']}
        x=_num(node.get('x'),lo=0,hi=1);y=_num(node.get('y'),lo=0,hi=1)
        if x is None or y is None:
            return {'ready':False,'issues':['node_coordinates_required']}
        pos[str(node['id'])]=(80+x*600,65+y*230,str(node.get('label') or node['id']))
    parts=_svg_start(760,340,title)
    for comp in components[:32]:
        if not isinstance(comp,dict):
            return {'ready':False,'issues':['invalid_component']}
        a=str(comp.get('from') or '');b=str(comp.get('to') or '')
        if a not in pos or b not in pos:
            return {'ready':False,'issues':['component_references_unknown_node']}
        kind=str(comp.get('type') or '').lower()
        if kind not in {'resistor','wire'}:
            return {'ready':False,'issues':['unsupported_component_type']}
        p1=pos[a][:2];p2=pos[b][:2]
        if kind=='resistor':
            _resistor_between(parts,p1,p2,str(comp.get('label') or comp.get('value') or 'R'))
        else:
            parts.append(f'<line class="wire" x1="{p1[0]}" y1="{p1[1]}" x2="{p2[0]}" y2="{p2[1]}"/>')
    for _,(x,y,label) in pos.items():
        parts.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#101828"/><text x="{x+7}" y="{y-7}" font-size="11">{escape(label)}</text>')
    parts.append('<text class="muted" x="380" y="325" text-anchor="middle" font-size="10">الرسم مبني فقط من عقد ومكونات محددة صراحة في المصدر/المراجعة</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_graph_v1'}


def render_ray_paths(title: str, parameters: dict) -> dict:
    element=parameters.get('optical_element')
    rays=parameters.get('rays')
    if not isinstance(element,dict) or not isinstance(rays,list) or not rays:
        return {'ready':False,'issues':['missing_optical_element_or_explicit_rays']}
    ex=_num(element.get('x'),lo=0,hi=1)
    if ex is None:
        return {'ready':False,'issues':['optical_element_x_required']}
    etype=str(element.get('type') or '').lower()
    if etype not in {'convex_lens','concave_lens','concave_mirror','convex_mirror','plane_mirror'}:
        return {'ready':False,'issues':['unsupported_optical_element']}
    width,height=760,360;axis=190;xelem=60+ex*640
    parts=_svg_start(width,height,title)
    parts.append(f'<line class="line" x1="45" y1="{axis}" x2="715" y2="{axis}"/>')
    parts.append(f'<line class="line" x1="{xelem}" y1="70" x2="{xelem}" y2="300"/>')
    parts.append(f'<text x="{xelem}" y="55" text-anchor="middle" font-size="12">{escape(str(element.get("label") or etype))}</text>')
    for ray in rays[:12]:
        points=ray.get('points') if isinstance(ray,dict) else None
        if not isinstance(points,list) or len(points)<2:
            return {'ready':False,'issues':['each_ray_requires_two_or_more_explicit_points']}
        xy=[]
        for point in points[:8]:
            if not isinstance(point,(list,tuple)) or len(point)!=2:
                return {'ready':False,'issues':['invalid_ray_point']}
            x=_num(point[0],lo=0,hi=1);y=_num(point[1],lo=0,hi=1)
            if x is None or y is None:
                return {'ready':False,'issues':['ray_points_must_be_normalized']}
            xy.append((60+x*640,70+y*230))
        for i in range(len(xy)-1):
            _arrow(parts,*xy[i],*xy[i+1])
    for fx in parameters.get('focal_points') or []:
        f=_num(fx,lo=0,hi=1)
        if f is not None:
            px=60+f*640
            parts.append(f'<circle cx="{px}" cy="{axis}" r="4" fill="#b42318"/><text x="{px}" y="{axis+18}" text-anchor="middle" font-size="10">F</text>')
    parts.append('<text class="muted" x="380" y="340" text-anchor="middle" font-size="10">لا يتم اشتقاق مسارات الأشعة؛ تُرسم النقاط الصريحة فقط</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_ray_paths_v1'}


def render_magnetic_conductor(title: str, parameters: dict) -> dict:
    current=str(parameters.get('current_direction') or '').lower()
    field=str(parameters.get('field_direction') or '').lower()
    if current not in {'into_page','out_of_page'} or field not in {'clockwise','counterclockwise'}:
        return {'ready':False,'issues':['explicit_current_and_field_direction_required']}
    parts=_svg_start(560,390,title);cx,cy=280,205
    parts.append(f'<circle class="node" cx="{cx}" cy="{cy}" r="28"/>')
    if current=='out_of_page':
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="#101828"/>')
    else:
        parts.append(f'<line class="line" x1="{cx-8}" y1="{cy-8}" x2="{cx+8}" y2="{cy+8}"/><line class="line" x1="{cx+8}" y1="{cy-8}" x2="{cx-8}" y2="{cy+8}"/>')
    for radius in (70,110,150):
        parts.append(f'<circle class="line" cx="{cx}" cy="{cy}" r="{radius}"/>')
        angle=-0.45 if field=='counterclockwise' else 0.45
        x=cx+radius*cos(angle);y=cy+radius*sin(angle)
        tangent=angle+(-pi/2 if field=='clockwise' else pi/2)
        _arrow(parts,x-14*cos(tangent),y-14*sin(tangent),x+14*cos(tangent),y+14*sin(tangent))
    parts.append(f'<text x="{cx}" y="{cy+50}" text-anchor="middle" font-size="12">{escape(str(parameters.get("label") or "موصل"))}</text>')
    parts.append('<text class="muted" x="280" y="375" text-anchor="middle" font-size="10">اتجاه التيار والمجال مأخوذان من قيم صريحة ولا يتم استنتاجهما</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_magnetic_direction_v1'}


def render_solenoid(title: str, parameters: dict) -> dict:
    current=str(parameters.get('current_direction') or '').lower()
    field=str(parameters.get('field_direction') or '').lower()
    north=str(parameters.get('north_side') or '').lower()
    turns=parameters.get('turns')
    try:
        turns=int(turns)
    except (TypeError,ValueError):
        turns=0
    if current not in {'left_to_right','right_to_left'}:
        return {'ready':False,'issues':['explicit_solenoid_current_direction_required']}
    if field not in {'left_to_right','right_to_left'}:
        return {'ready':False,'issues':['explicit_solenoid_field_direction_required']}
    if north not in {'left','right'}:
        return {'ready':False,'issues':['explicit_solenoid_polarity_required']}
    if not 3 <= turns <= 18:
        return {'ready':False,'issues':['solenoid_turn_count_out_of_range']}
    width,height=760,350
    parts=_svg_start(width,height,title)
    x0,x1,y=190,570,180
    spacing=(x1-x0)/(turns-1)
    for i in range(turns):
        x=x0+i*spacing
        parts.append(f'<ellipse class="line" cx="{x}" cy="{y}" rx="16" ry="70"/>')
    parts.append(f'<line class="wire" x1="110" y1="110" x2="{x0}" y2="110"/><line class="wire" x1="{x1}" y1="250" x2="650" y2="250"/>')
    if field=='left_to_right':
        _arrow(parts,150,y,610,y)
    else:
        _arrow(parts,610,y,150,y)
    left_pole='N' if north=='left' else 'S';right_pole='N' if north=='right' else 'S'
    parts.append(f'<text x="150" y="155" text-anchor="middle" font-size="16" font-weight="700">{left_pole}</text>')
    parts.append(f'<text x="610" y="155" text-anchor="middle" font-size="16" font-weight="700">{right_pole}</text>')
    parts.append(f'<text x="380" y="290" text-anchor="middle" font-size="12">{escape(str(parameters.get("label") or "ملف لولبي"))} · {turns} turns</text>')
    parts.append(f'<text class="muted" x="380" y="330" text-anchor="middle" font-size="10">التيار: {escape(current)} · المجال: {escape(field)} · القطب N: {escape(north)}</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_solenoid_field_v1'}


def render_molecule(title: str, parameters: dict) -> dict:
    atoms=parameters.get('atoms');bonds=parameters.get('bonds')
    if not isinstance(atoms,list) or not isinstance(bonds,list) or len(atoms)<2:
        return {'ready':False,'issues':['explicit_atoms_and_bonds_required']}
    pos={}
    for atom in atoms[:24]:
        if not isinstance(atom,dict) or not str(atom.get('id') or ''):
            return {'ready':False,'issues':['invalid_atom']}
        x=_num(atom.get('x'),lo=0,hi=1);y=_num(atom.get('y'),lo=0,hi=1)
        if x is None or y is None:
            return {'ready':False,'issues':['atom_coordinates_required']}
        pos[str(atom['id'])]=(90+x*520,70+y*200,str(atom.get('element') or '?'),str(atom.get('charge') or ''))
    parts=_svg_start(700,320,title)
    for bond in bonds[:40]:
        if not isinstance(bond,dict):
            return {'ready':False,'issues':['invalid_bond']}
        a=str(bond.get('from') or '');b=str(bond.get('to') or '')
        try: order=int(bond.get('order') or 1)
        except (TypeError,ValueError): return {'ready':False,'issues':['invalid_bond_order']}
        if a not in pos or b not in pos or order not in {1,2,3}:
            return {'ready':False,'issues':['bond_reference_or_order_invalid']}
        x1,y1=pos[a][:2];x2,y2=pos[b][:2]
        dx,dy=x2-x1,y2-y1;length=(dx*dx+dy*dy)**0.5 or 1;px,py=-dy/length,dx/length
        offsets={1:[0],2:[-4,4],3:[-6,0,6]}[order]
        for off in offsets:
            parts.append(f'<line class="line" x1="{x1+px*off}" y1="{y1+py*off}" x2="{x2+px*off}" y2="{y2+py*off}"/>')
    for _,(x,y,el,charge) in pos.items():
        parts.append(f'<circle class="node" cx="{x}" cy="{y}" r="22"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="14">{escape(el)}</text>')
        if charge:
            parts.append(f'<text x="{x+20}" y="{y-18}" font-size="10">{escape(charge)}</text>')
    parts.append('<text class="muted" x="350" y="305" text-anchor="middle" font-size="10">العناصر والروابط ودرجاتها وإحداثياتها مأخوذة من مواصفات صريحة فقط</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_molecule_graph_v1'}


def render_lab_setup(title: str, parameters: dict) -> dict:
    vessels=parameters.get('vessels');connections=parameters.get('connections')
    if not isinstance(vessels,list) or not isinstance(connections,list) or not vessels:
        return {'ready':False,'issues':['explicit_lab_vessels_and_connections_required']}
    pos={}
    for vessel in vessels[:12]:
        if not isinstance(vessel,dict) or not str(vessel.get('id') or ''):
            return {'ready':False,'issues':['invalid_lab_vessel']}
        kind=str(vessel.get('type') or '').lower()
        if kind not in {'flask','beaker','test_tube','gas_jar','wash_bottle','receiver'}:
            return {'ready':False,'issues':['unsupported_lab_vessel_type']}
        x=_num(vessel.get('x'),lo=0,hi=1);y=_num(vessel.get('y'),lo=0,hi=1)
        if x is None or y is None:
            return {'ready':False,'issues':['lab_vessel_coordinates_required']}
        pos[str(vessel['id'])]=(90+x*560,85+y*190,kind,str(vessel.get('label') or vessel['id']))
    parts=_svg_start(740,340,title)
    for _,(x,y,kind,label) in pos.items():
        if kind=='flask':
            parts.append(f'<path class="line" d="M {x-18} {y-55} L {x+18} {y-55} L {x+28} {y-5} Q {x+35} {y+45} {x} {y+52} Q {x-35} {y+45} {x-28} {y-5} Z"/>')
        elif kind in {'beaker','gas_jar','receiver'}:
            parts.append(f'<rect class="soft" x="{x-30}" y="{y-42}" width="60" height="84" rx="7"/>')
        elif kind=='test_tube':
            parts.append(f'<path class="line" d="M {x-12} {y-52} L {x-12} {y+28} Q {x} {y+48} {x+12} {y+28} L {x+12} {y-52}"/>')
        else:
            parts.append(f'<rect class="soft" x="{x-26}" y="{y-38}" width="52" height="76" rx="10"/>')
        parts.append(f'<text x="{x}" y="{y+72}" text-anchor="middle" font-size="11">{escape(label)}</text>')
    for conn in connections[:20]:
        if not isinstance(conn,dict):
            return {'ready':False,'issues':['invalid_lab_connection']}
        a=str(conn.get('from') or '');b=str(conn.get('to') or '')
        direction=str(conn.get('direction') or '').lower()
        if a not in pos or b not in pos:
            return {'ready':False,'issues':['lab_connection_references_unknown_vessel']}
        if direction not in {'from_to','to_from','none'}:
            return {'ready':False,'issues':['explicit_lab_connection_direction_required']}
        x1,y1=pos[a][:2];x2,y2=pos[b][:2]
        if direction=='from_to':
            _arrow(parts,x1,y1,x2,y2)
        elif direction=='to_from':
            _arrow(parts,x2,y2,x1,y1)
        else:
            parts.append(f'<line class="line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
        label=str(conn.get('label') or '')
        if label:
            parts.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2-8}" text-anchor="middle" font-size="10">{escape(label)}</text>')
    parts.append('<text class="muted" x="370" y="325" text-anchor="middle" font-size="10">الأوعية والوصلات واتجاه الحركة تُرسم من مواصفات صريحة فقط؛ المواد والتفاعلات لا تُستنتج</text></svg>')
    return {'ready':True,'svg':''.join(parts),'issues':[],'parameter_contract':'explicit_lab_apparatus_v1'}


def render_parameterized(kind: str, title: str, parameters: dict | None) -> dict | None:
    if kind not in PARAMETERIZED_KINDS or not isinstance(parameters,dict) or not parameters:
        return None
    if kind in {'resistor_network','series_parallel_circuit'}:
        out=render_resistor_graph(title,parameters)
    elif kind=='ray_diagram':
        out=render_ray_paths(title,parameters)
    elif kind=='magnetic_field':
        out=render_magnetic_conductor(title,parameters)
    elif kind=='solenoid_field':
        out=render_solenoid(title,parameters)
    elif kind=='molecule_bond':
        out=render_molecule(title,parameters)
    elif kind=='chemistry_lab_setup':
        out=render_lab_setup(title,parameters)
    else:
        return None
    if not out.get('ready'):
        return {
            'svg':None,'valid':False,'issues':out.get('issues') or ['invalid_explicit_parameters'],
            'deterministic':True,'review_required':True,
            'review_reason':'explicit_parameters_incomplete_or_invalid',
            'parameterized':True,
        }
    return {
        'svg':out['svg'],'valid':True,'issues':[],'deterministic':True,
        'review_required':True,
        'review_reason':'parameterized_scientific_relationship_requires_teacher_check',
        'parameterized':True,
        'parameter_contract':out['parameter_contract'],
    }
