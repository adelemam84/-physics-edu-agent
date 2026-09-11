from __future__ import annotations

import inspect
import unittest

from app import adaptive_practice, advanced_learning, db, student_portal, student_quiz


class AdaptiveQuizIsolationTests(unittest.TestCase):
    def test_schema_has_student_owner_and_archives_legacy_public_adaptive_quizzes(self):
        source = inspect.getsource(db.init_db)
        self.assertIn("owner_student_id bigint REFERENCES students(id) ON DELETE CASCADE", source)
        self.assertIn("idx_quizzes_owner_student", source)
        self.assertIn("'legacy_adaptive_isolation'", source)
        self.assertIn("al.action='adaptive_publish'", source)

    def test_new_adaptive_quiz_is_owned_and_title_does_not_expose_student_id(self):
        source = inspect.getsource(adaptive_practice.create_student_adaptive_quiz)
        self.assertIn("owner_student_id", source)
        self.assertIn("q.owner_student_id=%s", source)
        self.assertIn("audience", source)
        self.assertIn("single_student", source)
        self.assertNotIn("طالب #{", source)

    def test_adaptive_question_selection_keeps_current_quality_gates(self):
        source = inspect.getsource(adaptive_practice.build_adaptive_practice)
        self.assertIn("q.question_type<>'unknown'", source)
        self.assertIn("q.difficulty<>'unclassified'", source)
        self.assertIn("question_review_notes", source)
        self.assertIn("qr.status='open'", source)

    def test_student_portal_lists_only_public_or_owned_quizzes(self):
        source = inspect.getsource(student_portal.student_portal)
        self.assertIn("q.owner_student_id IS NULL OR q.owner_student_id=%s", source)
        self.assertIn("z.owner_student_id IS NULL", source)

    def test_mock_exam_excludes_personal_adaptive_quizzes(self):
        source = inspect.getsource(advanced_learning._mock_exam)
        self.assertIn("q.owner_student_id IS NULL", source)

    def test_student_quiz_access_checks_owner_for_read_start_and_submit(self):
        for fn in (
            student_quiz.student_quiz,
            student_quiz.start_quiz_attempt,
            student_quiz.submit_quiz,
        ):
            source = inspect.getsource(fn)
            self.assertIn("owner_student_id IS NULL OR owner_student_id=%s", source, fn.__name__)


if __name__ == "__main__":
    unittest.main()
