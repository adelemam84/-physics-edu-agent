from pathlib import Path
import unittest


class VercelGeneratedPythonVersionTests(unittest.TestCase):
    def test_vercel_generated_python_version_marker_is_ignored(self):
        gitignore = Path('.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('.python-version', gitignore)


if __name__ == '__main__':
    unittest.main()
