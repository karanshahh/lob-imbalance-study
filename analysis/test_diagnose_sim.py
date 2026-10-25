"""Tests for analysis/diagnose_sim.py. Prices are ITCH units; one tick = 100 units."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as C  # noqa: E402
import diagnose_sim as D  # noqa: E402
import sim  # noqa: E402
import test_sim as T  # noqa: E402

MS = T.MS


class KnownAnswers(unittest.TestCase):
    def test_long_trade_by_hand(self):
        # Row 0: bid 10000, ask 10100, I = 0.8. Buy at 10100.
        # Row 100 ms: bid 10200, ask 10400. Exit sells at 10200. Gross = 100 units = 1.0 tick.
        # Entry mid 10050, exit mid 10300: signed move 250 units = 2.5 ticks.
        # Entry half spread 50 units = 0.5 tick, exit half spread 100 units = 1.0 tick.
        # Check: 2.5 - 0.5 - 1.0 = 1.0.
        rows = [(0, 10000, 90, 10100, 10), (100, 10200, 50, 10400, 50)]
        d = D.decompose(T.day(rows), 0.2, None, 0, 100 * MS)
        self.assertEqual((d["n_trades"], d["n_usable"]), (1, 1))
        self.assertAlmostEqual(d["entry_half"][0], 0.5)
        self.assertAlmostEqual(d["exit_half"][0], 1.0)
        self.assertAlmostEqual(d["signed_move"][0], 2.5)
        self.assertAlmostEqual(d["gross"][0], 1.0)
        self.assertAlmostEqual(d["identity_error"][0], 0.0)

    def test_short_trade_by_hand(self):
        # I = -0.8: sell at bid 10000. Row 100 ms: bid 9800, ask 9900. Exit buys at 9900.
        # Gross = -(9900 - 10000) = +100 units = 1.0 tick. Entry mid 10050, exit mid 9850:
        # raw move -200, signed move (side -1) = +200 units = 2.0 ticks.
        # Half spreads 0.5 and 0.5 ticks. Check: 2.0 - 0.5 - 0.5 = 1.0.
        rows = [(0, 10000, 10, 10100, 90), (100, 9800, 50, 9900, 50)]
        d = D.decompose(T.day(rows), 0.2, None, 0, 100 * MS)
        self.assertAlmostEqual(d["signed_move"][0], 2.0)
        self.assertAlmostEqual(d["entry_half"][0], 0.5)
        self.assertAlmostEqual(d["exit_half"][0], 0.5)
        self.assertAlmostEqual(d["gross"][0], 1.0)
        self.assertAlmostEqual(d["identity_error"][0], 0.0)

    def test_latency_uses_the_fill_rows(self):
        # LONG_ROWS with L = 60 ms: entry row is 50 ms (bid 10100, ask 10200), exit row is
        # 200 ms (bid 10400, ask 10500). Entry mid 10150, exit mid 10450: move 300 = 3 ticks.
        # Half spreads 0.5 and 0.5. Gross = 10400 - 10200 = 200 units = 2.0 ticks = 3 - 1.
        d = D.decompose(T.day(T.LONG_ROWS), 0.2, None, 60 * MS, 100 * MS)
        self.assertAlmostEqual(d["signed_move"][0], 3.0)
        self.assertAlmostEqual(d["gross"][0], 2.0)
        self.assertAlmostEqual(d["identity_error"][0], 0.0)

    def test_trade_with_a_missing_side_is_not_decomposable(self):
        # The exit row has a bid (so the trade fills) but no ask, so its mid is undefined
        # and the trade cannot be decomposed. It still counts in n_trades.
        rows = [(0, 10000, 90, 10100, 10), (100, 10200, 50, 0, 0)]
        d = D.decompose(T.day(rows), 0.2, None, 0, 100 * MS)
        self.assertEqual(d["n_trades"], 1)
        self.assertEqual(d["n_usable"], 0)
        self.assertEqual(len(d["gross"]), 0)

    def test_no_trades(self):
        d = D.decompose(T.day([(0, 10000, 50, 10100, 50)]), 0.2, None, 0, 100 * MS)
        self.assertEqual((d["n_trades"], d["n_usable"]), (0, 0))


class Identity(unittest.TestCase):
    def test_identity_holds_on_random_books(self):
        rng = np.random.default_rng(777)
        checked = 0
        for _ in range(40):
            rows = T.random_rows(rng, int(rng.integers(30, 200)))
            data = [(i, T.BASE + t, bp, bq, ap, aq) for i, (t, bp, bq, ap, aq) in enumerate(rows)]
            day = sim.Day(sim.collapse(pd.DataFrame(data, columns=sim.COLUMNS, dtype=np.int64)))
            for lat in (0, 100_000, 30 * MS):
                d = D.decompose(day, 0.2, None, lat, 100 * MS)
                checked += d["n_usable"]
                if d["n_usable"]:
                    self.assertLess(float(d["identity_error"].max()), 1e-9)
        self.assertGreater(checked, 300)   # not vacuous

    def test_pooling_adds_trades_and_averages(self):
        a = D.decompose(T.day([(0, 10000, 90, 10100, 10), (100, 10200, 50, 10400, 50)]),
                        0.2, None, 0, 100 * MS)
        b = D.decompose(T.day([(0, 10000, 10, 10100, 90), (100, 9800, 50, 9900, 50)]),
                        0.2, None, 0, 100 * MS)
        p = D.pool([a, b])
        self.assertEqual((p["trades"], p["usable_trades"]), (2, 2))
        self.assertAlmostEqual(p["signed_move_ticks"], (2.5 + 2.0) / 2)
        self.assertAlmostEqual(p["entry_half_ticks"], 0.5)
        self.assertAlmostEqual(p["exit_half_ticks"], (1.0 + 0.5) / 2)
        self.assertAlmostEqual(p["gross_ticks"], 1.0)
        self.assertAlmostEqual(p["max_identity_error_ticks"], 0.0)


class Scope(unittest.TestCase):
    def test_diagnostic_never_references_held_out_days(self):
        with open(D.__file__) as f:
            self.assertNotIn("HELDOUT_DAYS", f.read())


if __name__ == "__main__":
    unittest.main()
