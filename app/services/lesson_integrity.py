from __future__ import annotations

import hashlib
import json


def review_source_hash(transcript: str, structured: dict) -> str:
    """Hash exactly what a second reviewer evaluated.

    Final-quality checks can then reject a reviewer result after any content change,
    regardless of which endpoint performed that change.
    """
    canonical = json.dumps(
        {
            'transcript': transcript or '',
            'structured': structured or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()
