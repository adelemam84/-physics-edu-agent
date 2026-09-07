import importlib
import unittest


class VercelEntrypointTests(unittest.TestCase):
    def test_vercel_entrypoint_imports_without_runtime_import_errors(self):
        module = importlib.import_module("index")
        self.assertEqual(module.app.version, "1.8.0")


if __name__ == "__main__":
    unittest.main()
