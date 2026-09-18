from __future__ import annotations

from html import escape
from math import atan2, cos, pi, sin
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Annotated[float, Field(ge=0.0, le=1.0)]


class StrictSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ForceArrowSpec(StrictSpec):
    label: str = Field(min_length=1, max_length=80)
    x1: Unit
    y1: Unit
    x2: Unit
    y2: Unit


class ForceDiagramSpec(StrictSpec):
    object_label: str | None = Field(default=None, max_length=80)
    object_x: Unit = 0.5
    object_y: Unit = 0.5
    forces: list[ForceArrowSpec] = Field(min_length=1, max_length=12)


class GraphPointSpec(StrictSpec):
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)


class GraphSeriesSpec(StrictSpec):
    label: str = Field(min_length=1, max_length=80)
    points: list[GraphPointSpec] = Field(min_length=2, max_length=64)


class GraphPlotSpec(StrictSpec):
    x_label: str = Field(min_length=1, max_length=80)
    y_label: str = Field(min_length=1, max_length=80)
    x_min: float = Field(ge=-1_000_000, le=1_000_000)
    x_max: float = Field(ge=-1_000_000, le=1_000_000)
    y_min: float = Field(ge=-1_000_000, le=1_000_000)
    y_max: float = Field(ge=-1_000_000, le=1_000_000)
    series: list[GraphSeriesSpec] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("graph_bounds_invalid")
        for series in self.series:
            for point in series.points:
                if not (self.x_min <= point.x <= self.x_max and self.y_min <= point.y <= self.y_max):
                    raise ValueError("graph_point_outside_explicit_bounds")
        return self


class ParticleSpec(StrictSpec):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=40)
    x: Unit
    y: Unit


class ParticleLinkSpec(StrictSpec):
    from_id: str = Field(alias="from", min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=40)


class ParticleModelSpec(StrictSpec):
    particles: list[ParticleSpec] = Field(min_length=1, max_length=40)
    links: list[ParticleLinkSpec] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [p.id for p in self.particles]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_particle_id")
        known = set(ids)
        for link in self.links:
            if link.from_id not in known or link.to not in known:
                raise ValueError("particle_link_unknown_node")
            if link.from_id == link.to:
                raise ValueError("particle_self_link")
        return self


class ReactionProfileSpec(StrictSpec):
    reactants_label: str = Field(min_length=1, max_length=80)
    products_label: str = Field(min_length=1, max_length=80)
    energy_unit: str = Field(min_length=1, max_length=20)
    reactants_energy: float = Field(ge=-1_000_000, le=1_000_000)
    products_energy: float = Field(ge=-1_000_000, le=1_000_000)
    transition_energy: float = Field(ge=-1_000_000, le=1_000_000)

    @model_validator(mode="after")
    def validate_profile(self):
        if self.transition_energy < max(self.reactants_energy, self.products_energy):
            raise ValueError("transition_energy_below_endpoint")
        return self


class CellPartSpec(StrictSpec):
    label: str = Field(min_length=1, max_length=80)
    x: Unit
    y: Unit


class CellStructureSpec(StrictSpec):
    cell_type: Literal["plant", "animal", "prokaryotic", "generic"]
    parts: list[CellPartSpec] = Field(min_length=1, max_length=16)


class FoodWebNodeSpec(StrictSpec):
    id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=80)
    x: Unit
    y: Unit


class FoodWebEdgeSpec(StrictSpec):
    from_id: str = Field(alias="from", min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=32)
    relation_label: str | None = Field(default=None, max_length=80)


class FoodWebSpec(StrictSpec):
    nodes: list[FoodWebNodeSpec] = Field(min_length=2, max_length=20)
    edges: list[FoodWebEdgeSpec] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_food_web_node")
        known = set(ids)
        for edge in self.edges:
            if edge.from_id not in known or edge.to not in known:
                raise ValueError("food_web_edge_unknown_node")
            if edge.from_id == edge.to:
                raise ValueError("food_web_self_edge")
        return self


class EarthLayerSpec(StrictSpec):
    label: str = Field(min_length=1, max_length=80)
    relative_thickness: float = Field(gt=0.0, le=1.0)


class EarthLayersSpec(StrictSpec):
    layers_outer_to_inner: list[EarthLayerSpec] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_total(self):
        total = sum(x.relative_thickness for x in self.layers_outer_to_inner)
        if total > 1.000001:
            raise ValueError("earth_layer_relative_thickness_total_exceeds_one")
        return self


SPEC_MODELS_V2 = {
    "force_diagram": ForceDiagramSpec,
    "graph_plot": GraphPlotSpec,
    "particle_model": ParticleModelSpec,
    "reaction_profile": ReactionProfileSpec,
    "cell_structure": CellStructureSpec,
    "food_web": FoodWebSpec,
    "earth_layers": EarthLayersSpec,
}

SPEC_CONTRACTS_V2 = {
    "force_diagram": "explicit_force_vectors_v1",
    "graph_plot": "explicit_graph_series_v1",
    "particle_model": "explicit_particle_positions_v1",
    "reaction_profile": "explicit_reaction_energy_v1",
    "cell_structure": "explicit_cell_labels_v1",
    "food_web": "explicit_food_web_edges_v1",
    "earth_layers": "explicit_earth_layers_v1",
}

SPEC_DOMAINS_V2 = {
    "force_diagram": "physics",
    "graph_plot": "cross_science",
    "particle_model": "chemistry",
    "reaction_profile": "chemistry",
    "cell_structure": "middle_school_science",
    "food_web": "middle_school_science",
    "earth_layers": "middle_school_science",
}


def _svg_start(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        '<style>text{font-family:Arial,sans-serif;fill:#172033}.line{stroke:#344054;stroke-width:2;fill:none}.node{fill:#fff;stroke:#344054;stroke-width:2}.soft{fill:#f8fafc;stroke:#98a2b3;stroke-width:1.5}.axis{stroke:#101828;stroke-width:2}.muted{fill:#667085}</style>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" font-weight="700">{escape(title)}</text>',
    ]


def _arrow(parts: list[str], x1: float, y1: float, x2: float, y2: float) -> None:
    parts.append(f'<line class="line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    angle = atan2(y2-y1, x2-x1)
    size = 9
    a1, a2 = angle + pi*0.82, angle - pi*0.82
    p1=(x2+size*cos(a1),y2+size*sin(a1));p2=(x2+size*cos(a2),y2+size*sin(a2))
    parts.append(f'<path class="line" d="M {p1[0]} {p1[1]} L {x2} {y2} L {p2[0]} {p2[1]}"/>')


def render_force_diagram(title: str, p: dict) -> str:
    parts=_svg_start(720,360,title)
    ox=80+float(p["object_x"])*560;oy=65+float(p["object_y"])*230
    parts.append(f'<rect class="soft" x="{ox-38}" y="{oy-28}" width="76" height="56" rx="8"/>')
    if p.get("object_label"):
        parts.append(f'<text x="{ox}" y="{oy+5}" text-anchor="middle" font-size="13">{escape(str(p["object_label"]))}</text>')
    for force in p["forces"]:
        x1=80+float(force["x1"])*560;y1=65+float(force["y1"])*230;x2=80+float(force["x2"])*560;y2=65+float(force["y2"])*230
        _arrow(parts,x1,y1,x2,y2)
        parts.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2-8}" text-anchor="middle" font-size="12">{escape(str(force["label"]))}</text>')
    parts.append('<text class="muted" x="360" y="342" text-anchor="middle" font-size="10">كل متجه قوة وإحداثياته مُدخل صراحة؛ لا يتم استنتاج قوى مفقودة</text></svg>')
    return ''.join(parts)


def render_graph_plot(title: str, p: dict) -> str:
    parts=_svg_start(720,400,title)
    left,right,top,bottom=90,650,60,330
    _arrow(parts,left,bottom,right,bottom);_arrow(parts,left,bottom,left,top)
    parts.append(f'<text x="{right}" y="{bottom+30}" text-anchor="end" font-size="12">{escape(str(p["x_label"]))}</text>')
    parts.append(f'<text x="{left-15}" y="{top}" text-anchor="end" font-size="12">{escape(str(p["y_label"]))}</text>')
    xmin,xmax=float(p["x_min"]),float(p["x_max"]);ymin,ymax=float(p["y_min"]),float(p["y_max"])
    def xy(pt):
        x=left+(float(pt["x"])-xmin)/(xmax-xmin)*(right-left)
        y=bottom-(float(pt["y"])-ymin)/(ymax-ymin)*(bottom-top)
        return x,y
    for series in p["series"]:
        coords=[xy(pt) for pt in series["points"]]
        points=' '.join(f'{x},{y}' for x,y in coords)
        parts.append(f'<polyline class="line" points="{points}"/>')
        for x,y in coords: parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#344054"/>')
        x,y=coords[-1];parts.append(f'<text x="{x+6}" y="{y-6}" font-size="10">{escape(str(series["label"]))}</text>')
    parts.append('<text class="muted" x="360" y="385" text-anchor="middle" font-size="10">النقاط والحدود مأخوذة من بيانات صريحة فقط</text></svg>')
    return ''.join(parts)


def render_particle_model(title: str, p: dict) -> str:
    parts=_svg_start(720,360,title)
    pos={x["id"]:(80+float(x["x"])*560,65+float(x["y"])*230,x["label"]) for x in p["particles"]}
    for link in p.get("links") or []:
        x1,y1,_=pos[link["from"]];x2,y2,_=pos[link["to"]]
        parts.append(f'<line class="line" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>')
    for _,(x,y,label) in pos.items():
        parts.append(f'<circle class="node" cx="{x}" cy="{y}" r="20"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="11">{escape(str(label))}</text>')
    parts.append('<text class="muted" x="360" y="342" text-anchor="middle" font-size="10">الجسيمات والروابط والمواضع صريحة؛ لا يتم استنتاج تركيب مفقود</text></svg>')
    return ''.join(parts)


def render_reaction_profile(title: str, p: dict) -> str:
    parts=_svg_start(720,400,title)
    left,right,top,bottom=90,650,65,330
    _arrow(parts,left,bottom,right,bottom);_arrow(parts,left,bottom,left,top)
    vals=[float(p["reactants_energy"]),float(p["products_energy"]),float(p["transition_energy"])]
    lo=min(vals);hi=max(vals);span=max(1e-9,hi-lo)
    def yy(v): return bottom-35-(v-lo)/span*(bottom-top-70)
    yr,yp,yt=yy(vals[0]),yy(vals[1]),yy(vals[2])
    parts.append(f'<path class="line" d="M 130 {yr} C 280 {yr} 300 {yt} 360 {yt} C 430 {yt} 455 {yp} 590 {yp}"/>')
    parts.append(f'<text x="135" y="{yr-10}" font-size="11">{escape(str(p["reactants_label"]))}</text>')
    parts.append(f'<text x="585" y="{yp-10}" text-anchor="end" font-size="11">{escape(str(p["products_label"]))}</text>')
    parts.append(f'<text x="72" y="{top+10}" text-anchor="end" font-size="10">{escape(str(p["energy_unit"]))}</text>')
    parts.append('<text class="muted" x="360" y="385" text-anchor="middle" font-size="10">قيم طاقة المتفاعلات والنواتج والحالة الانتقالية مُدخلة صراحة</text></svg>')
    return ''.join(parts)


def render_cell_structure(title: str, p: dict) -> str:
    parts=_svg_start(720,390,title)
    cell_type=p["cell_type"]
    if cell_type=="plant":
        parts.append('<rect class="soft" x="130" y="70" width="430" height="250" rx="24"/>')
    else:
        parts.append('<ellipse class="soft" cx="345" cy="195" rx="215" ry="125"/>')
    for item in p["parts"]:
        x=150+float(item["x"])*390;y=85+float(item["y"])*220
        parts.append(f'<circle class="node" cx="{x}" cy="{y}" r="8"/><text x="{x+12}" y="{y+4}" font-size="11">{escape(str(item["label"]))}</text>')
    parts.append('<text class="muted" x="360" y="370" text-anchor="middle" font-size="10">الأجزاء والمسميات والمواضع صريحة؛ لا تُضاف عضيات أو وظائف تلقائيًا</text></svg>')
    return ''.join(parts)


def render_food_web(title: str, p: dict) -> str:
    parts=_svg_start(720,390,title)
    pos={n["id"]:(90+float(n["x"])*540,65+float(n["y"])*250,n["label"]) for n in p["nodes"]}
    for edge in p["edges"]:
        x1,y1,_=pos[edge["from"]];x2,y2,_=pos[edge["to"]]
        _arrow(parts,x1,y1,x2,y2)
        if edge.get("relation_label"):
            parts.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2-7}" text-anchor="middle" font-size="9">{escape(str(edge["relation_label"]))}</text>')
    for _,(x,y,label) in pos.items():
        parts.append(f'<rect class="node" x="{x-48}" y="{y-18}" width="96" height="36" rx="9"/><text x="{x}" y="{y+4}" text-anchor="middle" font-size="11">{escape(str(label))}</text>')
    parts.append('<text class="muted" x="360" y="372" text-anchor="middle" font-size="10">اتجاه كل علاقة غذائية مأخوذ من edge صريح؛ لا تُنشأ علاقات غير موجودة</text></svg>')
    return ''.join(parts)


def render_earth_layers(title: str, p: dict) -> str:
    parts=_svg_start(720,390,title)
    cx,cy=290,215;outer=145
    layers=p["layers_outer_to_inner"]
    total=sum(float(x["relative_thickness"]) for x in layers) or 1.0
    radius=outer
    rings=[]
    for layer in layers:
        thickness=outer*float(layer["relative_thickness"])/total
        rings.append((radius,layer["label"]))
        radius=max(8,radius-thickness)
    for r,label in rings:
        parts.append(f'<circle class="soft" cx="{cx}" cy="{cy}" r="{r}"/>')
        parts.append(f'<line class="line" x1="{cx+r*0.7}" y1="{cy-r*0.7}" x2="545" y2="{90+len(parts)%220}"/>')
        parts.append(f'<text x="555" y="{95+len(parts)%220}" font-size="11">{escape(str(label))}</text>')
    parts.append('<text class="muted" x="360" y="372" text-anchor="middle" font-size="10">ترتيب الطبقات وسماكاتها النسبية مُدخلة صراحة</text></svg>')
    return ''.join(parts)


def render_visual_v2(kind: str, title: str, parameters: dict) -> dict | None:
    fn={
        "force_diagram":render_force_diagram,
        "graph_plot":render_graph_plot,
        "particle_model":render_particle_model,
        "reaction_profile":render_reaction_profile,
        "cell_structure":render_cell_structure,
        "food_web":render_food_web,
        "earth_layers":render_earth_layers,
    }.get(kind)
    if not fn:
        return None
    return {
        "svg": fn(title, parameters),
        "valid": True,
        "issues": [],
        "deterministic": True,
        "review_required": True,
        "review_reason": "source_grounded_science_visual_requires_teacher_check",
        "parameterized": True,
        "parameter_contract": SPEC_CONTRACTS_V2[kind],
        "domain": SPEC_DOMAINS_V2[kind],
    }
