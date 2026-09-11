from __future__ import annotations

import unittest

from fastapi import HTTPException
from starlette.requests import Request

from app.practice import PRACTICE, practice_asset, practice_questions
from app.student_quiz import STUDENT, student_quiz


def anonymous_request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/student/quizzes/1",
        "headers": [],
        "scheme": "https",
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    })


class QuizPreloginSecurityTests(unittest.TestCase):
    def test_quiz_question_api_requires_student_session_before_db_access(self):
        with self.assertRaises(HTTPException) as ctx:
            student_quiz(1, anonymous_request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_quiz_page_loads_questions_only_after_session_check(self):
        load_start = STUDENT.index("async function load(){")
        session_check = STUDENT.index("let s=await sessionInfo();", load_start)
        quiz_load = STUDENT.index("if(await loadQuiz())", session_check)
        self.assertLess(session_check, quiz_load)
        self.assertIn("if(!data && !await loadQuiz())", STUDENT)

    def test_practice_question_api_requires_student_session_before_db_access(self):
        with self.assertRaises(HTTPException) as ctx:
            practice_questions(anonymous_request(), 10)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_practice_asset_requires_student_session_before_db_access(self):
        with self.assertRaises(HTTPException) as ctx:
            practice_asset(1, anonymous_request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_practice_page_checks_session_before_loading_questions(self):
        self.assertIn("/api/student/session", PRACTICE)
        self.assertIn("if(!s.authenticated){location.href='/student';return}", PRACTICE)
        self.assertLess(PRACTICE.index("/api/student/session"), PRACTICE.index("/api/practice/questions"))


if __name__ == "__main__":
    unittest.main()
