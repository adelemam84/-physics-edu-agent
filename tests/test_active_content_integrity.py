from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest.mock import patch

from app.services import active_content_integrity as integrity


class _Cursor:
    def __init__(self, row):
        self._row=row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, *, active=True, invalid=0, lesson_mismatch=0, quiz_mismatch=0, critical=0):
        self.active=active
        self.invalid=invalid
        self.lesson_mismatch=lesson_mismatch
        self.quiz_mismatch=quiz_mismatch
        self.critical=critical

    def execute(self, sql, params=()):
        if "FROM curriculum_versions cv" in sql and "LIMIT 1" in sql:
            return _Cursor(
                {
                    "curriculum_version_id": 2,
                    "academic_year": "2026/2027",
                    "subject_id": 1,
                    "grade_level_id": 6,
                } if self.active else None
            )
        if "approved_total" in sql:
            return _Cursor({
                "approved_total": 71,
                "invalid_approved_questions": self.invalid,
                "missing_answer": 0,
                "missing_lesson": 0,
                "missing_asset": self.invalid,
                "missing_concept": 0,
                "missing_skill": 0,
            })
        if "JOIN lessons l ON l.id=q.lesson_id" in sql:
            return _Cursor({"n": self.lesson_mismatch})
        if "JOIN quizzes z" in sql or "FROM quizzes z" in sql:
            return _Cursor({"n": self.quiz_mismatch})
        if "question_review_notes" in sql:
            return _Cursor({"n": self.critical})
        raise AssertionError(sql)


def _connect_factory(**kwargs):
    @contextmanager
    def _connect():
        yield _Connection(**kwargs)
    return _connect


class ActiveContentIntegrityTests(unittest.TestCase):
    def test_ready_snapshot_is_scoped_to_active_curriculum(self):
        with patch.object(integrity, "connect", _connect_factory()):
            data=integrity.active_content_integrity_snapshot()
        self.assertTrue(data["active"])
        self.assertTrue(data["ready"])
        self.assertEqual(data["academic_year"], "2026/2027")
        self.assertEqual(data["policy"], "active_curriculum_only")

    def test_missing_asset_is_content_integrity_gate(self):
        with patch.object(integrity, "connect", _connect_factory(invalid=16)):
            data=integrity.active_content_integrity_snapshot()
        self.assertFalse(data["ready"])
        self.assertEqual(data["invalid_approved_questions"], 16)
        self.assertEqual(data["reasons"]["missing_asset"], 16)

    def test_academic_mismatch_blocks_integrity_without_mutation(self):
        with patch.object(integrity, "connect", _connect_factory(lesson_mismatch=2)):
            data=integrity.active_content_integrity_snapshot()
        self.assertFalse(data["ready"])
        self.assertEqual(data["question_lesson_mismatches"], 2)

    def test_no_active_curriculum_fails_closed(self):
        with patch.object(integrity, "connect", _connect_factory(active=False)):
            data=integrity.active_content_integrity_snapshot()
        self.assertFalse(data["active"])
        self.assertFalse(data["ready"])
        self.assertEqual(data["reason"], "no_active_curriculum")


if __name__ == "__main__":
    unittest.main()
