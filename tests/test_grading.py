import unittest

from app.services.grading import extract_numeric_values, grade_answer


class GradingTests(unittest.TestCase):
    def test_scientific_notation(self):
        self.assertTrue(grade_answer("2.84×10^-19 J", "2.84×10^-19 J"))

    def test_scientific_notation_tolerance(self):
        self.assertTrue(grade_answer("2.85e-19", "2.84×10^-19 J"))

    def test_fraction(self):
        self.assertTrue(grade_answer("0.5", "1/2"))

    def test_sqrt_two(self):
        self.assertTrue(grade_answer("5.657", "4√2 A"))

    def test_multi_value_requires_all_values(self):
        self.assertTrue(grade_answer("100 V, 900 V", "100 V ، 900 V"))
        self.assertFalse(grade_answer("100 V", "100 V ، 900 V"))

    def test_qualitative_anchor(self):
        self.assertTrue(grade_answer("4×10^-6 N قوة تجاذب", "4×10^-6 N، قوة تجاذب"))
        self.assertFalse(grade_answer("4×10^-6 N قوة تنافر", "4×10^-6 N، قوة تجاذب"))

    def test_missing_answer_is_ungradable(self):
        self.assertIsNone(grade_answer("1", None))

    def test_extract_values(self):
        vals=extract_numeric_values("6.4×10^-4 T و 2 A")
        self.assertEqual(len(vals),2)


if __name__ == "__main__":
    unittest.main()
