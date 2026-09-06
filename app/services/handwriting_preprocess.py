from __future__ import annotations

from dataclasses import dataclass, asdict
from io import BytesIO
import os

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass(frozen=True)
class PreprocessReport:
    applied: bool
    original_width: int | None
    original_height: int | None
    output_width: int | None
    output_height: int | None
    orientation_fixed: bool
    contrast_enhanced: bool
    sharpened: bool
    grayscale: bool
    perspective_corrected: bool
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


SUPPORTED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ENABLED = os.getenv('LESSON_STUDIO_PREPROCESS_IMAGES', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}
MAX_EDGE = int(os.getenv('LESSON_STUDIO_PREPROCESS_MAX_EDGE', '2200'))


def preprocess_handwriting(data: bytes, content_type: str) -> tuple[bytes, str, PreprocessReport]:
    """Create an OCR-oriented derivative while leaving the stored original untouched.

    The serverless-safe path performs EXIF orientation, conservative resizing,
    autocontrast and mild sharpening. Perspective correction is deliberately not
    guessed; the report keeps that fact explicit for review.
    """
    if not ENABLED or content_type not in SUPPORTED_IMAGE_TYPES:
        return data, content_type, PreprocessReport(False, None, None, None, None, False, False, False, False, False, 'not_applicable')
    try:
        img = Image.open(BytesIO(data))
        original_size = img.size
        exif = img.getexif() if hasattr(img, 'getexif') else {}
        orientation = exif.get(274) if exif else None
        transposed = ImageOps.exif_transpose(img)
        orientation_fixed = orientation not in (None, 1)
        img = transposed.convert('RGB')
        if max(img.size) > MAX_EDGE:
            scale = MAX_EDGE / max(img.size)
            img = img.resize(
                (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                Image.Resampling.LANCZOS,
            )
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray = ImageEnhance.Contrast(gray).enhance(1.12)
        gray = gray.filter(ImageFilter.UnsharpMask(radius=1.2, percent=115, threshold=3))
        out = BytesIO()
        gray.save(out, format='PNG', optimize=True)
        return out.getvalue(), 'image/png', PreprocessReport(
            True,
            original_size[0],
            original_size[1],
            gray.width,
            gray.height,
            bool(orientation_fixed),
            True,
            True,
            True,
            False,
            'ocr_derivative_only_original_preserved',
        )
    except Exception:
        return data, content_type, PreprocessReport(
            False, None, None, None, None, False, False, False, False, False,
            'preprocess_failed_original_used',
        )
