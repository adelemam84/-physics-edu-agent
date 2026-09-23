from __future__ import annotations

from pathlib import Path
import unittest


SCRIPT = Path("tools/install_windows_runner_service.ps1")


class WindowsRunnerServiceScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_requires_admin_and_uses_supported_service_configuration(self):
        self.assertIn("Assert-Administrator", self.text)
        self.assertIn("--runasservice", self.text)
        self.assertIn("--unattended", self.text)
        self.assertIn("--replace", self.text)

    def test_preserves_existing_runner_identity_before_reconfiguration(self):
        self.assertIn('Join-Path $RunnerRoot ".runner"', self.text)
        self.assertIn("$stored.agentName", self.text)
        self.assertIn("$stored.workFolder", self.text)

    def test_requires_both_remove_and_registration_tokens_for_existing_non_service_runner(self):
        self.assertIn("RemoveToken", self.text)
        self.assertIn("RegistrationToken", self.text)
        self.assertIn("config.cmd remove", self.text)

    def test_can_acquire_short_lived_tokens_from_authenticated_gh(self):
        self.assertIn("gh api --method POST", self.text)
        self.assertIn("actions/runners/remove-token", self.text)
        self.assertIn("actions/runners/registration-token", self.text)

    def test_service_is_automatic_and_has_restart_recovery(self):
        self.assertIn("StartupType Automatic", self.text)
        self.assertIn("sc.exe failure", self.text)
        self.assertIn("sc.exe failureflag", self.text)

    def test_prevents_duplicate_interactive_listener(self):
        self.assertIn("Stop-InteractiveRunnerListeners", self.text)
        self.assertIn("Expected exactly one Runner.Listener", self.text)
        self.assertIn("--startuptype\\s+service", self.text)


if __name__ == "__main__":
    unittest.main()
