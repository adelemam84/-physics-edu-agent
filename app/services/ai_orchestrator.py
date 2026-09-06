from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ResearchTask = Literal['source_analysis', 'lesson_support', 'question_review', 'visual_review']


@dataclass(frozen=True)
class OrchestrationPlan:
    task: ResearchTask
    primary_role: str
    secondary_provider: str
    source_mode: str
    requires_source: bool
    can_write_question_bank: bool
    can_auto_approve: bool
    can_publish: bool
    post_validation: tuple[str, ...]


def build_orchestration_plan(
    task: ResearchTask,
    *,
    provider_configured: bool,
    file_search_configured: bool,
    page_count: int,
) -> OrchestrationPlan:
    """Choose the safest source-research path without changing academic content.

    The primary platform always owns workflow decisions. Gemini is a secondary,
    advisory source engine only. Visual/small-range jobs use exact PDF pages;
    larger textual jobs may use a configured persistent File Search store.
    """
    if task not in {'source_analysis', 'lesson_support', 'question_review', 'visual_review'}:
        raise ValueError('unsupported research task')
    if page_count < 1:
        raise ValueError('page_count must be positive')

    if not provider_configured:
        source_mode = 'provider_unavailable'
    elif task in {'visual_review', 'question_review'}:
        source_mode = 'exact_pdf_pages'
    elif file_search_configured and page_count > 6:
        source_mode = 'file_search'
    else:
        source_mode = 'exact_pdf_pages'

    return OrchestrationPlan(
        task=task,
        primary_role='workflow_owner_and_final_gate',
        secondary_provider='gemini_source_engine',
        source_mode=source_mode,
        requires_source=True,
        can_write_question_bank=False,
        can_auto_approve=False,
        can_publish=False,
        post_validation=(
            'source_document_match',
            'source_page_scope_match',
            'verbatim_question_text_when_applicable',
            'no_open_qa_before_question_approval',
        ),
    )


def plan_dict(plan: OrchestrationPlan) -> dict:
    out = asdict(plan)
    out['post_validation'] = list(plan.post_validation)
    return out


def integrity_envelope(*, provider: str, document_id: int, page_start: int, page_end: int) -> dict:
    """Standard immutable contract attached to all secondary-engine responses."""
    return {
        'provider': provider,
        'source_document_id': document_id,
        'source_pages': {'start': page_start, 'end': page_end},
        'advisory_only': True,
        'auto_saved_to_question_bank': False,
        'auto_approved': False,
        'auto_published': False,
        'requires_human_or_deterministic_review_before_use': True,
    }
