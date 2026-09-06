from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from .db import connect
from .main import app
from .security import require_admin

EXPLANATORY_KINDS={"lesson","explanation","textbook","notes"}

class LessonSourceMap(BaseModel):
    lesson_id:int
    start_page:int
    end_page:int

@app.get("/api/admin/lesson-sources",dependencies=[Depends(require_admin)])
def lesson_sources(document_id:int|None=None,lesson_id:int|None=None):
    sql="""SELECT m.id,m.document_id,m.lesson_id,m.start_page,m.end_page,m.mapping_status,
      (m.mapping_status='approved') approved,m.confidence,m.notes,m.created_at,m.updated_at,
      d.filename,d.kind,d.status,l.title lesson_title,u.title unit_title
      FROM lesson_source_mappings m
      JOIN documents d ON d.id=m.document_id
      JOIN lessons l ON l.id=m.lesson_id
      LEFT JOIN units u ON u.id=l.unit_id
      WHERE 1=1"""
    params=[]
    if document_id is not None:
        sql+=" AND m.document_id=%s"
        params.append(document_id)
    if lesson_id is not None:
        sql+=" AND m.lesson_id=%s"
        params.append(lesson_id)
    sql+=" ORDER BY d.id,l.sort_order,m.start_page"
    with connect() as con:
        return list(con.execute(sql,params).fetchall())

@app.post("/api/admin/documents/{document_id}/lesson-source",dependencies=[Depends(require_admin)])
def map_lesson_source(document_id:int,p:LessonSourceMap):
    if p.start_page<1 or p.end_page<p.start_page:
        raise HTTPException(400,"نطاق الصفحات غير صحيح")
    with connect() as con:
        doc=con.execute("""SELECT id,filename,kind,status,subject_id,grade_level_id,curriculum_version_id,term_id
          FROM documents WHERE id=%s""",(document_id,)).fetchone()
        if not doc:
            raise HTTPException(404,"Document not found")
        if doc["kind"] not in EXPLANATORY_KINDS:
            raise HTTPException(400,"الملف ليس مصدر شرح")
        lesson=con.execute("""SELECT id,title,subject_id,grade_level_id,curriculum_version_id,term_id,unit_id
          FROM lessons WHERE id=%s""",(p.lesson_id,)).fetchone()
        if not lesson:
            raise HTTPException(404,"الدرس غير موجود")
        bad=[k for k in ("subject_id","grade_level_id","curriculum_version_id","term_id") if doc[k] is None or doc[k]!=lesson[k]]
        if bad:
            raise HTTPException(409,{"message":"مصدر الشرح لا يطابق السياق الأكاديمي للدرس","fields":bad})
        pages=int(con.execute("""SELECT count(*) c FROM document_pages WHERE document_id=%s
          AND page_number BETWEEN %s AND %s""",(document_id,p.start_page,p.end_page)).fetchone()["c"])
        expected=p.end_page-p.start_page+1
        if pages!=expected:
            raise HTTPException(409,{"message":"بعض صفحات النطاق غير مفهرسة","expected":expected,"found":pages})
        overlap=con.execute("""SELECT id,lesson_id,start_page,end_page FROM lesson_source_mappings
          WHERE document_id=%s AND mapping_status<>'rejected'
            AND int4range(start_page,end_page,'[]') && int4range(%s,%s,'[]')
            AND lesson_id<>%s LIMIT 1""",
          (document_id,p.start_page,p.end_page,p.lesson_id)).fetchone()
        if overlap:
            raise HTTPException(409,{"message":"النطاق يتداخل مع درس آخر","mapping":overlap})
        row=con.execute("""INSERT INTO lesson_source_mappings(document_id,lesson_id,start_page,end_page,mapping_status)
          VALUES(%s,%s,%s,%s,'draft')
          ON CONFLICT(document_id,lesson_id,start_page,end_page)
          DO UPDATE SET mapping_status='draft',updated_at=now()
          RETURNING *""",(document_id,p.lesson_id,p.start_page,p.end_page)).fetchone()
        con.execute("UPDATE documents SET status='source_review_required' WHERE id=%s",(document_id,))
        return {"mapping":row,"status":"source_review_required"}

@app.post("/api/admin/lesson-sources/{mapping_id}/approve",dependencies=[Depends(require_admin)])
def approve_lesson_source(mapping_id:int):
    with connect() as con:
        m=con.execute("""SELECT m.*,d.kind,d.subject_id d_subject,d.grade_level_id d_grade,
          d.curriculum_version_id d_cv,d.term_id d_term,
          l.subject_id,l.grade_level_id,l.curriculum_version_id,l.term_id
          FROM lesson_source_mappings m
          JOIN documents d ON d.id=m.document_id
          JOIN lessons l ON l.id=m.lesson_id
          WHERE m.id=%s""",(mapping_id,)).fetchone()
        if not m:
            raise HTTPException(404,"Mapping not found")
        if m["kind"] not in EXPLANATORY_KINDS:
            raise HTTPException(409,"نوع المصدر غير صالح للشرح")
        if (m["d_subject"],m["d_grade"],m["d_cv"],m["d_term"])!=(m["subject_id"],m["grade_level_id"],m["curriculum_version_id"],m["term_id"]):
            raise HTTPException(409,"السياق الأكاديمي للمصدر والدرس غير متطابق")
        bad=con.execute("""SELECT count(*) c FROM document_pages
          WHERE document_id=%s AND page_number BETWEEN %s AND %s
            AND (extracted_text IS NULL OR btrim(extracted_text)='')""",
          (m["document_id"],m["start_page"],m["end_page"])).fetchone()["c"]
        if bad:
            raise HTTPException(409,{"message":"لا يمكن الاعتماد: توجد صفحات بلا نص مستخرج","pages_without_text":bad})
        row=con.execute("""UPDATE lesson_source_mappings
          SET mapping_status='approved',updated_at=now()
          WHERE id=%s RETURNING *""",(mapping_id,)).fetchone()
        remaining=con.execute("""SELECT count(*) c FROM lesson_source_mappings
          WHERE document_id=%s AND mapping_status NOT IN ('approved','rejected')""",
          (m["document_id"],)).fetchone()["c"]
        document_status="approved" if not remaining else "source_review_required"
        con.execute("UPDATE documents SET status=%s WHERE id=%s",(document_status,m["document_id"]))
        return {"mapping":row,"document_status":document_status}
