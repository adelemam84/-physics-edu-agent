from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from app.services import ai_telemetry


class _FakeConnection:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self.row


class _Context:
    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, exc_type, exc, tb):
        return False


class AITelemetryTests(unittest.TestCase):
    def test_normalizes_gemini_and_openai_usage(self):
        gemini = ai_telemetry.normalize_usage(
            "gemini",
            {"promptTokenCount": 100, "candidatesTokenCount": 25, "totalTokenCount": 125},
        )
        self.assertEqual(gemini, {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125})
        openai = ai_telemetry.normalize_usage(
            "openai",
            {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
        )
        self.assertEqual(openai["total_tokens"], 50)

    def test_pricing_is_environment_managed(self):
        pricing = json.dumps({
            "model-x": {"input_per_million": 2.0, "output_per_million": 8.0}
        })
        with patch.dict(os.environ, {"AI_MODEL_PRICING_JSON": pricing}, clear=False):
            cost = ai_telemetry.estimate_cost_usd(
                "model-x",
                input_tokens=1_000_000,
                output_tokens=500_000,
            )
        self.assertEqual(cost, 6.0)

    def test_recording_strips_content_bearing_metadata(self):
        con = _FakeConnection()
        with patch("app.services.ai_telemetry.connect", return_value=_Context(con)):
            ok = ai_telemetry.record_ai_usage(
                provider="gemini",
                task="source_analysis",
                model="gemini-test",
                status="success",
                latency_ms=123,
                usage={"promptTokenCount": 10, "candidatesTokenCount": 5},
                metadata={
                    "document_id": 7,
                    "prompt": "sensitive prompt",
                    "transcript": "sensitive source text",
                    "answer": "student answer",
                },
            )
        self.assertTrue(ok)
        self.assertEqual(len(con.calls), 1)
        params = con.calls[0][1]
        metadata_json = params[10]
        self.assertIn("document_id", metadata_json)
        self.assertNotIn("sensitive prompt", metadata_json)
        self.assertNotIn("sensitive source text", metadata_json)
        self.assertNotIn("student answer", metadata_json)


if __name__ == "__main__":
    unittest.main()
