from __future__ import annotations

from io import BytesIO

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from .lesson_presentation_blueprint import presentation_preflight, project_edition


def _set_text(shape, text: str, *, size: int = 24, bold: bool = False) -> None:
    frame = shape.text_frame
    frame.clear()
    p = frame.paragraphs[0]
    p.text = str(text or "")
    p.alignment = PP_ALIGN.RIGHT
    p.font.size = Pt(size)
    p.font.bold = bold


def _add_notes(slide, notes: list[str]) -> None:
    if not notes:
        return
    try:
        notes_slide = slide.notes_slide
        frame = getattr(notes_slide, "notes_text_frame", None)
        if frame is None:
            return
        frame.clear()
        for i, note in enumerate(notes):
            p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            p.text = str(note)
    except Exception:
        # Notes support differs slightly across python-pptx versions; failure to attach
        # notes must not corrupt the editable slide deck.
        return


def render_presentation_pptx(blueprint: dict, edition: str) -> bytes:
    projected = project_edition(blueprint, edition)
    report = presentation_preflight(projected, edition=edition)
    if not report["ready"]:
        raise ValueError(f"presentation preflight failed: {report['blocking_failures']}")

    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)

    for idx, spec in enumerate(projected.get("slides") or []):
        if idx == 0:
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            _set_text(slide.shapes.title, spec.get("title") or projected.get("title") or "", size=30, bold=True)
            subtitle = slide.placeholders[1]
            _set_text(subtitle, f"{projected.get('subject') or ''} · {projected.get('grade_label') or ''}", size=18)
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            _set_text(slide.shapes.title, spec.get("title") or "", size=28, bold=True)
            body = slide.shapes.add_textbox(Inches(0.8), Inches(1.45), Inches(11.7), Inches(4.8))
            frame = body.text_frame
            frame.clear()
            blocks = list(spec.get("content_blocks") or [])
            if not blocks and spec.get("visual_specs"):
                blocks = [{"kind": "visual", "text": f"رسم/صورة: {v.get('title') or v.get('kind') or ''}"} for v in spec.get("visual_specs") or []]
            if not blocks and spec.get("table_specs"):
                blocks = [{"kind": "table", "text": "جدول منظم مرتبط بمحتوى الدرس"}]
            for i, block in enumerate(blocks):
                p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
                prefix = "• "
                if block.get("kind") == "answer":
                    prefix = "الإجابة: "
                elif block.get("kind") == "explanation":
                    prefix = "التفسير: "
                p.text = prefix + str(block.get("text") or "")
                p.alignment = PP_ALIGN.RIGHT
                p.font.size = Pt(20 if len(blocks) <= 5 else 17)

            refs = " · ".join(spec.get("source_refs") or [])
            if refs:
                footer = slide.shapes.add_textbox(Inches(0.6), Inches(6.9), Inches(12.0), Inches(0.35))
                _set_text(footer, refs, size=8)
        if edition == "teacher":
            _add_notes(slide, list(spec.get("speaker_notes") or []))

    stream = BytesIO()
    prs.save(stream)
    return stream.getvalue()


def pptx_preflight(data: bytes, expected_slide_count: int) -> dict:
    try:
        prs = Presentation(BytesIO(data))
    except Exception:
        return {"ready": False, "blocking_failures": ["valid_pptx"], "slide_count": 0}
    slide_count = len(prs.slides)
    blockers = []
    if slide_count != int(expected_slide_count):
        blockers.append("slide_count_matches_blueprint")
    if slide_count == 0:
        blockers.append("slides_present")
    return {
        "ready": not blockers,
        "blocking_failures": blockers,
        "slide_count": slide_count,
    }
