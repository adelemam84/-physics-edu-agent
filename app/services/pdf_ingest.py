from pathlib import Path
import fitz
import re

QUESTION_START = re.compile(
    r"(?m)^\s*(?:س(?:ؤال)?\s*)?[\(\[]?([0-9٠-٩]{1,3})[\)\].\-:،]?\s+"
)

def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    doc = fitz.open(pdf_path)
    pages = []
    for idx, page in enumerate(doc, start=1):
        pages.append((idx, page.get_text("text")))
    return pages

def detect_verbatim_question_candidates(page_text: str) -> list[str]:
    matches = list(QUESTION_START.finditer(page_text))
    if not matches:
        return []
    candidates = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
        block = page_text[start:end].strip()
        if len(block) >= 12:
            candidates.append(block)
    return candidates
