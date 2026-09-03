import re

def normalize_answer(value: str | None) -> str:
    if value is None:
        return ""
    v = value.strip().casefold()
    v = v.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    v = v.replace("ى", "ي").replace("ة", "ه")
    v = re.sub(r"[\s،,.;:]+", "", v)
    return v

def grade_exact(student_answer: str | None, accepted_answer: str | None) -> bool | None:
    if not accepted_answer:
        return None
    return normalize_answer(student_answer) == normalize_answer(accepted_answer)
