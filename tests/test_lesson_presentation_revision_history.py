import unittest
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

from app import lesson_presentation_revision_history as history
from app.services.lesson_presentation_blueprint import build_presentation_blueprint
from app.services.lesson_presentation_editor import presentation_editor_base_hash


class _Result:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((str(sql), params))
        return _Result()


class LessonPresentationRevisionHistoryTests(unittest.TestCase):
    REF = "ملف 1: lesson.pdf · صفحة 1"

    def _pack(self):
        return {
            "title": "قانون أوم",
            "subject": "فيزياء",
            "grade_label": "الثالث الثانوي",
            "learning_objectives": ["يطبق قانون أوم"],
            "summary": "يربط القانون بين الجهد والتيار والمقاومة.",
            "sections": [
                {
                    "heading": "الفكرة",
                    "body": "العلاقة V = IR تربط الكميات الكهربائية.",
                    "source_refs": [self.REF],
                }
            ],
            "equations_or_rules": [
                {
                    "label": "قانون أوم",
                    "expression": "V = IR",
                    "notes": "",
                    "source_refs": [self.REF],
                }
            ],
            "worked_examples": [],
            "source_visuals": [],
            "diagram_specs": [],
            "practice_questions": [],
            "common_mistakes": [],
            "quick_revision": [{"text": "V = IR", "source_refs": [self.REF]}],
        }

    def _blueprint(self):
        return build_presentation_blueprint(
            self._pack(),
            {
                "mode": "lesson_explanation",
                "audience": "teacher",
                "language": "ar",
                "length": "medium",
            },
            source_lesson_pack_id="pack-1",
        )

    def test_label_is_compact_and_bounded(self):
        self.assertEqual(history._clean_label("  نسخة   قبل الاختبار  "), "نسخة قبل الاختبار")
        self.assertEqual(len(history._clean_label("x" * 400)), 120)
        self.assertIsNone(history._clean_label("   "))

    def test_editor_payload_uses_current_guarded_validator(self):
        base = self._blueprint()
        edited = deepcopy(base)
        edited["slides"][0]["title"] += " — تعديل"
        base_hash = presentation_editor_base_hash(base)
        report = {
            "ready": True,
            "base_hash": base_hash,
            "edit_digest": "digest-1",
            "changed": True,
            "teacher_reapproval_required": True,
        }
        payload = {
            "edited_blueprint": edited,
            "editor_base_hash": base_hash,
            "current_slide": 999,
        }
        with patch.object(
            history.lesson_presentation_studio,
            "_presentation_editor_base",
            return_value=(base, base["request"]),
        ), patch.object(
            history.lesson_presentation_studio,
            "validate_presentation_edits",
            return_value=report,
        ) as validator:
            result = history._validated_editor_payload("job-1", payload)
        self.assertEqual(result[2], base_hash)
        self.assertEqual(result[3], "digest-1")
        self.assertEqual(result[4], len(edited["slides"]) - 1)
        validator.assert_called_once()

    def test_schema_creates_separate_draft_and_revision_tables(self):
        from app.services import lesson_pack_schema

        fake = _FakeConnection()

        @contextmanager
        def fake_connect():
            yield fake

        with patch.object(lesson_pack_schema, "connect", fake_connect):
            lesson_pack_schema.ensure_lesson_pack_schema()
        sql = "\n".join(item[0] for item in fake.sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS lesson_presentation_drafts", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS lesson_presentation_revisions", sql)
        self.assertIn("REFERENCES lesson_pack_jobs(id) ON DELETE CASCADE", sql)

    def test_revision_routes_are_registered(self):
        import index

        paths = {route.path for route in index.app.routes}
        required = {
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/draft",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions/{revision_id}",
            "/api/admin/lesson-pack-studio/jobs/{job_id}/presentation/revisions/{revision_id}/restore",
        }
        self.assertTrue(required.issubset(paths), required - paths)

    def test_workspace_exposes_revision_recovery_tools(self):
        import index
        from app import lesson_presentation_studio_ui

        html = lesson_presentation_studio_ui._workspace("job-revisions")
        for marker in (
            "Revision Timeline & Recovery",
            "saveCheckpoint",
            "refreshTimeline",
            "clearServerDraft",
            "serverDraftState",
            "data-restore-revision",
            "recoverServerDraft",
            "Ctrl",
            "Teacher re-approved",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
