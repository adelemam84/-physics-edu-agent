from __future__ import annotations

import unittest

from app.admin_auth import LOGIN


class AdminLoginUiTests(unittest.TestCase):
    def test_login_uses_semantic_form_and_accessible_status(self):
        for token in (
            "<form id=loginForm",
            'onsubmit="login(event)"',
            "aria-live=polite",
            "required maxlength=512",
            "autocomplete=current-password",
        ):
            self.assertIn(token, LOGIN)

    def test_login_supports_password_visibility_without_persisting_key(self):
        self.assertIn("toggleKey()", LOGIN)
        self.assertIn("type=password", LOGIN)
        self.assertNotIn("localStorage", LOGIN)
        self.assertNotIn("sessionStorage", LOGIN)

    def test_login_handles_network_and_backend_errors_without_navigation_loop(self):
        self.assertIn("try{let r=await fetch('/api/admin/login'", LOGIN)
        self.assertIn("تعذر الاتصال بالخادم", LOGIN)
        self.assertIn("x.configured===false", LOGIN)


if __name__ == "__main__":
    unittest.main()
