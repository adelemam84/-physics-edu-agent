from __future__ import annotations

from . import science_lesson_studio
from .services.diagram_router import route_diagram
from .services.science_diagram_extensions import render_advanced

_BASE_ATTACH = science_lesson_studio._attach_diagram_engine


def _attach_with_smart_routing(structured: dict, subject: str) -> dict:
    routed = dict(structured)
    specs = []
    advanced_indexes: dict[int, tuple[str, tuple[str, ...], str]] = {}
    for idx, raw in enumerate(structured.get('diagram_specs') or []):
        item = dict(raw)
        route = route_diagram(
            str(item.get('kind') or ''),
            str(item.get('title') or ''),
            str(item.get('description') or ''),
            subject,
        )
        item['kind'] = route.kind
        item['routing'] = route.as_dict()
        specs.append(item)
        labels = tuple(str(x) for x in (item.get('scientific_labels') or []))
        if route.kind in {'resistor_network', 'magnetic_field', 'molecule_bond'}:
            advanced_indexes[idx] = (route.kind, labels, str(item.get('title') or 'رسم توضيحي'))
    routed['diagram_specs'] = specs
    out = _BASE_ATTACH(routed, subject)
    diagrams = list(out.get('diagram_specs') or [])
    for idx, (kind, labels, title) in advanced_indexes.items():
        if idx >= len(diagrams):
            continue
        rendered = render_advanced(kind, title, labels)
        if rendered:
            item = dict(diagrams[idx])
            item['normalized_kind'] = kind
            item['diagram_engine'] = rendered
            diagrams[idx] = item
    out['diagram_specs'] = diagrams
    summary = dict(out.get('diagram_engine_summary') or {})
    summary['total'] = len(diagrams)
    summary['deterministic_ready'] = sum(1 for x in diagrams if (x.get('diagram_engine') or {}).get('svg'))
    summary['review_required'] = sum(1 for x in diagrams if (x.get('diagram_engine') or {}).get('review_required'))
    summary['advanced_extension_kinds'] = ['magnetic_field', 'molecule_bond', 'resistor_network']
    out['diagram_engine_summary'] = summary
    return out


science_lesson_studio._attach_diagram_engine = _attach_with_smart_routing
