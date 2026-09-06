from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse

from .db import connect
from .main import app
from .security import require_admin

# Latest detailed official public physics structure verified during implementation.
# It is deliberately labelled as a reference baseline, not silently claimed to be
# the final 2026/2027 specification.
OFFICIAL_REFERENCE = {
    'academic_year': '2024/2025',
    'subject': 'الفيزياء',
    'total_questions': 46,
    'objective_questions': 44,
    'essay_questions': 2,
    'total_marks': 60,
    'objective_marks': 56,
    'essay_marks': 4,
    'reference_authority': 'وزارة التربية والتعليم والتعليم الفني المصرية',
    'reference_url': 'https://moe.gov.eg/ar/what-s-on/news/new-old/',
    'status': 'reference_baseline_until_newer_official_spec_is_registered',
}


def _context(con):
    return con.execute("""SELECT cv.id curriculum_version_id,cv.academic_year,cv.subject_id,cv.grade_level_id,t.id term_id
      FROM curriculum_versions cv JOIN academic_terms t ON t.curriculum_version_id=cv.id
      WHERE cv.subject_id=1 AND cv.grade_level_id=6 AND cv.active=TRUE
      ORDER BY cv.id DESC,t.id LIMIT 1""").fetchone()


def _eligible_clause():
    return """q.approved=TRUE
      AND q.accepted_answer IS NOT NULL AND btrim(q.accepted_answer)<>''
      AND q.question_type<>'unknown' AND q.difficulty<>'unclassified'
      AND q.lesson_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM question_assets a WHERE a.question_id=q.id
        AND a.document_id=q.document_id AND a.page_number=coalesce(q.source_page,q.page))
      AND EXISTS(SELECT 1 FROM question_concepts qc WHERE qc.question_id=q.id)
      AND EXISTS(SELECT 1 FROM question_skills qs WHERE qs.question_id=q.id)
      AND NOT EXISTS(SELECT 1 FROM question_review_notes qr WHERE qr.question_id=q.id AND qr.status='open')"""


def blueprint_readiness():
    with connect() as con:
        ctx=_context(con)
        if not ctx:
            return {'active':False,'reference':OFFICIAL_REFERENCE}
        ready=_eligible_clause()
        params=(ctx['subject_id'],ctx['grade_level_id'],ctx['curriculum_version_id'],ctx['term_id'])
        counts=con.execute("""SELECT count(*) total,
          count(*) FILTER(WHERE q.question_type='essay') essay,
          count(*) FILTER(WHERE q.question_type<>'essay') objective,
          count(DISTINCT q.lesson_id) lessons,
          count(DISTINCT q.difficulty) difficulties
          FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s""",params).fetchone()
        types=list(con.execute("""SELECT q.question_type label,count(*) n FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
          GROUP BY q.question_type ORDER BY n DESC""",params).fetchall())
        difficulties=list(con.execute("""SELECT q.difficulty label,count(*) n FROM questions q WHERE """+ready+"""
          AND q.subject_id=%s AND q.grade_level_id=%s AND q.curriculum_version_id=%s AND q.term_id=%s
          GROUP BY q.difficulty ORDER BY q.difficulty""",params).fetchall())
    objective=int(counts['objective'] or 0);essay=int(counts['essay'] or 0);total=int(counts['total'] or 0)
    exact=objective>=OFFICIAL_REFERENCE['objective_questions'] and essay>=OFFICIAL_REFERENCE['essay_questions']
    training=total>=OFFICIAL_REFERENCE['total_questions']
    gaps={
      'objective':max(0,OFFICIAL_REFERENCE['objective_questions']-objective),
      'essay':max(0,OFFICIAL_REFERENCE['essay_questions']-essay),
      'total':max(0,OFFICIAL_REFERENCE['total_questions']-total),
    }
    return {
      'active':True,'curriculum':dict(ctx),'reference':OFFICIAL_REFERENCE,
      'eligible':{'total':total,'objective':objective,'essay':essay,'lessons':int(counts['lessons'] or 0),'difficulties':int(counts['difficulties'] or 0)},
      'question_types':{r['label']:int(r['n']) for r in types},
      'difficulty':{r['label']:int(r['n']) for r in difficulties},
      'exact_official_shape_feasible':exact,
      'training_46_feasible':training,
      'gaps':gaps,
      'policy':'لا يتم تحويل أسئلة غير مقالية إلى مقالية أو اختراع أسئلة لسد المواصفة.',
    }


@app.get('/api/admin/exam-blueprint/physics',dependencies=[Depends(require_admin)])
def physics_exam_blueprint():
    return blueprint_readiness()


PAGE=r'''<!doctype html><html lang=ar dir=rtl><meta name=viewport content="width=device-width,initial-scale=1"><title>جاهزية محاكاة امتحان الفيزياء</title><style>
body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}main{max-width:1050px;margin:auto;padding:18px}.box{background:#fff;border-radius:16px;padding:16px;margin:12px 0;box-shadow:0 3px 14px #0001}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.card{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.n{font-size:28px;font-weight:800}.muted{color:#667085}.ok{color:#067647}.warn{color:#b54708}.bad{color:#b42318}</style><main>
<div class=box><a href="/admin/dashboard">لوحة التحكم</a> · <a href="/admin/question-bank-balance">توازن البنك</a> · <a href="/admin/quiz-builder">منشئ الاختبارات</a></div><div class=box><h1>جاهزية محاكاة امتحان الفيزياء</h1><p class=muted>المواصفة الرسمية المرجعية محفوظة كBaseline قابل للتحديث، ولا تُنسب تلقائيًا إلى 2026/2027 قبل اعتماد مصدر رسمي أحدث.</p><div id=ref></div></div><div class=box><h2>جاهزية البنك الحالي</h2><div id=cards class=grid></div><div id=status></div></div><div class=box><h2>الفجوات</h2><div id=gaps class=grid></div></div><script>function e(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}async function load(){let r=await fetch('/api/admin/exam-blueprint/physics');if(r.status===401){location.href='/admin/login';return}let x=await r.json(),z=x.reference;ref.innerHTML='<div class=card><b>مرجع '+e(z.academic_year)+'</b><div>'+z.total_questions+' سؤال: '+z.objective_questions+' موضوعي + '+z.essay_questions+' مقالي · '+z.total_marks+' درجة</div><div class=muted>'+e(z.reference_authority)+'</div></div>';let a=x.eligible;cards.innerHTML=[['جاهز كليًا',a.total],['موضوعي',a.objective],['مقالي',a.essay],['الدروس المغطاة',a.lessons],['مستويات الصعوبة',a.difficulties]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class=n>'+v[1]+'</div></div>').join('');status.innerHTML='<p class="'+(x.exact_official_shape_feasible?'ok':'warn')+'"><b>'+(x.exact_official_shape_feasible?'البنك قادر حاليًا على بناء الشكل المرجعي الكامل دون اختراع محتوى.':'الشكل المرجعي الكامل غير جاهز بعد؛ النظام لن يزيّف الأسئلة الناقصة.')+'</b></p>';gaps.innerHTML=[['نقص الموضوعي',x.gaps.objective],['نقص المقالي',x.gaps.essay],['نقص الإجمالي',x.gaps.total]].map(v=>'<div class=card><div class=muted>'+v[0]+'</div><div class="n '+(v[1]?'bad':'ok')+'">'+v[1]+'</div></div>').join('')}load()</script></main></html>'''

@app.get('/admin/exam-blueprint/physics',response_class=HTMLResponse)
def physics_exam_blueprint_page(): return PAGE
