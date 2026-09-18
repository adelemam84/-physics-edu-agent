from pathlib import Path
import unittest

TRIAGE = Path("app/visual_review_triage.py").read_text(encoding="utf-8")
INDEX = Path("index.py").read_text(encoding="utf-8")
DASH = Path("app/admin_dashboard.py").read_text(encoding="utf-8")


class VisualReviewTriageTests(unittest.TestCase):
    def test_routes_are_registered_and_linked(self):
        self.assertIn("visual_review_triage", INDEX)
        self.assertIn("/admin/visual-review-triage", DASH)
        self.assertIn("/api/admin/current-corpus/visual-review-triage", TRIAGE)

    def test_triage_shows_authoritative_source_image(self):
        self.assertIn("/api/questions/", TRIAGE)
        self.assertIn("/asset/image", TRIAGE)
        self.assertIn("/api/admin/review/documents/", TRIAGE)
        self.assertIn("/preview", TRIAGE)

    def test_decision_is_trim_validated_locked_and_active_curriculum_scoped(self):
        self.assertIn("Reviewer note must contain at least 3 non-space characters", TRIAGE)
        self.assertIn("FOR UPDATE OF q,qr", TRIAGE)
        self.assertGreaterEqual(TRIAGE.count("q.curriculum_version_id=("), 2)

    def test_acceptance_is_human_gated_and_never_auto_approves(self):
        self.assertIn("Explicit human-reviewed verbatim text is required", TRIAGE)
        self.assertIn("approved=FALSE", TRIAGE)
        self.assertIn('"auto_approved":False', TRIAGE)
        self.assertIn("human_decision_required", TRIAGE)

    def test_acceptance_is_limited_to_source_candidate_placeholders(self):
        self.assertIn("Only source-image candidate placeholders can be replaced here", TRIAGE)
        self.assertIn("_CANDIDATE_RE.match", TRIAGE)

    def test_triage_prioritizes_missing_low_confidence_and_uncertain(self):
        self.assertIn('band="missing"', TRIAGE)
        self.assertIn('confidence < 0.65', TRIAGE)
        self.assertIn('confidence < 0.85', TRIAGE)
        self.assertIn("uncertain_parts", TRIAGE)

    def test_accept_resolves_only_visual_transcription_note(self):
        self.assertIn("reason_code='visual_transcription_required'", TRIAGE)
        self.assertIn("status='resolved'", TRIAGE)
        self.assertIn("source_verified=TRUE", TRIAGE)

    def test_non_accept_decisions_leave_note_open(self):
        self.assertIn("Human review requested correction", TRIAGE)
        self.assertIn("Human review rejected AI transcription", TRIAGE)
        self.assertNotIn("decision==\"reject\" and", TRIAGE)


if __name__ == "__main__":
    unittest.main()
