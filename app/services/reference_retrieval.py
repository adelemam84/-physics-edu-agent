from __future__ import annotations

from collections import Counter, defaultdict
import math
import re


_STOP = {
    'من','في','على','إلى','الى','عن','هو','هي','هذا','هذه','ذلك','تلك','ثم','او','أو',
    'مع','كان','تكون','يكون','كل','بين','عند','the','and','of','to','a','an','is','are',
}


def _normalize_word(word: str) -> str:
    value = (word or '').lower().strip()
    value = value.replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ى','ي')
    value = value.replace('ؤ','و').replace('ئ','ي')
    value = re.sub(r'[\u064b-\u065f\u0670]', '', value)
    return value


def ordered_tokens(text: str) -> list[str]:
    words = re.findall(r'[\w\u0600-\u06ff]+', text or '', flags=re.UNICODE)
    out = []
    for word in words:
        token = _normalize_word(word)
        if len(token) > 2 and token not in _STOP:
            out.append(token)
    return out


def token_set(text: str) -> set[str]:
    return set(ordered_tokens(text))


def _query_bigrams(tokens: list[str]) -> set[tuple[str,str]]:
    return {(tokens[i], tokens[i+1]) for i in range(len(tokens)-1)}


def rank_reference_pages(query: str, pages: list[dict], limit: int = 8) -> list[dict]:
    """Deterministic source-only retrieval with BM25, coverage, phrase and continuity signals."""
    limit = min(20, max(1, int(limit)))
    q_tokens = ordered_tokens(query)
    if not q_tokens or not pages:
        return []

    docs_tokens: list[list[str]] = [ordered_tokens(str(p.get('page_text') or '')) for p in pages]
    lengths = [len(x) for x in docs_tokens]
    avg_len = sum(lengths) / max(1, len(lengths))
    df: Counter[str] = Counter()
    for tokens in docs_tokens:
        df.update(set(tokens))

    q_counts = Counter(q_tokens)
    q_unique = set(q_tokens)
    q_bigrams = _query_bigrams(q_tokens)
    n_docs = len(pages)
    raw = []

    for idx, (page, tokens) in enumerate(zip(pages, docs_tokens)):
        if not tokens:
            continue
        tf = Counter(tokens)
        bm25 = 0.0
        for term, qtf in q_counts.items():
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1.0 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            k1, b = 1.35, 0.72
            denom = freq + k1 * (1.0 - b + b * (len(tokens) / max(avg_len, 1.0)))
            bm25 += idf * ((freq * (k1 + 1.0)) / max(denom, 1e-9)) * (1.0 + 0.12 * min(qtf - 1, 3))

        matched = q_unique & set(tokens)
        coverage = len(matched) / max(1, len(q_unique))

        page_bigrams = _query_bigrams(tokens)
        phrase_matches = len(q_bigrams & page_bigrams)
        phrase = phrase_matches / max(1, len(q_bigrams))

        # Query-term density rewards pages where matching evidence is concentrated.
        match_positions = [i for i,t in enumerate(tokens) if t in q_unique]
        density = 0.0
        if match_positions:
            span = max(match_positions) - min(match_positions) + 1
            density = min(1.0, len(match_positions) / max(1, span))

        raw.append({
            'idx': idx,
            'bm25': bm25,
            'coverage': coverage,
            'phrase': phrase,
            'density': density,
            'matched_terms': sorted(matched),
            'phrase_matches': phrase_matches,
        })

    if not raw:
        return []
    max_bm25 = max((x['bm25'] for x in raw), default=0.0) or 1.0
    base_by_idx = {}
    for item in raw:
        bm25_norm = item['bm25'] / max_bm25
        base = 0.56 * bm25_norm + 0.27 * item['coverage'] + 0.11 * item['phrase'] + 0.06 * item['density']
        item['base_score'] = base
        base_by_idx[item['idx']] = base

    ranked = []
    for item in raw:
        idx = item['idx']
        neighbor = 0.0
        for adjacent in (idx-1, idx+1):
            neighbor = max(neighbor, base_by_idx.get(adjacent, 0.0))
        continuity = min(0.08, neighbor * 0.08)
        score = min(1.0, item['base_score'] + continuity)
        if score <= 0:
            continue
        page = pages[idx]
        ranked.append({
            **page,
            'score': round(score, 4),
            'retrieval': {
                'method': 'deterministic_hybrid_v1',
                'bm25': round(item['bm25'] / max_bm25, 4),
                'coverage': round(item['coverage'], 4),
                'phrase': round(item['phrase'], 4),
                'density': round(item['density'], 4),
                'adjacent_context_bonus': round(continuity, 4),
                'matched_terms': item['matched_terms'],
                'phrase_matches': item['phrase_matches'],
            },
        })

    ranked.sort(key=lambda x: (-x['score'], str(x.get('document_id') or ''), int(x.get('page_number') or 0)))
    return ranked[:limit]


def retrieval_contract() -> dict:
    return {
        'method': 'deterministic_hybrid_v1',
        'signals': ['bm25','query_coverage','phrase_order','term_density','adjacent_page_continuity'],
        'external_knowledge': False,
        'external_embedding_provider': False,
        'page_provenance_preserved': True,
        'scientific_content_rewrite': False,
    }
