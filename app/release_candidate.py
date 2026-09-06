from __future__ import annotations

from .db import connect

RC_VERSION = "1.0-RC1"

def source_corpus_benchmark() -> dict:
    """Measure readiness of the real PDF-backed question corpus already stored in production."""
    with connect() as con:
        total = con.execute("SELECT count(*) c FROM questions").fetchone()["c"]
        approved = con.execute("SELECT count(*) c FROM questions WHERE approved=TRUE").fetchone()["c"]
        rows = con.execute("""
            SELECT
              count(*) FILTER (WHERE q.approved=TRUE) approved,
              count(*) FILTER (WHERE q.approved=TRUE AND q.document_id IS NOT NULL AND coalesce(q.source_page,q.page) IS NOT NULL) source_linked,
              count(*) FILTER (WHERE q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'') answered,
              count(*) FILTER (WHERE q.approved=TRUE AND q.lesson_id IS NOT NULL AND q.unit_id IS NOT NULL
                 AND q.subject_id IS NOT NULL AND q.grade_level_id IS NOT NULL
                 AND q.curriculum_version_id IS NOT NULL AND q.term_id IS NOT NULL) academically_tagged,
              count(*) FILTER (WHERE q.approved=TRUE AND EXISTS(
                 SELECT 1 FROM question_assets a WHERE a.question_id=q.id
              )) asset_linked
            FROM questions q
        """).fetchone()
        review_docs = con.execute(
            "SELECT count(*) c FROM documents WHERE status IN ('review_required','extraction_review_required')"
        ).fetchone()["c"]

    denominator = max(int(rows["approved"] or 0), 1)
    metrics = {
        "approved_questions": int(rows["approved"] or 0),
        "source_linked_percent": round(100 * int(rows["source_linked"] or 0) / denominator, 2),
        "answer_coverage_percent": round(100 * int(rows["answered"] or 0) / denominator, 2),
        "academic_tagging_percent": round(100 * int(rows["academically_tagged"] or 0) / denominator, 2),
        "asset_linkage_percent": round(100 * int(rows["asset_linked"] or 0) / denominator, 2),
        "documents_needing_review": int(review_docs or 0),
        "total_questions": int(total or 0),
        "approved_count": int(approved or 0),
    }
    gates = {
        "has_real_questions": total > 0,
        "has_approved_questions": approved > 0,
        "source_grounding_90": metrics["source_linked_percent"] >= 90,
        "answer_coverage_90": metrics["answer_coverage_percent"] >= 90,
        "academic_tagging_90": metrics["academic_tagging_percent"] >= 90,
    }
    return {"version": RC_VERSION, "metrics": metrics, "gates": gates, "passed": all(gates.values())}

def release_readiness() -> dict:
    try:
        corpus = source_corpus_benchmark()
    except RuntimeError as exc:
        corpus = {"version": RC_VERSION, "metrics": {}, "gates": {"database_available": False}, "passed": False, "error": str(exc)}
    blockers = [k for k, ok in corpus["gates"].items() if not ok]
    return {
        "version": RC_VERSION,
        "status": "ready_for_live_acceptance" if not blockers else "corpus_hardening_required",
        "source_corpus": corpus,
        "blockers": blockers,
        "required_before_v1": [
            "real-source corpus gates",
            "preview deployment smoke test",
            "mobile/RTL acceptance",
            "production promotion only after preview passes",
        ],
    }
