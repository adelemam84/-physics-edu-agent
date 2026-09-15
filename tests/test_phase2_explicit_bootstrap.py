from __future__ import annotations

import inspect
import unittest
from unittest.mock import MagicMock, patch

from app import main, phase2_admin, technical_observability
from app.services import corpus_phase2_runtime as phase2


class Phase2ExplicitBootstrapTests(unittest.TestCase):
    def test_cold_start_has_no_phase2_business_bootstrap(self):
        source = inspect.getsource(main.lifespan)
        self.assertIn("ensure_runtime_schema()", source)
        self.assertNotIn("ensure_phase2_schemas", source)
        self.assertNotIn("run_phase2_bootstrap(", source)

    def test_schema_helper_contains_only_schema_initializers(self):
        source = inspect.getsource(phase2.ensure_phase2_schemas)
        self.assertIn("ensure_release_state_schema", source)
        self.assertIn("reference_schema()", source)
        self.assertIn("_map_schema()", source)
        self.assertIn("_history_schema()", source)
        self.assertNotIn("_ensure_quiz", source)
        self.assertNotIn("_publish_if_ready", source)

    def test_admin_bootstrap_is_protected_and_rate_limited(self):
        module_source = inspect.getsource(phase2_admin)
        endpoint_source = inspect.getsource(phase2_admin.admin_phase2_bootstrap)
        self.assertIn('dependencies=[Depends(require_admin)]', module_source)
        self.assertIn("enforce_request_policy", endpoint_source)
        self.assertIn('name="admin_phase2_bootstrap"', endpoint_source)
        self.assertIn("run_phase2_bootstrap()", endpoint_source)

    def test_admin_bootstrap_calls_explicit_business_action_once(self):
        request = MagicMock()
        with patch.object(phase2_admin, "enforce_request_policy") as limiter, \
             patch.object(
                 phase2_admin,
                 "run_phase2_bootstrap",
                 return_value={"active": True, "quizzes": []},
             ) as run:
            data = phase2_admin.admin_phase2_bootstrap(request)

        limiter.assert_called_once()
        run.assert_called_once_with()
        self.assertTrue(data["explicit_admin_action"])
        self.assertFalse(data["automatic_cold_start_mutation"])

    def test_phase2_rate_limit_scope_is_observable(self):
        self.assertEqual(
            technical_observability.RATE_LIMIT_POLICY_DEFAULTS[
                "admin_phase2_bootstrap"
            ],
            (2, 3600),
        )


if __name__ == "__main__":
    unittest.main()
