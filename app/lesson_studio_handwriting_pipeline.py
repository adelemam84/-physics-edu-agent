from __future__ import annotations

from fastapi import Depends

from .main import app
from .security import require_admin
from .science_lesson_studio import _job
from .services.handwriting_confidence import build_confidence_map, golden_page_contract, subject_profile


def handwriting_pipeline_snapshot(job_id: str) -> dict:
    row, sources = _job(job_id)
    structured = dict(row.get('structured_json') or {})
    source_items = []
    total_review_lines = 0
    for source in sources:
        cmap = build_confidence_map(
            str(source.get('extracted_text') or ''),
            float(source.get('confidence') or 0.0),
            list(source.get('ocr_conflicts') or []),
        )
        total_review_lines += int(cmap['summary']['review_required'])
        source_items.append({
            'id': source['id'],
            'position': source['position'],
            'filename': source['filename'],
            'confidence_band': source.get('ocr_confidence_band'),
            'source_requires_review': bool(source.get('requires_review')),
            'confidence_map': cmap,
        })
    diagrams = list(structured.get('diagram_specs') or [])
    return {
        'job_id': job_id,
        'subject': row.get('subject'),
        'status': row.get('status'),
        'source_count': len(sources),
        'subject_profile': subject_profile(str(row.get('subject') or 'science')),
        'sources': source_items,
        'summary': {
            'review_lines': total_review_lines,
            'uncertain_items': len(structured.get('uncertain_items') or []),
            'diagram_reviews': sum(1 for d in diagrams if (d.get('diagram_engine') or {}).get('review_required')),
            'notation_reviews': int((structured.get('notation_quality') or {}).get('review_required') or 0),
            'study_note_ready_for_teacher_review': bool(structured) and len(sources) > 0,
        },
        'golden_page_contract': golden_page_contract(),
        'pipeline': [
            'original_source_preserved',
            'ocr_derivative_preprocessed',
            'multimodal_transcription',
            'dual_provider_consensus_when_available',
            'line_confidence_map',
            'source_preserving_structuring',
            'subject_aware_diagram_strategy',
            'teacher_review',
            'quality_gate',
            'a4_or_mobile_pdf',
        ],
        'policy': {
            'no_silent_scientific_correction': True,
            'low_confidence_science_requires_teacher_review': True,
            'ai_generated_visuals_must_be_labeled': True,
        },
    }


@app.get('/api/admin/lesson-studio/jobs/{job_id}/handwriting-pipeline', dependencies=[Depends(require_admin)])
def handwriting_pipeline(job_id: str):
    return handwriting_pipeline_snapshot(job_id)
