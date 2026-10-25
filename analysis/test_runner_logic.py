"""Logic tests for analysis/run_strategy_sim.py: variant selection, pooled statistics and
the frozen v2 constants. Expected values are worked out by hand in the comments."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import config as C  # noqa: E402
import run_strategy_sim as R  # noqa: E402

KEY = R.fee_key(C.REF_FEE_PER_SHARE)
OTHER = R.fee_key(0.0)


def prow(symbol, thr, lim, lat, trades, net, other=0.0):
    return {"symbol": symbol, "threshold": thr, "spread_limit_ticks": lim,
            "latency_ns": lat, "trades": trades, KEY: net, OTHER: other}


REF = C.REF_LATENCY_NS


class Selection(unittest.TestCase):
    def test_picks_the_highest_net_among_eligible(self):
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.004),
                prow("SPY", 0.4, "1", REF, 500, -0.001),
                prow("SPY", 0.6, "1", REF, 500, -0.009)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.4)
        self.assertEqual(s["eligible_variants"], 3)
        self.assertEqual(s["variants_total"], 3)

    def test_variants_below_the_minimum_trade_count_are_excluded(self):
        # The 0.6 variant has the best net but only MIN - 1 trades, so it is not eligible.
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.004),
                prow("SPY", 0.6, "1", REF, C.MIN_TRADES_SELECT - 1, 0.050)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.2)
        self.assertEqual(s["eligible_variants"], 1)

    def test_exactly_the_minimum_trade_count_is_eligible(self):
        rows = [prow("SPY", 0.6, "1", REF, C.MIN_TRADES_SELECT, -0.001)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.6)

    def test_only_the_reference_latency_counts(self):
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.004),
                prow("SPY", 0.8, "any", 0, 500, 0.090),            # better, wrong latency
                prow("SPY", 0.8, "any", 1_000_000, 500, 0.090)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.2)
        self.assertEqual(s["variants_total"], 1)

    def test_only_the_reference_fee_counts(self):
        # Fee 0 column says 0.8 is best, the reference-fee column says 0.2 is.
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.001, other=-0.005),
                prow("SPY", 0.8, "1", REF, 500, -0.009, other=0.020)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.2)

    def test_other_symbols_are_ignored(self):
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.004),
                prow("QQQ", 0.8, "any", REF, 500, 0.090)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.2)
        self.assertEqual(s["variants_total"], 1)

    def test_ties_go_to_the_first_variant_in_grid_order(self):
        rows = [prow("SPY", 0.2, "1", REF, 500, -0.003),
                prow("SPY", 0.2, "2", REF, 500, -0.003),
                prow("SPY", 0.4, "1", REF, 500, -0.003)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual((s["selected"]["threshold"], s["selected"]["spread_limit_ticks"]), (0.2, "1"))

    def test_nan_net_is_never_selected(self):
        rows = [prow("SPY", 0.2, "1", REF, 500, float("nan")),
                prow("SPY", 0.4, "1", REF, 500, -0.002)]
        s = R.select_variant(rows, "SPY")
        self.assertEqual(s["selected"]["threshold"], 0.4)
        self.assertEqual(s["eligible_variants"], 1)

    def test_nobody_eligible_means_no_selection(self):
        rows = [prow("SPY", 0.2, "1", REF, 5, 0.9), prow("SPY", 0.4, "1", REF, 99, 0.9)]
        s = R.select_variant(rows, "SPY")
        self.assertIsNone(s["selected"])
        self.assertEqual(s["eligible_variants"], 0)

    def test_the_selected_net_is_reported_unchanged(self):
        rows = [prow("SPY", 0.4, "2", REF, 321, -0.00123)]
        sel = R.select_variant(rows, "SPY")["selected"]
        self.assertEqual(sel["dev_trades"], 321)
        self.assertEqual(sel["dev_net_mean_usd_at_ref"], -0.00123)
        self.assertEqual(sel["spread_limit_ticks"], "2")


def fake_result(gross, candidates=0, entry_empty=0, exit_unavailable=0):
    return types.SimpleNamespace(
        gross_units=np.array(gross, dtype=np.int64), n=len(gross), n_candidates=candidates,
        entry_empty=entry_empty, exit_unavailable=exit_unavailable)


class PooledStats(unittest.TestCase):
    def test_known_answers_over_two_days(self):
        # Day 1 gross units [200, -100, 100]; day 2 has no trades.
        # trades 3, days with trades 1, trades per day 3/2 = 1.5, shares per day 2*3/2 = 3.0,
        # gross mean = 200/3 units = 0.6667 ticks. Counters add across days.
        res = [fake_result([200, -100, 100], candidates=7, entry_empty=2, exit_unavailable=1),
               fake_result([], candidates=3, entry_empty=1, exit_unavailable=4)]
        row = R.pooled_stats(res, (0.0, 0.003, 0.01))
        self.assertEqual(row["trades"], 3)
        self.assertEqual(row["days_with_trades"], 1)
        self.assertAlmostEqual(row["trades_per_day"], 1.5)
        self.assertAlmostEqual(row["shares_per_day"], 3.0)
        self.assertAlmostEqual(row["gross_mean_ticks"], 0.6666666667)
        self.assertEqual((row["candidates"], row["entry_empty"], row["exit_unavailable"]), (10, 3, 5))
        # Fee 0: net [0.02, -0.01, 0.01], mean 0.0066667, hit 2/3, sharpe 0.4364358, day positive.
        self.assertAlmostEqual(row["net_mean_usd_fee0.0"], 0.0066666667)
        self.assertAlmostEqual(row["hit_rate_fee0.0"], 2 / 3)
        self.assertAlmostEqual(row["sharpe_per_trade_fee0.0"], 0.4364358, places=6)
        self.assertEqual(row["days_net_positive_fee0.0"], 1)
        # Fee 0.003 (both legs, 0.006): net [0.014, -0.016, 0.004], mean 0.00066667.
        self.assertAlmostEqual(row["net_mean_usd_fee0.003"], 0.00066666667)
        self.assertAlmostEqual(row["hit_rate_fee0.003"], 2 / 3)
        self.assertEqual(row["days_net_positive_fee0.003"], 1)
        # Fee 0.01 (0.02 both legs): net [0.0, -0.03, -0.01]. A trade at exactly 0 is not a
        # win, the mean is negative, and the day is not positive.
        self.assertAlmostEqual(row["net_mean_usd_fee0.01"], -0.0133333333)
        self.assertAlmostEqual(row["hit_rate_fee0.01"], 0.0)
        self.assertEqual(row["days_net_positive_fee0.01"], 0)

    def test_no_trades_at_all_gives_nan_not_zero(self):
        row = R.pooled_stats([fake_result([]), fake_result([])], (0.0,))
        self.assertEqual(row["trades"], 0)
        self.assertTrue(np.isnan(row["net_mean_usd_fee0.0"]))
        self.assertTrue(np.isnan(row["gross_mean_ticks"]))
        self.assertEqual(row["days_net_positive_fee0.0"], 0)


class FrozenDecisions(unittest.TestCase):
    """The v2 choices written in docs/design.md. Changing one after results exist must be
    logged (config.py docstring), so a silent edit has to fail a test."""

    def test_v2_constants(self):
        self.assertEqual(C.HOLD_NS, 100_000_000)
        self.assertEqual(C.REF_LATENCY_NS, 100_000)
        self.assertEqual(C.REF_FEE_PER_SHARE, 0.001)
        self.assertEqual(C.MIN_TRADES_SELECT, 100)
        self.assertEqual(C.RANDOM_REPS, 200)
        self.assertEqual(C.RANDOM_SEED, 20261025)

    def test_v2_grid(self):
        self.assertEqual(C.THRESHOLDS, (0.2, 0.4, 0.6, 0.8))
        self.assertEqual(C.SPREAD_LIMITS_TICKS, (1, 2, None))
        self.assertEqual(C.LATENCIES_NS, (0, 10_000, 100_000, 1_000_000))
        self.assertEqual(C.FEES_PER_SHARE, (0.0, 0.001, 0.003))
        self.assertEqual(len(R.variants()), 12)

    def test_reference_cell_is_inside_the_grid(self):
        self.assertIn(C.REF_LATENCY_NS, C.LATENCIES_NS)
        self.assertIn(C.REF_FEE_PER_SHARE, C.FEES_PER_SHARE)


if __name__ == "__main__":
    unittest.main()
