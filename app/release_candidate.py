from __future__ import annotations

from .db import connect

RC_VERSION = "1.3.0"

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
            "SELECT count(*) c FROM documents WHERE status IN ('review_required','extraction_review_required','visual_review_required','source_review_required')"
        ).fetchone()["c"]
        qa = con.execute("""SELECT count(*) FILTER(WHERE status='open') open,
          count(*) FILTER(WHERE status='open' AND severity='critical') critical,
          count(*) FILTER(WHERE status='resolved') resolved FROM question_review_notes""").fetchone()

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
        "candidate_questions": int(total or 0) - int(approved or 0),
        "source_documents": 0,
        "qa_open": int(qa["open"] or 0),
        "qa_critical": int(qa["critical"] or 0),
        "qa_resolved": int(qa["resolved"] or 0),
    }
    with connect() as con:
        metrics["source_documents"] = int(con.execute("SELECT count(*) c FROM documents WHERE storage_url IS NOT NULL OR EXISTS(SELECT 1 FROM document_files f WHERE f.document_id=documents.id)").fetchone()["c"] or 0)
        active=con.execute("""SELECT cv.id,cv.academic_year,
          (SELECT count(*) FROM documents d WHERE d.curriculum_version_id=cv.id) source_docs,
          (SELECT count(*) FROM questions q WHERE q.curriculum_version_id=cv.id AND q.approved=TRUE) approved_questions
          FROM curriculum_versions cv WHERE cv.active=TRUE ORDER BY cv.id DESC LIMIT 1""").fetchone()
        metrics["active_curriculum_id"] = int(active["id"]) if active else None
        metrics["active_curriculum_year"] = active["academic_year"] if active else None
        metrics["active_source_documents"] = int(active["source_docs"] or 0) if active else 0
        metrics["active_approved_questions"] = int(active["approved_questions"] or 0) if active else 0
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
        "status": "released" if not blockers else "corpus_hardening_required",
        "source_corpus": corpus,
        "blockers": blockers,
        "required_before_v1": [] if not blockers else [
            "real-source corpus gates",
            "source review and approval",
        ],
    }
