import inspect
import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

from app.services.lesson_presentation_blueprint import build_presentation_blueprint
from app.services.lesson_presentation_editor import presentation_edit_digest, presentation_editor_base_hash


class _Result:
    def __init__(self, row=None, rows=None):
        self.row=row
        self.rows=rows or []
    def fetchone(self): return self.row
    def fetchall(self): return self.rows


class _Conn:
    def __init__(self): self.sql=[]
    def execute(self, sql, params=None):
        self.sql.append((str(sql),params))
        return _Result()


class PresentationApprovalLedgerTests(unittest.TestCase):
    REF="ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title":"قانون أوم","subject":"فيزياء","grade_label":"الثالث الثانوي",
            "learning_objectives":["يطبق قانون أوم"],"summary":"V = IR",
            "sections":[{"heading":"الفكرة","body":"V = IR","source_refs":[self.REF]}],
            "equations_or_rules":[],"worked_examples":[],"source_visuals":[],
            "diagram_specs":[],"practice_questions":[],"common_mistakes":[],
            "quick_revision":[{"text":"V = IR","source_refs":[self.REF]}],
        }

    def _blueprint(self):
        return build_presentation_blueprint(
            self._pack(),
            {"mode":"lesson_explanation","audience":"teacher","language":"ar","length":"medium"},
            source_lesson_pack_id="pack-1",
        )

    def test_base_revision_has_stable_exact_digest(self):
        base=self._blueprint()
        h=presentation_editor_base_hash(base)
        d1=presentation_edit_digest(h,base)
        d2=presentation_edit_digest(h,deepcopy(base))
        self.assertEqual(d1,d2)
        edited=deepcopy(base); edited["slides"][0]["title"]+=" تعديل"
        self.assertNotEqual(d1,presentation_edit_digest(h,edited))

    def test_schema_contains_approval_ledger(self):
        from app.services import lesson_pack_schema
        fake=_Conn()
        @contextmanager
        def fake_connect():
            yield fake
        with patch.object(lesson_pack_schema,"connect",fake_connect):
            lesson_pack_schema.ensure_lesson_pack_schema()
        sql="\n".join(x[0] for x in fake.sql)
        self.assertIn("lesson_presentation_approvals",sql)
        self.assertIn("edit_digest text NOT NULL",sql)
        self.assertIn("revoked_at timestamptz",sql)

    def test_routes_and_ui_are_registered(self):
        import index
        from app import lesson_presentation_studio_ui
        paths={r.path for r in index.app.routes}
        required={
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approval-state",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approvals",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/approvals/{approval_id}/revoke",
        }
        self.assertTrue(required.issubset(paths), required-paths)
        html=lesson_presentation_studio_ui._workspace("job-1")
        for marker in ("Persistent Teacher Approval","approvalLedger","refreshApproval","exact digest","data-revoke"):
            self.assertIn(marker,html)

    def test_export_requires_persistent_exact_digest_approval(self):
        from app import lesson_presentation_studio
        src=inspect.getsource(lesson_presentation_studio.export_lesson_presentation_pptx)
        self.assertIn("active_approval",src)
        self.assertIn("presentation_approval_required",src)
        self.assertIn("X-Presentation-Approval-Id",src)
        self.assertNotIn('payload.get("teacher_reapproved") is not True',src)

    def test_unedited_export_context_has_digest(self):
        from app import lesson_presentation_studio
        src=inspect.getsource(lesson_presentation_studio._prepared_editor_blueprint)
        self.assertIn("presentation_edit_digest(base_hash, base)",src)
        self.assertIn('"teacher_reapproval_required": True',src)


if __name__=="__main__":
    unittest.main()
