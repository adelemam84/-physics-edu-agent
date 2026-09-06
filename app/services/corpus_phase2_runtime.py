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


def _phase2_quality(con, quiz_id: int):
    rows=list(con.execute("""SELECT q.id,q.lesson_id,q.difficulty,q.question_type,q.approved,
      q.document_id,coalesce(q.source_page,q.page) source_page,q.accepted_answer,
      EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id AND a.document_id=q.document_id
        AND a.page_number=coalesce(q.source_page,q.page)) asset_ok,
      EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id) has_concept,
      EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id) has_skill,
      EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open') qa_open
      FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id
      WHERE qq.quiz_id=%s ORDER BY qq.position""",(quiz_id,)).fetchall())
    if not rows:
        return {'ready':False,'score':0,'reason':'empty'}
    lessons={int(r['lesson_id']) for r in rows if r['lesson_id'] is not None}
    diffs={r['difficulty'] for r in rows if r['difficulty']}
    types={r['question_type'] for r in rows if r['question_type']}
    source_ok=all(bool(r['approved'] and r['document_id'] and r['source_page'] and r['accepted_answer'] and r['asset_ok'] and r['has_concept'] and r['has_skill'] and not r['qa_open']) for r in rows)
    max_lesson=max((sum(1 for r in rows if r['lesson_id']==lid) for lid in lessons),default=len(rows))/len(rows)
    checks={
      'count_20':len(rows)==20,
      'source_integrity':source_ok,
      'lesson_coverage':len(lessons)>=min(4,len(rows)),
      'difficulty_mix':len(diffs)>=2,
      'type_mix':len(types)>=1,
      'lesson_concentration':max_lesson<=0.60,
    }
    score=round(sum(1 for v in checks.values() if v)*100/len(checks))
    return {'ready':all(checks.values()),'score':score,'checks':checks}


def _publish_if_ready(con, item):
    qid=item.get('id')
    if not qid or item.get('published'):
        return item
    quality=_phase2_quality(con,int(qid))
    target='published' if quality['ready'] else 'quality_review'
    if quality['ready']:
        con.execute("""UPDATE quizzes SET published=TRUE,lifecycle_status='published',quality_score=%s,
          ready_at=coalesce(ready_at,now()),published_at=coalesce(published_at,now()),archived_at=NULL WHERE id=%s""",
          (quality['score'],qid))
    else:
        con.execute("UPDATE quizzes SET published=FALSE,lifecycle_status='quality_review',quality_score=%s WHERE id=%s",(quality['score'],qid))
    con.execute("""INSERT INTO quiz_audit_log(quiz_id,action,from_status,to_status,quality_score,details)
      VALUES(%s,'phase2_quality_gate','draft',%s,%s,'{\"automatic\":true,\"gate\":\"phase2_strict\"}'::jsonb)""",
      (qid,target,quality['score']))
    return {**item,'published':quality['ready'],'status':target,'quality_score':quality['score'],'quality':quality}


def run_phase2_bootstrap():
    """Idempotent production hardening after DB migration.

    Visual QA reconciliation/approval runs in init_db. This function expands the
    current source-backed assessment set and uses a strict local publication gate.
    It avoids importing request-layer route functions during FastAPI startup.
    """
    with connect() as con:
        ctx=_active_context(con)
        if not ctx:
            return {'active':False}
        candidates=[
            _ensure_quiz(con,ctx,'اختبار 2026/2027 — تدريب شامل (أ)',20,False),
            _ensure_quiz(con,ctx,'اختبار 2026/2027 — تدريب شامل (ب)',20,True),
        ]
        results=[_publish_if_ready(con,item) for item in candidates]
    return {'active':True,'quizzes':results}
