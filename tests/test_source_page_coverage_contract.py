from __future__ import annotations

import inspect
import unittest

from fastapi import HTTPException

from app.source_review import _coverage_state, _validate_page_closure


class SourcePageCoverageContractTests(unittest.TestCase):
    def test_zero_question_page_closes_only_as_reviewed_nonquestion(self):
        self.assertEqual(
            _coverage_state(0, "answer_solution", "done", 0),
            "reviewed_nonquestion",
        )
        self.assertEqual(
            _coverage_state(0, "front_matter", "done", 0),
            "reviewed_nonquestion",
        )
        self.assertEqual(
            _coverage_state(0, "index_or_divider", "done", 0),
            "reviewed_nonquestion",
        )

    def test_zero_question_candidate_stays_open(self):
        self.assertEqual(
            _coverage_state(0, "question_candidate", "reviewing", 2),
            "unresolved_question_candidate",
        )
        self.assertEqual(
            _coverage_state(0, "unknown", "pending", None),
            "unreviewed_zero_question",
        )

    def test_done_question_candidate_requires_exact_count(self):
        self.assertEqual(
            _coverage_state(4, "question_candidate", "done", 4),
            "question_page",
        )
        self.assertEqual(
            _coverage_state(4, "question_candidate", "done", 3),
            "question_count_mismatch",
        )
        with self.assertRaises(HTTPException) as ctx:
            _validate_page_closure(
                role="question_candidate",
                status="done",
                reviewed_count=3,
                extracted=4,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_question_candidate_cannot_close_with_zero_reviewed_count(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_page_closure(
                role="question_candidate",
                status="done",
                reviewed_count=0,
                extracted=0,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_nonquestion_role_cannot_close_if_questions_are_linked(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_page_closure(
                role="answer_solution",
                status="done",
                reviewed_count=0,
                extracted=1,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unknown_role_cannot_be_done(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_page_closure(
                role="unknown",
                status="done",
                reviewed_count=None,
                extracted=0,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_non_done_states_remain_editable_during_review(self):
        _validate_page_closure(
            role="question_candidate",
            status="reviewing",
            reviewed_count=7,
            extracted=2,
        )

    def test_physical_page_count_has_fallbacks_beyond_document_files(self):
        from app.source_review import _source_page_coverage_snapshot
        source = inspect.getsource(_source_page_coverage_snapshot)
        self.assertIn("greatest(", source)
        self.assertIn("max(f.page_count)", source)
        self.assertIn("max(p.page_number)", source)
        self.assertIn("max(coalesce(q.source_page,q.page))", source)
        self.assertIn("generate_series(1,d.physical_page_count)", source)



if __name__ == "__main__":
    unittest.main()
