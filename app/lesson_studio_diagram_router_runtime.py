from __future__ import annotations

from . import science_lesson_studio
from .services.diagram_router import route_diagram

_BASE_ATTACH = science_lesson_studio._attach_diagram_engine


def _attach_with_smart_routing(structured: dict, subject: str) -> dict:
    routed = dict(structured)
    specs = []
    for raw in structured.get('diagram_specs') or []:
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
    routed['diagram_specs'] = specs
    return _BASE_ATTACH(routed, subject)


science_lesson_studio._attach_diagram_engine = _attach_with_smart_routing
