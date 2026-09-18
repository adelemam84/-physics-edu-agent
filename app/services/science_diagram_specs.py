from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .science_visual_engine_v2 import (
    SPEC_CONTRACTS_V2,
    SPEC_DOMAINS_V2,
    SPEC_MODELS_V2,
    render_visual_v2,
)


Unit = Annotated[float, Field(ge=0.0, le=1.0)]
RayPoint = tuple[Unit, Unit]


class StrictSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True, str_strip_whitespace=True)


class NodeSpec(StrictSpec):
    id: str = Field(min_length=1, max_length=32)
    x: Unit
    y: Unit
    label: str | None = Field(default=None, max_length=80)


class CircuitComponentSpec(StrictSpec):
    type: Literal['resistor', 'wire']
    from_: str = Field(alias='from', min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=80)
    value: str | None = Field(default=None, max_length=80)


class ResistorGraphSpec(StrictSpec):
    nodes: list[NodeSpec] = Field(min_length=2, max_length=16)
    components: list[CircuitComponentSpec] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def validate_graph(self):
        ids = [x.id for x in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_node_id')
        known = set(ids)
        seen: set[tuple[str, str, str]] = set()
        for component in self.components:
            if component.from_ not in known or component.to not in known:
                raise ValueError('component_references_unknown_node')
            if component.from_ == component.to:
                raise ValueError('component_self_loop_not_allowed')
            key = (component.type, component.from_, component.to)
            reverse = (component.type, component.to, component.from_)
            if key in seen or reverse in seen:
                raise ValueError('duplicate_component_edge')
            seen.add(key)
        return self


class OpticalElementSpec(StrictSpec):
    type: Literal['convex_lens', 'concave_lens', 'concave_mirror', 'convex_mirror', 'plane_mirror']
    x: Unit
    label: str | None = Field(default=None, max_length=80)


class RayPathSpec(StrictSpec):
    points: list[RayPoint] = Field(min_length=2, max_length=8)
    label: str | None = Field(default=None, max_length=80)


class RayDiagramSpec(StrictSpec):
    optical_element: OpticalElementSpec
    rays: list[RayPathSpec] = Field(min_length=1, max_length=12)
    focal_points: list[Unit] = Field(default_factory=list, max_length=4)


class MagneticFieldSpec(StrictSpec):
    current_direction: Literal['into_page', 'out_of_page']
    field_direction: Literal['clockwise', 'counterclockwise']
    label: str | None = Field(default=None, max_length=80)


class SolenoidFieldSpec(StrictSpec):
    current_direction: Literal['left_to_right', 'right_to_left']
    field_direction: Literal['left_to_right', 'right_to_left']
    north_side: Literal['left', 'right']
    turns: int = Field(ge=3, le=18)
    label: str | None = Field(default=None, max_length=80)


class AtomSpec(StrictSpec):
    id: str = Field(min_length=1, max_length=32)
    element: str = Field(pattern=r'^[A-Z][a-z]?$', min_length=1, max_length=2)
    x: Unit
    y: Unit
    charge: str | None = Field(default=None, max_length=8)


class BondSpec(StrictSpec):
    from_: str = Field(alias='from', min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=32)
    order: Literal[1, 2, 3] = 1


class MoleculeBondSpec(StrictSpec):
    atoms: list[AtomSpec] = Field(min_length=2, max_length=24)
    bonds: list[BondSpec] = Field(min_length=1, max_length=40)

    @model_validator(mode='after')
    def validate_molecule(self):
        ids = [x.id for x in self.atoms]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_atom_id')
        known = set(ids)
        seen: set[frozenset[str]] = set()
        for bond in self.bonds:
            if bond.from_ not in known or bond.to not in known:
                raise ValueError('bond_references_unknown_atom')
            if bond.from_ == bond.to:
                raise ValueError('bond_self_loop_not_allowed')
            edge = frozenset((bond.from_, bond.to))
            if edge in seen:
                raise ValueError('duplicate_bond_edge')
            seen.add(edge)
        return self


class LabVesselSpec(StrictSpec):
    id: str = Field(min_length=1, max_length=32)
    type: Literal['flask', 'beaker', 'test_tube', 'gas_jar', 'wash_bottle', 'receiver']
    x: Unit
    y: Unit
    label: str | None = Field(default=None, max_length=80)


class LabConnectionSpec(StrictSpec):
    from_: str = Field(alias='from', min_length=1, max_length=32)
    to: str = Field(min_length=1, max_length=32)
    direction: Literal['from_to', 'to_from', 'none']
    label: str | None = Field(default=None, max_length=80)


class ChemistryLabSetupSpec(StrictSpec):
    vessels: list[LabVesselSpec] = Field(min_length=1, max_length=12)
    connections: list[LabConnectionSpec] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def validate_apparatus(self):
        ids = [x.id for x in self.vessels]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_lab_vessel_id')
        known = set(ids)
        seen: set[frozenset[str]] = set()
        for connection in self.connections:
            if connection.from_ not in known or connection.to not in known:
                raise ValueError('lab_connection_references_unknown_vessel')
            if connection.from_ == connection.to:
                raise ValueError('lab_connection_self_loop_not_allowed')
            edge = frozenset((connection.from_, connection.to))
            if edge in seen:
                raise ValueError('duplicate_lab_connection')
            seen.add(edge)
        return self


SPEC_MODELS = {
    'resistor_network': ResistorGraphSpec,
    'series_parallel_circuit': ResistorGraphSpec,
    'ray_diagram': RayDiagramSpec,
    'magnetic_field': MagneticFieldSpec,
    'solenoid_field': SolenoidFieldSpec,
    'molecule_bond': MoleculeBondSpec,
    'chemistry_lab_setup': ChemistryLabSetupSpec,
}

SPEC_MODELS.update(SPEC_MODELS_V2)

SPEC_CONTRACTS = {
    'resistor_network': 'explicit_graph_v1',
    'series_parallel_circuit': 'explicit_graph_v1',
    'ray_diagram': 'explicit_ray_paths_v1',
    'magnetic_field': 'explicit_magnetic_direction_v1',
    'solenoid_field': 'explicit_solenoid_field_v1',
    'molecule_bond': 'explicit_molecule_graph_v1',
    'chemistry_lab_setup': 'explicit_lab_apparatus_v1',
}

SPEC_CONTRACTS.update(SPEC_CONTRACTS_V2)

SPEC_DOMAINS = {
    'resistor_network':'physics','series_parallel_circuit':'physics','ray_diagram':'physics',
    'magnetic_field':'physics','solenoid_field':'physics','molecule_bond':'chemistry',
    'chemistry_lab_setup':'chemistry',
}
SPEC_DOMAINS.update(SPEC_DOMAINS_V2)


def _validation_errors(exc: ValidationError) -> list[dict]:
    errors = []
    for item in exc.errors(include_url=False):
        errors.append({
            'path': '.'.join(str(x) for x in item.get('loc') or ()) or '$',
            'message': str(item.get('msg') or 'invalid value'),
            'type': str(item.get('type') or 'validation_error'),
        })
    return errors


def schema_catalog() -> dict:
    kinds = {}
    for kind, model in SPEC_MODELS.items():
        kinds[kind] = {
            'contract': SPEC_CONTRACTS[kind],
            'schema': model.model_json_schema(by_alias=True),
            'strict_extra_fields': True,
            'source_grounded_only': True,
            'review_required_after_render': True,
            'domain': SPEC_DOMAINS.get(kind, 'cross_science'),
        }
    return {
        'version': 'diagram-specs-v1',
        'kinds': kinds,
        'policy': {
            'unknown_fields_rejected': True,
            'invalid_relationships_block_rendering': True,
            'no_missing_scientific_values_are_inferred': True,
            'preview_never_approves_scientific_content': True,
        },
    }


def validate_diagram_spec(kind: str, parameters: dict | None) -> dict:
    kind = str(kind or '').strip()
    model = SPEC_MODELS.get(kind)
    if model is None:
        return {
            'valid': False,
            'kind': kind,
            'errors': [{'path': 'kind', 'message': 'unsupported parameterized diagram kind', 'type': 'unsupported_kind'}],
            'normalized': None,
            'contract': None,
        }
    if not isinstance(parameters, dict):
        return {
            'valid': False,
            'kind': kind,
            'errors': [{'path': 'parameters', 'message': 'parameters must be an object', 'type': 'invalid_parameters_type'}],
            'normalized': None,
            'contract': SPEC_CONTRACTS[kind],
        }
    try:
        parsed = model.model_validate(parameters)
    except ValidationError as exc:
        return {
            'valid': False,
            'kind': kind,
            'errors': _validation_errors(exc),
            'normalized': None,
            'contract': SPEC_CONTRACTS[kind],
        }
    return {
        'valid': True,
        'kind': kind,
        'errors': [],
        'normalized': parsed.model_dump(mode='python', by_alias=True, exclude_none=True),
        'contract': SPEC_CONTRACTS[kind],
        'strict_extra_fields': True,
        'source_grounded_only': True,
    }


def preview_diagram_spec(kind: str, title: str, parameters: dict | None) -> dict:
    validation = validate_diagram_spec(kind, parameters)
    if not validation['valid']:
        return {
            'valid': False,
            'kind': kind,
            'title': title,
            'validation': validation,
            'renderer_called': False,
            'svg': None,
        }
    from .science_diagram_parameterized import render_parameterized

    rendered = render_parameterized(kind, title or 'رسم علمي', validation['normalized'])
    if not rendered:
        rendered = render_visual_v2(kind, title or 'رسم علمي', validation['normalized'])
    if not rendered or not rendered.get('valid'):
        return {
            'valid': False,
            'kind': kind,
            'title': title,
            'validation': validation,
            'renderer_called': True,
            'render': rendered,
            'svg': None,
        }
    return {
        'valid': True,
        'kind': kind,
        'title': title,
        'validation': validation,
        'renderer_called': True,
        'render': rendered,
        'svg': rendered.get('svg'),
        'review_required': True,
        'approval_state_changed': False,
    }
