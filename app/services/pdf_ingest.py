from pathlib import Path
import fitz
import re

# Question boundaries must be explicit. We intentionally do NOT accept a bare number
# followed by whitespace because scientific PDFs contain many values such as
# "1 mol", "10 ml", "200 V", etc. Those were previously misclassified as
# question starts.
#
# Accepted examples:
#   1) ...   2. ...   (18) ...   [7] ...
#   سؤال 5 ...   س 12: ...
# Arabic-Indic digits are supported as well.
QUESTION_LINE_START = re.compile(
    r"(?m)^\\s*\\(\\s*([0-9٠-٩]{1,3})\\s*\\)\\s+"
)

QUESTION_START = re.compile(
    r"(?<![\w\d])(?:"
    r"(?:س(?:ؤال)?\s*)[\(\[]?([0-9٠-٩]{1,3})[\)\]]?[\.\-:،)]?"
    r"|"
    r"[\(\[]([0-9٠-٩]{1,3})[\)\]]"
    r"|"
    r"([0-9٠-٩]{1,3})[\)\.\-:،]"
    r")\s*",
    re.MULTILINE,
)


def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    doc = fitz.open(pdf_path)
    try:
        return [(idx, page.get_text("text")) for idx, page in enumerate(doc, start=1)]
    finally:
        doc.close()


def _question_number(match: re.Match) -> int | None:
    raw = next((g for g in match.groups() if g), None)
    if not raw:
        return None
    # Convert Arabic-Indic digits to ASCII before int().
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    try:
        return int(raw.translate(trans))
    except ValueError:
        return None


def detect_verbatim_question_candidates(page_text: str) -> list[str]:
    """Split a PDF page into conservative verbatim question candidates.

    Scientific content is never rewritten. The only normalization here is
    trimming outer whitespace around each extracted block.

    We prefer false negatives over false positives: a marker must look like an
    actual question number, not a measurement or formula value.
    """
    # Prefer explicit numbered question markers at the start of a text line.
    # This avoids treating worked-solution labels such as # (1), formula values,
    # or inline numbered steps as new questions. Some older PDFs only expose
    # inline markers, so the conservative legacy matcher remains a fallback.
    line_matches = list(QUESTION_LINE_START.finditer(page_text))
    matches = line_matches if line_matches else list(QUESTION_START.finditer(page_text))
    if not matches:
        return []

    candidates: list[str] = []
    for i, match in enumerate(matches):
        qn = _question_number(match)
        if qn is None or qn == 0 or qn > 200:
            continue

        start = match.start()
        # End at the next explicit question marker, regardless of line layout.
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
        block = page_text[start:end].strip()

        # Tiny fragments are almost always headers/footer artifacts.
        if len(block) < 20:
            continue
        candidates.append(block)

    return candidates
