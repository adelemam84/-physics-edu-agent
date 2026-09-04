from __future__ import annotations
import os
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
STORAGE_BACKEND = "neon_postgresql" if DATABASE_URL else "not_configured"

@contextmanager
def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")
    import psycopg
    from psycopg.rows import dict_row
    con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    defaults = [("system_name","وكيل الفيزياء التعليمي"),("content_policy","pdf_only"),("allow_generated_questions","false"),("require_question_approval","true")]
    lessons = [("الفصل الأول","التيار الكهربي وقانون أوم",10),("الفصل الأول","توصيل المقاومات",20),("الفصل الأول","قوانين كيرشوف",30),("الفصل الثاني","التأثير المغناطيسي للتيار",40),("الفصل الثالث","الحث الكهرومغناطيسي",50),("الفصل الرابع","دوائر التيار المتردد",60)]
    with connect() as con:
        for key,value in defaults:
            con.execute("INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO NOTHING",(key,value))
        for chapter,title,sort_order in lessons:
            con.execute("INSERT INTO lessons(chapter,title,sort_order) SELECT %s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM lessons WHERE chapter=%s AND title=%s)",(chapter,title,sort_order,chapter,title))
        # Non-destructive notification delivery tracking migration.
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS delivery_status text")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS delivered_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS read_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_status_at timestamptz")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_error_code text")
        con.execute("ALTER TABLE parent_notifications ADD COLUMN IF NOT EXISTS provider_error_title text")
        con.execute("CREATE INDEX IF NOT EXISTS idx_parent_notifications_provider_message_id ON parent_notifications(provider_message_id)")
