from __future__ import annotations

from . import science_lesson_studio
from .services.handwriting_preprocess import preprocess_handwriting

_BASE_VERIFIED_OCR = science_lesson_studio._verified_ocr


def _verified_ocr_with_preprocess(data: bytes, content_type: str, position: int):
    ocr_data, ocr_type, report = preprocess_handwriting(data, content_type)
    primary, alternate, verification = _BASE_VERIFIED_OCR(ocr_data, ocr_type, position)
    verification = dict(verification)
    verification['preprocess'] = report.as_dict()
    verification['original_preserved'] = True
    return primary, alternate, verification


science_lesson_studio._verified_ocr = _verified_ocr_with_preprocess
