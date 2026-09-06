from __future__ import annotations

# Runtime-compatible patch for the existing FastAPI route object. We replace the
# function code in-place so the already-registered route and publish workflow both
# use the PostgreSQL-safe nullable lesson predicate without duplicating routes.
from . import quiz_builder


def _safe_quiz_quality_check(quiz_id: int):
    with connect() as con:
        quiz=con.execute("SELECT * FROM quizzes WHERE id=%s",(quiz_id,)).fetchone()
        if not quiz: raise HTTPException(404,'Quiz not found')
        rows=list(con.execute("""SELECT q.id,q.lesson_id,q.difficulty,q.question_type,q.approved,
          q.document_id,coalesce(q.source_page,q.page) source_page,q.accepted_answer,
          EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open') qa_open,
          array(SELECT qc.concept_id FROM question_concepts qc WHERE qc.question_id=q.id) concepts,
          array(SELECT qs.skill_id FROM question_skills qs WHERE qs.question_id=q.id) skills
          FROM quiz_questions qq JOIN questions q ON q.id=qq.question_id
          WHERE qq.quiz_id=%s ORDER BY qq.position""",(quiz_id,)).fetchall())
        scope_lesson=quiz['lesson_id']
        expected=con.execute("""SELECT count(DISTINCT q.lesson_id) n,
          count(DISTINCT q.difficulty) diff_n,count(DISTINCT q.question_type) type_n,
          count(DISTINCT qc.concept_id) concept_n,count(DISTINCT qs.skill_id) skill_n
          FROM questions q
          LEFT JOIN question_concepts qc ON qc.question_id=q.id
          LEFT JOIN question_skills qs ON qs.question_id=q.id
          WHERE q.approved=TRUE AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
            AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
            AND (%s::bigint IS NULL OR q.lesson_id=%s::bigint)
            AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')""",
          (quiz['subject_id'],quiz['grade_level_id'],quiz['curriculum_version_id'],quiz['term_id'],scope_lesson,scope_lesson)).fetchone()
    n=len(rows)
    if not n:return {'quiz_id':quiz_id,'ready':False,'score':0,'checks':[],'message':'الاختبار بلا أسئلة'}
    lessons={r['lesson_id'] for r in rows if r['lesson_id'] is not None};concepts={x for r in rows for x in (r['concepts'] or [])};skills={x for r in rows for x in (r['skills'] or [])}
    diffs={};types={}
    for r in rows: diffs[r['difficulty']]=diffs.get(r['difficulty'],0)+1;types[r['question_type']]=types.get(r['question_type'],0)+1
    lesson_target=max(1,min(n,int(expected['n'] or 0) or len(lessons) or 1));lesson_cov=min(1,len(lessons)/lesson_target)
    concept_target=max(1,min(n,int(expected['concept_n'] or 0) or len(concepts) or 1));concept_cov=min(1,len(concepts)/concept_target)
    skill_target=max(1,min(n,3,int(expected['skill_n'] or 0) or len(skills) or 1));skill_cov=min(1,len(skills)/skill_target)
    required_diffs=max(1,min(3,n,int(expected['diff_n'] or 0) or 1));required_types=max(1,min(2,n,int(expected['type_n'] or 0) or 1))
    max_lesson=max((sum(1 for r in rows if r['lesson_id']==x) for x in lessons),default=n)/n
    max_concept=max((sum(1 for r in rows if x in (r['concepts'] or [])) for x in concepts),default=n)/n
    source_ready=all(r['document_id'] is not None and r['source_page'] is not None for r in rows)
    approval_ready=all(bool(r['approved']) for r in rows);answer_ready=all(r['accepted_answer'] is not None and str(r['accepted_answer']).strip() for r in rows);qa_clear=all(not r['qa_open'] for r in rows)
    checks=[
      {'id':'source_grounding','label':'كل الأسئلة مرتبطة بالمصدر','ok':source_ready,'value':source_ready},
      {'id':'approval_gate','label':'كل الأسئلة معتمدة','ok':approval_ready,'value':approval_ready},
      {'id':'answer_coverage','label':'كل الأسئلة لها إجابة معتمدة','ok':answer_ready,'value':answer_ready},
      {'id':'qa_clear','label':'لا توجد ملاحظات QA مفتوحة','ok':qa_clear,'value':qa_clear},
      {'id':'lesson_coverage','label':'تغطية الدروس المتاحة','ok':lesson_cov>=.8,'value':round(lesson_cov*100)},
      {'id':'concept_coverage','label':'تنوع المفاهيم المتاحة','ok':concept_cov>=.8,'value':len(concepts)},
      {'id':'skill_coverage','label':'تنوع المهارات المتاحة','ok':skill_cov>=.67,'value':len(skills)},
      {'id':'difficulty_mix','label':'تنوع مستويات الصعوبة المتاحة','ok':len(diffs)>=required_diffs,'value':diffs},
      {'id':'question_type_mix','label':'تنوع أنواع الأسئلة المتاحة','ok':len(types)>=required_types,'value':types},
      {'id':'lesson_concentration','label':'عدم التركز في درس واحد','ok':max_lesson<=.6 or len(lessons)==1,'value':round(max_lesson*100)},
      {'id':'concept_concentration','label':'عدم التركز في مفهوم واحد','ok':max_concept<=.6 or len(concepts)==1,'value':round(max_concept*100)}]
    score=round(sum(1 for x in checks if x['ok'])*100/len(checks))
    return {'quiz_id':quiz_id,'ready':all(x['ok'] for x in checks),'score':score,'checks':checks,'coverage':{'lessons':len(lessons),'concepts':len(concepts),'skills':len(skills)},'difficulty':diffs,'question_types':types,'student_visible':False}


# These names must resolve in quiz_builder globals because the function code is
# installed into the original registered function object.
quiz_builder.quiz_quality_check.__code__ = _safe_quiz_quality_check.__code__
