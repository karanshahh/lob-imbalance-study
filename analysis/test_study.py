"""Known-answer tests for the signal functions. Run: python3 -m unittest discover -s analysis"""
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

import config as C
import run_signal_study
import study


def frame(rows):
    return pd.DataFrame(rows, columns=study.COLUMNS).astype("int64")


class MidAndImbalance(unittest.TestCase):
    def test_known_answer(self):
        mid, imb = study.mid_and_imbalance(frame([[0, 1, 10000, 300, 10100, 100]]))
        self.assertAlmostEqual(mid[0], 100.5)      # ($1.00 + $1.01) / 2 = 100.5 cents
        self.assertAlmostEqual(imb[0], 0.5)        # (300 - 100) / 400

    def test_more_on_the_ask_is_negative(self):
        _, imb = study.mid_and_imbalance(frame([[0, 1, 10000, 100, 10100, 300]]))
        self.assertAlmostEqual(imb[0], -0.5)

    def test_one_sided_rows_are_nan(self):
        mid, imb = study.mid_and_imbalance(frame([[0, 1, 10000, 300, 0, 0], [1, 2, 0, 0, 10100, 5]]))
        self.assertTrue(np.isnan(mid).all() and np.isnan(imb).all())


class Collapse(unittest.TestCase):
    def test_keeps_last_row_per_timestamp(self):
        df = frame([[0, 5, 10000, 1, 10100, 1], [1, 9, 0, 0, 10100, 1], [2, 9, 10050, 8, 10100, 1]])
        out = study.collapse_same_timestamp(df)
        self.assertEqual(list(out["seq"]), [0, 2])


class ForwardChanges(unittest.TestCase):
    ts = np.array([0, 50, 100, 150], dtype=np.int64)
    mid = np.array([1.0, 2.0, 4.0, 7.0])

    def test_event_horizons(self):
        np.testing.assert_array_equal(study.forward_change_events(self.mid, self.ts, 1), [1, 2, 3, np.nan])
        np.testing.assert_array_equal(study.forward_change_events(self.mid, self.ts, 2), [3, 5, np.nan, np.nan])

    def test_event_horizon_after_close_is_nan(self):
        ts = np.array([C.CLOSE_NS - 1, C.CLOSE_NS + 1], dtype=np.int64)
        self.assertTrue(np.isnan(study.forward_change_events(np.array([1.0, 2.0]), ts, 1)[0]))

    def test_time_horizon_includes_row_exactly_at_t_plus_tau(self):
        d = study.forward_change_time(self.mid, self.ts, 100)
        np.testing.assert_array_equal(d[:2], [3.0, 5.0])   # t=0 -> state at 100; t=50 -> state at 150
        self.assertTrue(np.isnan(d[2]) and np.isnan(d[3]))  # t+100 is past the last row

    def test_time_horizon_uses_state_in_force_not_next_row(self):
        d = study.forward_change_time(self.mid, self.ts, 70)
        self.assertEqual(d[0], 1.0)                         # at t=70 the row from t=50 is in force


class Session(unittest.TestCase):
    def test_boundaries(self):
        ts = np.array([C.SESSION_START_NS - 1, C.SESSION_START_NS, C.SESSION_END_NS, C.SESSION_END_NS + 1])
        self.assertEqual(list(study.in_session(ts)), [False, True, True, False])

    def test_start_is_0935(self):
        self.assertEqual(C.SESSION_START_NS, 34_500 * C.NS)


class NoLookAhead(unittest.TestCase):
    def test_signal_at_i_ignores_later_rows(self):
        a = frame([[0, 1, 10000, 300, 10100, 100], [1, 2, 10000, 10, 10100, 900]])
        b = frame([[0, 1, 10000, 300, 10100, 100], [1, 2, 9000, 1, 9100, 1]])
        self.assertEqual(study.mid_and_imbalance(a)[1][0], study.mid_and_imbalance(b)[1][0])


class Stats(unittest.TestCase):
    def test_a_cheating_signal_is_detected(self):
        rng = np.random.default_rng(1)
        change = rng.integers(-2, 3, 5000).astype(float)
        s, _ = study.signal_stats(change / 2.0, change)      # "signal" = the future change itself
        self.assertGreater(s["corr"], 0.999)

    def test_noise_gives_about_zero(self):
        rng = np.random.default_rng(2)
        s, _ = study.signal_stats(rng.uniform(-1, 1, 20000), rng.normal(size=20000))
        self.assertLess(abs(s["corr"]), 0.03)

    def test_known_slope_share_zero_and_buckets(self):
        x = np.array([-0.8, -0.4, 0.0, 0.4, 0.8])
        y = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        s, b = study.signal_stats(x, y)
        self.assertAlmostEqual(s["slope"], 2.5)
        self.assertAlmostEqual(s["share_zero"], 0.2)
        self.assertEqual(b, [-2.0, -1.0, 0.0, 1.0, 2.0])

    def test_rows_with_nan_are_dropped(self):
        s, _ = study.signal_stats(np.array([0.5, np.nan, 0.1]), np.array([1.0, 1.0, np.nan]))
        self.assertEqual(s["n"], 1)


class DayStats(unittest.TestCase):
    def test_runs_on_a_small_day(self):
        t0 = C.SESSION_START_NS
        rows = [[i, t0 + i * 1_000_000, 10000 + (i % 3) * 100, 100 + i, 10300, 200] for i in range(500)]
        out, info = study.day_stats(frame(rows))
        self.assertEqual([r["horizon"] for r in out], ["1ev", "10ev", "100ev", "100ms", "1s", "10s"])
        self.assertEqual(info["rows_raw"], 500)


class HeldOutLock(unittest.TestCase):
    def test_second_claim_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            run_signal_study.claim_heldout(d)
            self.assertTrue(os.path.exists(os.path.join(d, "HELDOUT_USED")))
            with self.assertRaises(SystemExit):
                run_signal_study.claim_heldout(d)

    def test_heldout_without_final_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                run_signal_study.main(["--export-dir", d, "--set", "heldout", "--out", d, "--results-root", d])
            self.assertFalse(os.path.exists(os.path.join(d, "HELDOUT_USED")))


if __name__ == "__main__":
    unittest.main()
