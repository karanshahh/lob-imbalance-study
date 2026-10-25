"""Known-answer tests for the diagnostic."""
import unittest

import numpy as np

import diagnose


class Spread(unittest.TestCase):
    def test_known_answer(self):
        s = diagnose.spread_stats(np.array([1.0, 1.0, 1.0, 2.0, np.nan]))
        self.assertAlmostEqual(s["spread_share_1"], 0.75)
        self.assertAlmostEqual(s["spread_median"], 1.0)


class Tails(unittest.TestCase):
    def test_one_big_jump_flips_pearson_not_spearman(self):
        x = np.linspace(-1, 1, 2001)
        y = np.sign(x) * 1.0            # small moves in the direction of the signal
        y[0] = 5000.0                   # one huge jump against it
        t = diagnose.tail_stats(x, y)
        self.assertLess(t["pearson"], 0)
        self.assertGreater(t["spearman"], 0.5)
        self.assertGreater(t["top_cov_share"], 1.0)   # the top rows carry more than all of it
        self.assertEqual(t["abs_max"], 5000.0)

    def test_share_gt10_and_nan_rows(self):
        t = diagnose.tail_stats(np.array([0.1, 0.2, np.nan, 0.3]), np.array([11.0, 1.0, 50.0, -12.0]))
        self.assertEqual(t["n"], 3)
        self.assertAlmostEqual(t["share_gt10"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
