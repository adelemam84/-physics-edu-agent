from __future__ import annotations

import inspect
import json
import unittest

from index import app
from app import (
    adaptive_practice,
    advanced_learning,
    analytics,
    student_lesson,
    student_portal,
    student_quiz,
    student_review_exports,
)
from app.student_session_api import StudentSessionLogin


class StudentApiSessionOnlyContractTests(unittest.TestCase):
    """After login, student identity must come only from the signed session cookie."""

    def test_only_login_model_contains_student_code(self):
        self.assertIn("student_code", StudentSessionLogin.model_fields)
        for model in (
            student_lesson.DiagnosticSubmit,
            student_quiz.SubmitAttempt,
            student_quiz.SaveAnswer,
            student_review_exports.StudentReviewExportRequest,
        ):
            self.assertNotIn("student_code", model.model_fields, model.__name__)

    def test_student_handlers_no_longer_accept_student_code_parameters(self):
        handlers = (
            student_portal.student_portal,
            analytics.student_mastery,
            analytics.student_remedial_progress,
            analytics.student_recommendations,
            advanced_learning.learning_suite_api,
            advanced_learning.review_queue_api,
            advanced_learning.exam_readiness_api,
            adaptive_practice.student_adaptive_practice,
            adaptive_practice.create_student_adaptive_quiz,
            student_lesson.student_lesson,
            student_lesson.lesson_diagnostic,
            student_quiz.start_quiz_attempt,
            student_quiz.save_quiz_answer,
            student_quiz.saved_quiz_answers,
            student_quiz.submit_quiz,
            student_review_exports.student_attempt_review_pdf,
            student_review_exports.student_mistakes_review_pdf,
        )
        for handler in handlers:
            self.assertNotIn("student_code", inspect.signature(handler).parameters, handler.__name__)

    def test_openapi_student_routes_do_not_advertise_student_code_except_login(self):
        schema = app.openapi()
        paths = schema.get("paths") or {}
        components = (schema.get("components") or {}).get("schemas") or {}

        def resolved_schema(node):
            if not isinstance(node, dict):
                return node
            ref = node.get("$ref")
            if ref and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                return components.get(name) or {}
            return node

        for path, item in paths.items():
            if not path.startswith("/api/student/"):
                continue
            for method, operation in item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if path == "/api/student/session" and method == "post":
                    body = operation.get("requestBody") or {}
                    schema_node = (
                        (body.get("content") or {})
                        .get("application/json", {})
                        .get("schema", {})
                    )
                    login_schema = resolved_schema(schema_node)
                    self.assertIn("student_code", (login_schema.get("properties") or {}))
                    continue

                for parameter in operation.get("parameters") or []:
                    self.assertNotEqual(parameter.get("name"), "student_code", (path, method))

                body = operation.get("requestBody") or {}
                schema_node = (
                    (body.get("content") or {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                payload_schema = resolved_schema(schema_node)
                self.assertNotIn(
                    '"student_code"',
                    json.dumps(payload_schema, ensure_ascii=False),
                    (path, method),
                )

    def test_legacy_student_code_environment_switch_is_gone(self):
        from app import student_security
        source = inspect.getsource(student_security)
        self.assertNotIn("ALLOW_LEGACY_STUDENT_CODE_AUTH", source)
        self.assertNotIn("legacy_student_code_allowed", source)


if __name__ == "__main__":
    unittest.main()
