from __future__ import annotations
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from .main import app
from .db import connect
from .security import require_admin

class CurriculumCreate(BaseModel):
    subject_id:int
    grade_level_id:int
    academic_year:str
    version_label:str="official"

class TermCreate(BaseModel):
    curriculum_version_id:int
    term_number:int
    name_ar:str

class UnitCreate(BaseModel):
    term_id:int
    title:str
    sort_order:int=0

@app.get("/api/academic/catalog")
def academic_catalog():
    with connect() as con:
        return {
            "subjects": list(con.execute("SELECT id,code,name_ar,name_en,sort_order FROM subjects WHERE active=TRUE ORDER BY sort_order,id").fetchall()),
            "grades": list(con.execute("SELECT id,stage_code,grade_number,name_ar,sort_order FROM grade_levels WHERE active=TRUE ORDER BY sort_order,id").fetchall()),
            "curricula": list(con.execute("""SELECT c.id,c.subject_id,c.grade_level_id,c.academic_year,c.version_label,c.active,
                s.code subject_code,s.name_ar subject_name,g.name_ar grade_name
                FROM curriculum_versions c JOIN subjects s ON s.id=c.subject_id JOIN grade_levels g ON g.id=c.grade_level_id
                ORDER BY c.academic_year DESC,s.sort_order,g.sort_order,c.id""").fetchall()),
            "terms": list(con.execute("SELECT id,curriculum_version_id,term_number,name_ar,sort_order FROM academic_terms ORDER BY curriculum_version_id,sort_order,term_number").fetchall()),
            "units": list(con.execute("SELECT id,term_id,title,sort_order FROM units ORDER BY term_id,sort_order,id").fetchall())
        }

@app.post("/api/academic/curricula",dependencies=[Depends(require_admin)])
def create_curriculum(p:CurriculumCreate):
    year=p.academic_year.strip()
    if not year: raise HTTPException(400,"السنة الدراسية مطلوبة")
    with connect() as con:
        return con.execute("""INSERT INTO curriculum_versions(subject_id,grade_level_id,academic_year,version_label)
          VALUES(%s,%s,%s,%s)
          ON CONFLICT(subject_id,grade_level_id,academic_year,version_label)
          DO UPDATE SET active=TRUE RETURNING *""",(p.subject_id,p.grade_level_id,year,p.version_label.strip() or "official")).fetchone()

@app.post("/api/academic/terms",dependencies=[Depends(require_admin)])
def create_term(p:TermCreate):
    if p.term_number not in (1,2): raise HTTPException(400,"رقم الترم يجب أن يكون 1 أو 2")
    with connect() as con:
        return con.execute("""INSERT INTO academic_terms(curriculum_version_id,term_number,name_ar,sort_order)
          VALUES(%s,%s,%s,%s) ON CONFLICT(curriculum_version_id,term_number)
          DO UPDATE SET name_ar=excluded.name_ar,sort_order=excluded.sort_order RETURNING *""",
          (p.curriculum_version_id,p.term_number,p.name_ar.strip(),p.term_number*10)).fetchone()

@app.post("/api/academic/units",dependencies=[Depends(require_admin)])
def create_unit(p:UnitCreate):
    if not p.title.strip(): raise HTTPException(400,"اسم الوحدة مطلوب")
    with connect() as con:
        return con.execute("INSERT INTO units(term_id,title,sort_order) VALUES(%s,%s,%s) RETURNING *",(p.term_id,p.title.strip(),p.sort_order)).fetchone()

@app.get("/api/academic/coverage",dependencies=[Depends(require_admin)])
def academic_coverage(subject_id:int|None=None,grade_level_id:int|None=None,curriculum_version_id:int|None=None):
    sql="""SELECT s.name_ar subject,g.name_ar grade,c.academic_year,t.name_ar term,u.title unit,l.title lesson,
      count(q.id) total_questions,count(q.id) FILTER(WHERE q.approved) approved_questions,
      count(distinct qc.concept_id) covered_concepts
      FROM lessons l LEFT JOIN subjects s ON s.id=l.subject_id LEFT JOIN grade_levels g ON g.id=l.grade_level_id
      LEFT JOIN curriculum_versions c ON c.id=l.curriculum_version_id LEFT JOIN academic_terms t ON t.id=l.term_id
      LEFT JOIN units u ON u.id=l.unit_id LEFT JOIN questions q ON q.lesson_id=l.id
      LEFT JOIN question_concepts qc ON qc.question_id=q.id WHERE 1=1"""
    params=[]
    if subject_id is not None: sql+=" AND l.subject_id=%s"; params.append(subject_id)
    if grade_level_id is not None: sql+=" AND l.grade_level_id=%s"; params.append(grade_level_id)
    if curriculum_version_id is not None: sql+=" AND l.curriculum_version_id=%s"; params.append(curriculum_version_id)
    sql+=" GROUP BY s.name_ar,g.name_ar,c.academic_year,t.name_ar,u.title,l.id,l.title,l.sort_order ORDER BY l.sort_order,l.id"
    with connect() as con:
        return list(con.execute(sql,params).fetchall())
