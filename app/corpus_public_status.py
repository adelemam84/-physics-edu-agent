from __future__ import annotations

from .db import connect
from .main import app


@app.get('/api/current-curriculum/phase2-status')
def current_curriculum_phase2_status():
    with connect() as con:
        cv=con.execute("""SELECT id,academic_year FROM curriculum_versions
          WHERE subject_id=1 AND grade_level_id=6 AND active=TRUE ORDER BY id DESC LIMIT 1""").fetchone()
        if not cv:
            return {'active':False}
        qa=list(con.execute("""SELECT qr.reason_code,count(*) total
          FROM question_review_notes qr JOIN questions q ON q.id=qr.question_id
          WHERE q.curriculum_version_id=%s AND qr.status='open'
          GROUP BY qr.reason_code ORDER BY total DESC,qr.reason_code""",(cv['id'],)).fetchall())
        rows=con.execute("""SELECT
          count(*) total_questions,
          count(*) FILTER(WHERE q.approved=TRUE) approved_questions,
          count(*) FILTER(WHERE a.question_id IS NOT NULL) with_asset,
          count(*) FILTER(WHERE q.approved=FALSE AND a.question_id IS NOT NULL) pending_with_asset,
          count(*) FILTER(WHERE q.approved=FALSE AND a.question_id IS NULL) pending_without_asset,
          count(*) FILTER(WHERE q.approved=FALSE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>'') pending_with_answer,
          count(*) FILTER(WHERE q.approved=FALSE AND q.question_type<>'unknown' AND q.difficulty<>'unclassified') pending_classified
          FROM questions q LEFT JOIN question_assets a ON a.question_id=q.id
          WHERE q.curriculum_version_id=%s""",(cv['id'],)).fetchone()
        types=list(con.execute("""SELECT q.question_type,count(*) total,count(*) FILTER(WHERE q.approved) approved
          FROM questions q WHERE q.curriculum_version_id=%s GROUP BY q.question_type ORDER BY total DESC""",(cv['id'],)).fetchall())
        quizzes=con.execute("""SELECT count(*) total,count(*) FILTER(WHERE published=TRUE) published
          FROM quizzes WHERE curriculum_version_id=%s""",(cv['id'],)).fetchone()
    return {
      'active':True,'academic_year':cv['academic_year'],
      'questions':dict(rows),
      'qa_open_by_reason':[dict(x) for x in qa],
      'question_types':[dict(x) for x in types],
      'quizzes':dict(quizzes),
      'policy':'aggregate_only_no_question_content',
    }
