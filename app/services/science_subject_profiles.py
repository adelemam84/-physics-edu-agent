from __future__ import annotations

from copy import deepcopy
from typing import Any


_SUBJECT_ALIASES = {
    "physics": "physics",
    "فيزياء": "physics",
    "الفيزياء": "physics",
    "chemistry": "chemistry",
    "كيمياء": "chemistry",
    "الكيمياء": "chemistry",
    "science": "middle_school_science",
    "علوم": "middle_school_science",
    "العلوم": "middle_school_science",
    "middle_school_science": "middle_school_science",
}

_PROFILES = {
    "physics": {
        "id": "physics",
        "label_ar": "فيزياء",
        "grade_scope": "secondary_or_configured",
        "notation_families": ["physics_or_math_equation", "quantity_with_unit", "plain_text"],
        "visual_domains": ["physics", "cross_science"],
        "preferred_visual_kinds": [
            "resistor_network",
            "series_parallel_circuit",
            "ray_diagram",
            "magnetic_field",
            "solenoid_field",
            "force_diagram",
            "graph_plot",
        ],
        "qa": {
            "units_preserved_verbatim": True,
            "vector_direction_requires_explicit_source": True,
            "graph_points_require_explicit_source": True,
            "no_silent_scientific_correction": True,
        },
    },
    "chemistry": {
        "id": "chemistry",
        "label_ar": "كيمياء",
        "grade_scope": "secondary_or_configured",
        "notation_families": [
            "chemical_equation",
            "chemical_formula_candidate",
            "quantity_with_unit",
            "plain_text",
        ],
        "visual_domains": ["chemistry", "cross_science"],
        "preferred_visual_kinds": [
            "molecule_bond",
            "chemistry_lab_setup",
            "particle_model",
            "reaction_profile",
            "graph_plot",
        ],
        "qa": {
            "chemical_formula_digits_preserved": True,
            "charge_and_state_markers_preserved": True,
            "reaction_energy_requires_explicit_source": True,
            "no_silent_scientific_correction": True,
        },
    },
    "middle_school_science": {
        "id": "middle_school_science",
        "label_ar": "علوم إعدادي",
        "grade_scope": "middle_school",
        "notation_families": [
            "physics_or_math_equation",
            "chemical_equation",
            "chemical_formula_candidate",
            "quantity_with_unit",
            "plain_text",
        ],
        "visual_domains": ["middle_school_science", "physics", "chemistry", "cross_science"],
        "preferred_visual_kinds": [
            "cell_structure",
            "food_web",
            "earth_layers",
            "particle_model",
            "graph_plot",
            "force_diagram",
        ],
        "qa": {
            "cross_domain_units_allowed": True,
            "life_earth_science_labels_require_explicit_source": True,
            "chemical_and_physics_notation_allowed_when_source_present": True,
            "no_silent_scientific_correction": True,
        },
    },
}


def normalize_subject(subject: str) -> str:
    value = str(subject or "").strip().lower()
    if value in _SUBJECT_ALIASES:
        return _SUBJECT_ALIASES[value]
    for alias, normalized in _SUBJECT_ALIASES.items():
        if alias and alias in value:
            return normalized
    return "unknown"


def subject_profile(subject: str) -> dict[str, Any]:
    normalized = normalize_subject(subject)
    if normalized == "unknown":
        return {
            "id": "unknown",
            "label_ar": "مادة علمية غير مصنفة",
            "grade_scope": "configured",
            "notation_families": ["plain_text", "quantity_with_unit"],
            "visual_domains": ["cross_science"],
            "preferred_visual_kinds": ["graph_plot"],
            "qa": {
                "fail_closed_on_domain_specific_assumptions": True,
                "no_silent_scientific_correction": True,
            },
        }
    return deepcopy(_PROFILES[normalized])


def subject_profiles_catalog() -> dict[str, Any]:
    return {
        "profiles": [deepcopy(_PROFILES[key]) for key in ("physics", "chemistry", "middle_school_science")],
        "policy": {
            "profiles_are_presentation_and_qa_configuration_only": True,
            "profiles_do_not_add_scientific_content": True,
            "source_grounding_required": True,
            "official_question_bank_write": False,
            "content_ingestion_unchanged": True,
        },
    }


def visual_domain_allowed(subject: str, domain: str) -> bool:
    profile = subject_profile(subject)
    return str(domain or "cross_science") in set(profile.get("visual_domains") or [])


def notation_kind_allowed(subject: str, notation_kind: str) -> bool:
    profile = subject_profile(subject)
    return str(notation_kind or "plain_text") in set(profile.get("notation_families") or [])
