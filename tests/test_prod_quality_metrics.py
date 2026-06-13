import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.quality import compute_quality  # noqa: E402


def pair_rows(n, instruction="Explain photosynthesis in plants", response="Plants convert light into chemical energy"):
    return [{"instruction": f"{instruction} {i}", "response": f"{response} {i}"} for i in range(n)]


class QualityMetricsTest(unittest.TestCase):
    def test_empty_is_zero(self):
        m = compute_quality([])
        self.assertEqual(m.overall, 0)

    def test_clean_pair_dataset_scores_high(self):
        m = compute_quality(pair_rows(20))
        self.assertGreaterEqual(m.completeness, 0.99)
        self.assertGreaterEqual(m.consistency, 0.99)
        self.assertGreaterEqual(m.overall, 90)

    def test_missing_fields_lower_completeness(self):
        rows = pair_rows(10)
        rows[0]["response"] = ""
        rows[1]["response"] = "   "
        m = compute_quality(rows)
        self.assertLess(m.completeness, 1.0)

    def test_duplicates_lower_diversity(self):
        rows = [{"instruction": "same", "response": "same"} for _ in range(10)]
        m = compute_quality(rows)
        self.assertLess(m.diversity, 0.2)
        self.assertLess(m.duplicate_ratio, 0.2)

    def test_inconsistent_keys_lower_consistency(self):
        rows = pair_rows(10)
        rows[5] = {"instruction": "x", "response": "y", "extra": "z"}
        m = compute_quality(rows)
        self.assertLess(m.consistency, 1.0)

    def test_dirty_formatting_lowers_score(self):
        clean = compute_quality(pair_rows(10))
        dirty_rows = [{"instruction": f"  padded {i}  ", "response": f"trailing {i}\t"} for i in range(10)]
        dirty = compute_quality(dirty_rows)
        self.assertLess(dirty.formatting, clean.formatting)

    def test_overlong_text_hurts_readability_and_compat(self):
        long_text = "word " * 5000
        rows = [{"instruction": long_text, "response": long_text} for _ in range(5)]
        m = compute_quality(rows)
        self.assertEqual(m.readability, 0.0)
        self.assertLess(m.model_compatibility, 0.85)

    def test_single_text_structure_detected(self):
        rows = [{"text": f"a sentence number {i}"} for i in range(10)]
        m = compute_quality(rows)
        # single-text base is 0.70
        self.assertAlmostEqual(m.model_compatibility, 0.70, places=2)

    def test_unstructured_low_compat(self):
        rows = [{"foo": i, "bar": i * 2} for i in range(10)]
        m = compute_quality(rows)
        self.assertAlmostEqual(m.model_compatibility, 0.40, places=2)
        self.assertEqual(m.completeness, 0.0)

    def test_meets_threshold(self):
        m = compute_quality(pair_rows(20))
        self.assertTrue(m.meets("fast"))
        self.assertFalse(compute_quality([{"foo": 1}]).meets("production"))

    def test_dirty_dataset_scores_below_clean(self):
        clean = compute_quality(pair_rows(20))
        dirty = compute_quality([{"instruction": "same", "response": ""} for _ in range(20)])
        self.assertLess(dirty.overall, clean.overall)


if __name__ == "__main__":
    unittest.main(verbosity=2)
