from __future__ import annotations

import unittest

from app import advanced_learning, student_lesson, student_portal, student_quiz


class StudentSessionUiContractTests(unittest.TestCase):
    def test_portal_never_puts_student_code_in_url_or_session_storage(self):
        page = student_portal.PAGE
        self.assertNotIn("?student_code=", page)
        self.assertNotIn("sessionStorage.setItem('student_code'", page)
        self.assertIn("/api/student/session", page)
        self.assertIn("/api/student/portal", page)

    def test_learning_suite_uses_session_api(self):
        page = advanced_learning.PAGE
        self.assertNotIn("learning-suite?student_code=", page)
        self.assertIn("/api/student/session", page)
        self.assertIn("fetch('/api/student/learning-suite'", page)

    def test_lesson_uses_session_api(self):
        page = student_lesson.PAGE
        self.assertNotIn("?student_code=", page)
        self.assertNotIn("sessionStorage.getItem('student_code'", page)
        self.assertIn("/api/student/session", page)

    def test_quiz_never_places_student_code_in_url_or_attempt_payloads(self):
        page = student_quiz.STUDENT
        self.assertNotIn("?student_code=", page)
        self.assertNotIn("student_code:code.value", page)
        self.assertIn("/api/student/session", page)
        self.assertIn("/saved',{cache:'no-store'}", page)
        self.assertIn("body:JSON.stringify({question_id:qid,answer:el.value})", page)


if __name__ == "__main__":
    unittest.main()
