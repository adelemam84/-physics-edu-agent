from __future__ import annotations

from collections import defaultdict

from ..db import connect


def _active_context(con):
    return con.execute(
        """SELECT cv.id curriculum_version_id,cv.subject_id,cv.grade_level_id,t.id term_id
           FROM curriculum_versions cv
           JOIN academic_terms t ON t.curriculum_version_id=cv.id
           WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE
           ORDER BY cv.id DESC,t.id LIMIT 1"""
    ).fetchone()


def _eligible_rows(con, ctx):
    return list(con.execute(
        """SELECT q.id,q.lesson_id,q.difficulty,q.question_type,l.sort_order lesson_order
           FROM questions q JOIN lessons l ON l.id=q.lesson_id
           WHERE q.approved=TRUE
             AND q.subject_id=%s AND q.grade_level_id=%s
             AND q.curriculum_version_id=%s AND q.term_id=%s
             AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
             AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
             AND EXISTS(SELECT 1 FROM question_assets a
               WHERE a.question_id=q.id AND a.document_id=q.document_id
                 AND a.page_number=coalesce(q.source_page,q.page))
             AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
             AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
             AND NOT EXISTS(SELECT 1 FROM question_review_notes qr
               WHERE qr.question_id=q.id AND qr.status='open')
           ORDER BY l.sort_order,l.id,q.id""",
        (ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])
    ).fetchall())


def _round_robin(rows, count: int, reverse: bool = False):
    by_lesson: dict[int, list[dict]] = defaultdict(list)
    order: list[int] = []
    for r in rows:
        lid=int(r['lesson_id'])
        if lid not in by_lesson:
            order.append(lid)
        by_lesson[lid].append(dict(r))
    if reverse:
        for lid in by_lesson:
            by_lesson[lid].reverse()
        order=list(reversed(order))
    selected=[]
    depth=0
    while len(selected)<count:
        progressed=False
        for lid in order:
            bucket=by_lesson[lid]
            if depth < len(bucket):
                selected.append(bucket[depth]);progressed=True
                if len(selected)>=count: break
        if not progressed: break
        depth+=1
    return selected


def _ensure_quiz(con, ctx, title: str, count: int, reverse: bool = False):
    old=con.execute("SELECT id,published,lifecycle_status FROM quizzes WHERE title=%s AND curriculum_version_id=%s",(title,ctx['curriculum_version_id'])).fetchone()
    if old:
        return {'id':old['id'],'created':False,'published':bool(old['published']),'status':old['lifecycle_status']}
    rows=_eligible_rows(con,ctx)
    if len(rows)<count:
        return {'created':False,'published':False,'status':'insufficient_bank','available':len(rows),'required':count}
    picked=_round_robin(rows,count,reverse)
    if len(picked)<count:
        return {'created':False,'published':False,'status':'insufficient_distribution','available':len(picked),'required':count}
    quiz=con.execute("""INSERT INTO quizzes(title,published,lifecycle_status,duration_minutes,max_attempts,retry_wait_minutes,score_policy,
                    subject_id,grade_level_id,curriculum_version_id,term_id)
             VALUES(%s,FALSE,'draft',30,2,0,'highest',%s,%s,%s,%s) RETURNING id""",
        (title,ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])).fetchone()
    for pos,r in enumerate(picked,1):
        con.execute("INSERT INTO quiz_questions(quiz_id,question_id,position) VALUES(%s,%s,%s)",(quiz['id'],r['id'],pos))
    con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,details)
             VALUES(%s,'create',NULL,'draft','{\"source\":\"phase2_auto_balanced\"}'::jsonb)""",(quiz['id'],))
    return {'id':quiz['id'],'created':True,'published':False,'status':'draft'}


def run_phase2_bootstrap():
    """Idempotent production hardening after DB migration.

    Visual QA reconciliation/approval runs in init_db. This function only expands
    the current source-backed assessment set, then reuses the existing quality and
    publication gates. A quiz that does not pass those gates remains unpublished.
    """
    with connect() as con:
        ctx=_active_context(con)
        if not ctx:
            return {'active':False}
        candidates=[
            _ensure_quiz(con,ctx,'اختبار 2026/2027 — تدريب شامل (أ)',20,False),
            _ensure_quiz(con,ctx,'اختبار 2026/2027 — تدريب شامل (ب)',20,True),
        ]
    # Reuse the production quality gate; never bypass publication checks.
    from ..quiz_builder import quiz_quality_check, publish_quiz, review_quiz
    results=[]
    for item in candidates:
        qid=item.get('id')
        if not qid:
            results.append(item);continue
        if item.get('published'):
            results.append(item);continue
        quality=quiz_quality_check(int(qid))
        if quality.get('ready'):
            pub=publish_quiz(int(qid))
            results.append({**item,'published':True,'status':'published','quality_score':pub.get('quality_score')})
        else:
            reviewed=review_quiz(int(qid))
            results.append({**item,'published':False,'status':reviewed.get('lifecycle_status'),'quality_score':reviewed.get('quality_score')})
    return {'active':True,'quizzes':results}
