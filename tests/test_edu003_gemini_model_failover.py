from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import app.visual_review_assistant as visual


STUDIO = Path("app/science_lesson_studio.py").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/execute-edu001-edu003.yml").read_text(encoding="utf-8")
SCRIPT = Path("tools/manual_content_maintenance.sh").read_text(encoding="utf-8")


class Edu003GeminiModelFailoverTests(unittest.TestCase):
    def test_gemini_helper_accepts_model_override(self):
        self.assertIn("model_override: str | None = None", STUDIO)
        self.assertIn("effective_model = (model_override or GEMINI_MODEL)", STUDIO)
        self.assertIn("models/{effective_model}:generateContent", STUDIO)

    def test_visual_failover_chain_has_high_volume_fallbacks(self):
        self.assertEqual(visual.GEMINI_VISUAL_PRIMARY_MODEL, "gemini-3.5-flash-lite")
        self.assertIn("gemini-3.1-flash-lite", visual.GEMINI_VISUAL_FALLBACK_MODELS)
        self.assertIn("gemini-2.5-flash-lite", visual.GEMINI_VISUAL_FALLBACK_MODELS)

    def test_429_moves_to_next_gemini_model(self):
        row={"filename":"source.pdf","source_page":10}
        image=b"jpeg"
        attempts=[]
        def fake(parts, system, **kwargs):
            model=kwargs["model_override"]
            attempts.append(model)
            if len(attempts)==1:
                raise HTTPException(502, {"message":"Gemini request failed","status":429})
            return '{"question_text":"ok","options":[],"visible_answer":null,"question_type":"unknown","difficulty_guess":"unclassified","uncertain_parts":[],"visual_description":"","confidence":0.5}'
        with patch.object(visual, "_gemini_text", side_effect=fake), patch.object(
            visual, "GEMINI_VISUAL_FALLBACK_MODELS", ("gemini-3.1-flash-lite",)
        ), patch.object(
            visual, "model_settings", return_value={"gemini_lesson_studio":"gemini-3.5-flash-lite"}
        ):
            raw, provider, attempted=visual._gemini_visual_json(image,"prompt",row)
        self.assertIn('"question_text":"ok"', raw)
        self.assertEqual(provider,"gemini:gemini-3.1-flash-lite")
        self.assertEqual(attempted,["gemini-3.5-flash-lite","gemini-3.1-flash-lite"])

    def test_404_moves_to_next_gemini_model(self):
        row={"filename":"source.pdf","source_page":10}
        attempts=[]
        def fake(parts, system, **kwargs):
            model=kwargs["model_override"]
            attempts.append(model)
            if len(attempts)==1:
                raise HTTPException(502, {"message":"Gemini request failed","status":404})
            return '{"question_text":"ok","options":[],"visible_answer":null,"question_type":"unknown","difficulty_guess":"unclassified","uncertain_parts":[],"visual_description":"","confidence":0.5}'
        with patch.object(visual, "_gemini_text", side_effect=fake), patch.object(
            visual, "GEMINI_VISUAL_FALLBACK_MODELS", ("gemini-3.1-flash-lite",)
        ):
            raw, provider, attempted=visual._gemini_visual_json(b"jpeg","prompt",row)
        self.assertIn('"question_text":"ok"', raw)
        self.assertEqual(provider,"gemini:gemini-3.1-flash-lite")
        self.assertEqual(attempted,["gemini-3.5-flash-lite","gemini-3.1-flash-lite"])

    def test_network_unavailability_moves_to_next_gemini_model(self):
        row={"filename":"source.pdf","source_page":10}
        attempts=[]
        def fake(parts, system, **kwargs):
            model=kwargs["model_override"]
            attempts.append(model)
            if len(attempts)==1:
                raise HTTPException(502, "Gemini is temporarily unavailable")
            return '{"question_text":"ok","options":[],"visible_answer":null,"question_type":"unknown","difficulty_guess":"unclassified","uncertain_parts":[],"visual_description":"","confidence":0.5}'
        with patch.object(visual, "_gemini_text", side_effect=fake), patch.object(
            visual, "GEMINI_VISUAL_FALLBACK_MODELS", ("gemini-3.1-flash-lite",)
        ):
            raw, provider, attempted=visual._gemini_visual_json(b"jpeg","prompt",row)
        self.assertIn('"question_text":"ok"', raw)
        self.assertEqual(provider,"gemini:gemini-3.1-flash-lite")
        self.assertEqual(attempted,["gemini-3.5-flash-lite","gemini-3.1-flash-lite"])

    def test_non_transient_gemini_failure_does_not_switch_models(self):
        row={"filename":"source.pdf","source_page":10}
        with patch.object(
            visual, "_gemini_text",
            side_effect=HTTPException(502, {"message":"Gemini request failed","status":400})
        ), patch.object(
            visual, "GEMINI_VISUAL_FALLBACK_MODELS", ("gemini-3.1-flash-lite",)
        ), patch.object(
            visual, "model_settings", return_value={"gemini_lesson_studio":"gemini-3.5-flash-lite"}
        ):
            with self.assertRaises(HTTPException):
                visual._gemini_visual_json(b"jpeg","prompt",row)

    def test_maintenance_fails_closed_when_visual_candidates_remain(self):
        self.assertIn("tools/manual_content_maintenance.sh", WORKFLOW)
        self.assertIn('without_suggestion', SCRIPT)
        self.assertIn('EDU-003 incomplete', SCRIPT)


if __name__ == "__main__":
    unittest.main()
