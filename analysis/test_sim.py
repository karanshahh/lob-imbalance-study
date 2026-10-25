"""Known-answer tests for analysis/sim.py. Every expected value is worked out by hand
in the comment above it. Prices are ITCH units: 10100 = $1.0100, one tick = 100 units."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as C  # noqa: E402
import sim  # noqa: E402

MS = 1_000_000
BASE = C.SESSION_START_NS + 1_000_000_000  # one second after the session opens


def frame(rows, base=BASE):
    """rows: (ms, bid_px, bid_qty, ask_px, ask_qty); ms is the offset from `base`."""
    data = [(i, base + ms * MS, bp, bq, ap, aq) for i, (ms, bp, bq, ap, aq) in enumerate(rows)]
    return pd.DataFrame(data, columns=sim.COLUMNS, dtype=np.int64)


def day(rows, base=BASE):
    return sim.Day(sim.collapse(frame(rows, base)))


def run(rows, thr=0.2, limit=None, lat=0, hold=100 * MS, base=BASE):
    return sim.simulate(day(rows, base), thr, limit, lat, hold)


# Rows used by several tests. Row 0 has I = (90-10)/100 = 0.8 and a one-tick spread; the
# rest are balanced (I = 0), so only row 0 fires the rule.
LONG_ROWS = [
    (0, 10000, 90, 10100, 10),
    (50, 10100, 50, 10200, 50),
    (100, 10200, 50, 10300, 50),
    (200, 10400, 50, 10500, 50),
    (250, 10400, 50, 10500, 50),
]


class Entry(unittest.TestCase):
    def test_long_latency_zero(self):
        # Entry: buy at the ask of row 0 = 10100. Exit fills at 0 + 100 ms: last row with
        # ts <= 100 ms is row 100, bid 10200. Gross = 10200 - 10100 = 100 units = $0.01.
        r = run(LONG_ROWS, lat=0)
        self.assertEqual(r.n, 1)
        self.assertEqual(list(r.side), [1])
        self.assertEqual(list(r.gross_units), [100])
        self.assertEqual(r.exit_ts[0], BASE + 100 * MS)

    def test_long_latency_60ms(self):
        # L = 60 ms. Entry row: last ts <= 60 ms is row 50, ask 10200. Exit fills at
        # 100 + 2*60 = 220 ms: last row ts <= 220 is row 200, bid 10400.
        # Gross = 10400 - 10200 = 200 units.
        r = run(LONG_ROWS, lat=60 * MS)
        self.assertEqual(r.n, 1)
        self.assertEqual(list(r.gross_units), [200])
        self.assertEqual(r.exit_ts[0], BASE + 220 * MS)

    def test_short(self):
        # I = (10-90)/100 = -0.8: sell at the bid of row 0 = 10000. Exit buys at the ask
        # of row 100 = 9900. Gross = -(9900 - 10000) = +100 units.
        rows = [(0, 10000, 10, 10100, 90), (100, 9800, 50, 9900, 50)]
        r = run(rows)
        self.assertEqual(list(r.side), [-1])
        self.assertEqual(list(r.gross_units), [100])

    def test_fee_on_both_legs(self):
        # Gross 100 units = $0.01. Fee $0.003 on both legs: 0.01 - 0.006 = 0.004.
        r = run(LONG_ROWS)
        self.assertAlmostEqual(sim.net_dollars(r.gross_units, 0.0)[0], 0.01)
        self.assertAlmostEqual(sim.net_dollars(r.gross_units, 0.001)[0], 0.008)
        self.assertAlmostEqual(sim.net_dollars(r.gross_units, 0.003)[0], 0.004)

    def test_no_look_ahead(self):
        # Changing rows after the entry fill changes the exit price, never the entry.
        a = run(LONG_ROWS)
        changed = [row for row in LONG_ROWS]
        changed[2] = (100, 10600, 50, 10700, 50)
        b = run(changed)
        self.assertEqual(a.entry_ts[0], b.entry_ts[0])
        self.assertEqual(b.gross_units[0], 10600 - 10100)
        self.assertNotEqual(a.gross_units[0], b.gross_units[0])


class Filters(unittest.TestCase):
    def test_threshold_boundary(self):
        # I = (70-30)/100 = 0.4 exactly: passes 0.4, fails 0.6.
        rows = [(0, 10000, 70, 10100, 30), (100, 10000, 50, 10100, 50)]
        self.assertEqual(run(rows, thr=0.4).n, 1)
        self.assertEqual(run(rows, thr=0.6).n, 0)

    def test_spread_limit(self):
        # Spread 300 units = 3 ticks. Limits 1 and 2 reject it; None accepts it.
        rows = [(0, 10000, 90, 10300, 10), (100, 10000, 50, 10300, 50)]
        self.assertEqual(run(rows, limit=1).n, 0)
        self.assertEqual(run(rows, limit=2).n, 0)
        self.assertEqual(run(rows, limit=None).n, 1)

    def test_spread_limit_boundary(self):
        # Spread 200 units = 2 ticks: passes limit 2, fails limit 1.
        rows = [(0, 10000, 90, 10200, 10), (100, 10000, 50, 10200, 50)]
        self.assertEqual(run(rows, limit=2).n, 1)
        self.assertEqual(run(rows, limit=1).n, 0)

    def test_session_window(self):
        rows = [(0, 10000, 90, 10100, 10), (100, 10000, 50, 10100, 50)]
        before = C.SESSION_START_NS - 1_000_000
        self.assertEqual(run(rows, base=before).n, 0)           # 09:34:59.999
        self.assertEqual(run(rows, base=C.SESSION_START_NS).n, 1)  # 09:35:00 inclusive
        self.assertEqual(run(rows, base=C.SESSION_END_NS).n, 1)    # 15:55:00 inclusive
        self.assertEqual(run(rows, base=C.SESSION_END_NS + 1_000_000).n, 0)

    def test_one_sided_and_crossed_rows_never_fire(self):
        rows = [
            (0, 0, 0, 10100, 100),        # no bid: imbalance undefined
            (10, 10000, 100, 0, 0),       # no ask
            (20, 10100, 90, 10000, 10),   # crossed book (bid > ask)
            (30, 10000, 90, 10000, 10),   # locked book (spread 0)
            (200, 10000, 50, 10100, 50),
        ]
        self.assertEqual(run(rows).n, 0)
        self.assertEqual(day(rows).candidates(0.2, None).size, 0)

    def test_same_timestamp_keeps_last_row(self):
        # Two rows share a timestamp: only the later one (seq 1) is a real state.
        # It is balanced, so nothing fires even though seq 0 had I = 0.8.
        df = pd.DataFrame(
            [(0, BASE, 10000, 90, 10100, 10), (1, BASE, 10000, 50, 10100, 50),
             (2, BASE + 100 * MS, 10000, 50, 10100, 50)],
            columns=sim.COLUMNS, dtype=np.int64)
        d = sim.Day(sim.collapse(df))
        self.assertEqual(d.n, 2)
        self.assertEqual(sim.simulate(d, 0.2, None, 0, 100 * MS).n, 0)


class Position(unittest.TestCase):
    def test_one_position_at_a_time(self):
        # Rows 0, 50, 100 all fire (I = 0.8). Trade 1 at 0 exits at 100 ms. The signal at
        # 50 ms is inside that window and ignored. The signal at 100 ms is allowed
        # (100 >= 100) and exits at 200 ms: row 200 is balanced.
        rows = [
            (0, 10000, 90, 10100, 10),
            (50, 10000, 90, 10100, 10),
            (100, 10000, 90, 10100, 10),
            (200, 10200, 50, 10300, 50),
        ]
        r = run(rows)
        self.assertEqual(r.n, 2)
        self.assertEqual(list(r.entry_ts - BASE), [0, 100 * MS])
        # trade 1: buy 10100, sell at row 100 bid 10000 -> -100. trade 2: buy 10100,
        # exit fills at 200 ms, bid 10200 -> +100.
        self.assertEqual(list(r.gross_units), [-100, 100])

    def test_constant_book_every_trade_loses_one_spread(self):
        # Bid 10000, ask 10100 for 101 rows, 10 ms apart, always I = 0.8. Entries at
        # 0, 100, ..., 1000 ms = 11 trades. Each buys 10100 and sells 10000: -100 units.
        rows = [(10 * k, 10000, 90, 10100, 10) for k in range(101)]
        r = run(rows)
        self.assertEqual(r.n, 11)
        self.assertTrue(np.all(r.gross_units == -100))
        self.assertAlmostEqual(float(sim.net_dollars(r.gross_units, 0.0).mean()), -0.01)


class EdgeCases(unittest.TestCase):
    def test_entry_side_empty_after_latency_is_skipped(self):
        # L = 60 ms: entry row is row 50, whose ask side is empty -> skipped, counted.
        rows = [(0, 10000, 90, 10100, 10), (50, 10000, 50, 0, 0), (300, 10000, 50, 10100, 50)]
        r = run(rows, lat=60 * MS)
        self.assertEqual(r.n, 0)
        self.assertEqual(r.entry_empty, 1)
        self.assertEqual(r.exit_unavailable, 0)

    def test_exit_uses_first_later_row_with_the_side(self):
        # Exit time 100 ms: row 100 has no bid, so the exit waits for row 150 (bid 10200).
        # Gross = 10200 - 10100 = 100; exit fill time = 150 ms.
        rows = [
            (0, 10000, 90, 10100, 10),
            (100, 0, 0, 10300, 50),
            (150, 10200, 50, 10300, 50),
        ]
        r = run(rows)
        self.assertEqual(r.n, 1)
        self.assertEqual(list(r.gross_units), [100])
        self.assertEqual(r.exit_ts[0], BASE + 150 * MS)

    def test_exit_with_no_later_row_is_dropped(self):
        rows = [(0, 10000, 90, 10100, 10), (100, 0, 0, 10300, 50)]
        r = run(rows)
        self.assertEqual(r.n, 0)
        self.assertEqual(r.exit_unavailable, 1)

    def test_exit_after_close_is_dropped(self):
        # Signal at 15:55:00, hold 400 s -> exit time 16:01:40, past the close.
        rows = [(0, 10000, 90, 10100, 10), (1000, 10000, 50, 10100, 50)]
        r = run(rows, hold=400 * 1_000_000_000, base=C.SESSION_END_NS)
        self.assertEqual(r.n, 0)
        self.assertEqual(r.exit_unavailable, 1)

    def test_skipped_entry_does_not_block_the_next_signal(self):
        # L = 40 ms. Signal at 0: its entry row is the last row with ts <= 40, row 30,
        # which has no ask -> skipped, no position opened. Signal at 50 is then free to
        # trade: entry row is the last ts <= 90, row 80 (ask 10100). Its exit fills at
        # 50 + 100 + 80 = 230 ms: last row ts <= 230 is row 80, bid 10000.
        # Gross = 10000 - 10100 = -100. The signal at 80 is inside the open position.
        rows = [
            (0, 10000, 90, 10100, 10),
            (30, 10000, 50, 0, 0),
            (50, 10000, 90, 10100, 10),
            (80, 10000, 90, 10100, 10),
        ]
        r = run(rows, lat=40 * MS)
        self.assertEqual(r.entry_empty, 1)
        self.assertEqual(r.n, 1)
        self.assertEqual(list(r.entry_ts - BASE), [50 * MS])
        self.assertEqual(list(r.gross_units), [-100])


class InputChecks(unittest.TestCase):
    def test_non_monotonic_timestamps_are_rejected(self):
        # seq order says row 1 happens before row 0 in time: the data is not usable.
        df = pd.DataFrame(
            [(0, BASE + 100 * MS, 10000, 50, 10100, 50), (1, BASE, 10000, 50, 10100, 50)],
            columns=sim.COLUMNS, dtype=np.int64)
        with self.assertRaises(ValueError):
            sim.Day(sim.collapse(df))

    def test_wrong_columns_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.csv")
            with open(path, "w") as f:
                f.write("a,b\n1,2\n")
            with self.assertRaises(ValueError):
                sim.load_day(path)


class Determinism(unittest.TestCase):
    def test_same_input_same_output(self):
        rows = [(10 * k, 10000, 90, 10100, 10) for k in range(101)]
        a, b = run(rows), run(rows)
        self.assertEqual(list(a.entry_ts), list(b.entry_ts))
        self.assertEqual(list(a.gross_units), list(b.gross_units))


class Stats(unittest.TestCase):
    def test_sharpe_known_answer(self):
        # x = [2, 0, 2, 0]: mean 1, sample variance 4/3, sr = 1/sqrt(4/3) = sqrt(3)/2.
        # se = sqrt((1 + 0.5 * 0.75) / 4) = sqrt(0.34375).
        n, mean, sr, se = sim.sharpe_stats([2, 0, 2, 0])
        self.assertEqual(n, 4)
        self.assertAlmostEqual(mean, 1.0)
        self.assertAlmostEqual(sr, 0.8660254037844386)
        self.assertAlmostEqual(se, 0.5863019699779287)

    def test_sharpe_degenerate(self):
        self.assertTrue(np.isnan(sim.sharpe_stats([1.0])[2]))
        self.assertTrue(np.isnan(sim.sharpe_stats([1.0, 1.0, 1.0])[2]))


class RandomBaseline(unittest.TestCase):
    def test_constant_book_baseline_is_exactly_minus_one_spread(self):
        # In the constant book both directions lose exactly 100 units, so every
        # repetition has mean -0.01 whatever the directions drawn.
        rows = [(10 * k, 10000, 90, 10100, 10) for k in range(101)]
        r = run(rows)
        means = sim.random_direction_means(
            r.long_gross, r.long_ok, r.short_gross, r.short_ok, 0.0, 200, 7)
        self.assertEqual(len(means), 200)
        self.assertTrue(np.allclose(means, -0.01))
        # Fee $0.003 on both legs adds -0.006: -0.01 - 0.006 = -0.016.
        with_fee = sim.random_direction_means(
            r.long_gross, r.long_ok, r.short_gross, r.short_ok, 0.003, 200, 7)
        self.assertTrue(np.allclose(with_fee, -0.016))

    def test_reproducible_and_seed_dependent(self):
        lg = np.array([100, -100, 50, -50, 0, 200, -200, 10], dtype=np.int64)
        sg = np.array([-100, 100, -50, 50, 0, -200, 200, -10], dtype=np.int64)
        ok = np.ones(8, dtype=bool)
        a = sim.random_direction_means(lg, ok, sg, ok, 0.0, 50, 1)
        b = sim.random_direction_means(lg, ok, sg, ok, 0.0, 50, 1)
        c = sim.random_direction_means(lg, ok, sg, ok, 0.0, 50, 2)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))

    def test_unfillable_random_directions_are_dropped(self):
        # Only the long direction is fillable. Reps that draw 'short' for the single
        # trade have no trade left (nan); reps that draw 'long' give 100 units = 0.01.
        lg = np.array([100], dtype=np.int64)
        sg = np.array([0], dtype=np.int64)
        means = sim.random_direction_means(
            lg, np.array([True]), sg, np.array([False]), 0.0, 400, 3)
        finite = means[~np.isnan(means)]
        self.assertTrue(0 < len(finite) < 400)
        self.assertTrue(np.allclose(finite, 0.01))


def reference(rows, base, thr, limit, lat, hold):
    """Slow, plain-Python implementation of the written rules. Shares no code with sim.py.

    rows: (offset_ns, bid_px, bid_qty, ask_px, ask_qty), one row per distinct timestamp,
    in time order. Returns (entry_ts, side, gross, exit_ts, entry_empty, exit_unavailable).
    """
    ts = [base + r[0] for r in rows]
    bp = [r[1] for r in rows]
    bq = [r[2] for r in rows]
    ap = [r[3] for r in rows]
    aq = [r[4] for r in rows]
    n = len(rows)
    entry_ts, sides, gross, exit_ts = [], [], [], []
    entry_empty = exit_unavail = 0
    next_free = -1
    for i in range(n):
        t = ts[i]
        if t < next_free:
            continue
        if not (C.SESSION_START_NS <= t <= C.SESSION_END_NS):
            continue
        if not (bq[i] > 0 and bp[i] > 0 and aq[i] > 0 and ap[i] > 0 and ap[i] - bp[i] > 0):
            continue
        imb = (bq[i] - aq[i]) / (bq[i] + aq[i])
        if abs(imb) < thr:
            continue
        if limit is not None and ap[i] - bp[i] > limit * C.TICK:
            continue
        side = 1 if imb > 0 else -1
        e = max(k for k in range(n) if ts[k] <= t + lat)
        entry_px = ap[e] if side == 1 else bp[e]
        entry_ok = (aq[e] > 0 and ap[e] > 0) if side == 1 else (bq[e] > 0 and bp[e] > 0)
        if not entry_ok:
            entry_empty += 1
            continue
        tf = t + hold + 2 * lat
        r = max(k for k in range(n) if ts[k] <= tf)
        j = None
        for k in range(r, n):
            usable = (bq[k] > 0 and bp[k] > 0) if side == 1 else (aq[k] > 0 and ap[k] > 0)
            if usable:
                j = k
                break
        if j is None or max(tf, ts[j]) >= C.CLOSE_NS:
            exit_unavail += 1
            continue
        exit_px = bp[j] if side == 1 else ap[j]
        entry_ts.append(t)
        sides.append(side)
        gross.append(side * (exit_px - entry_px))
        exit_ts.append(max(tf, ts[j]))
        next_free = max(tf, ts[j])
    return entry_ts, sides, gross, exit_ts, entry_empty, exit_unavail


def random_rows(rng, n):
    """Random book with ns offsets: mixed gaps, some crossed or locked rows, some empty sides."""
    rows = []
    t = 0
    mid = 10000
    for _ in range(n):
        t += int(rng.choice([10_000, 100_000, 1_000_000, 5_000_000, 20_000_000,
                             60_000_000, 150_000_000]))
        mid += int(rng.integers(-60, 61))
        spread = int(rng.choice([100, 100, 200, 300, 50, 0, -50]))
        bid, ask = mid - spread // 2, mid + (spread - spread // 2)
        bq, aq = int(rng.integers(1, 100)), int(rng.integers(1, 100))
        if rng.random() < 0.08:
            bid, bq = 0, 0
        if rng.random() < 0.08:
            ask, aq = 0, 0
        rows.append((t, bid, bq, ask, aq))
    return rows


def simulate_ns(rows, thr, limit, lat, hold):
    data = [(i, BASE + t, bp, bq, ap, aq) for i, (t, bp, bq, ap, aq) in enumerate(rows)]
    df = pd.DataFrame(data, columns=sim.COLUMNS, dtype=np.int64)
    return sim.simulate(sim.Day(sim.collapse(df)), thr, limit, lat, hold)


class MatchesReference(unittest.TestCase):
    def test_random_books_match_the_slow_reference(self):
        rng = np.random.default_rng(12345)
        checked = trades = 0
        for _ in range(60):
            rows = random_rows(rng, int(rng.integers(30, 200)))
            for thr in (0.2, 0.6):
                for limit in (1, 2, None):
                    for lat in (0, 10_000, 100_000, 1_000_000, 30 * MS):
                        got = simulate_ns(rows, thr, limit, lat, 100 * MS)
                        want = reference(rows, BASE, thr, limit, lat, 100 * MS)
                        self.assertEqual(list(got.entry_ts), want[0])
                        self.assertEqual(list(got.side), want[1])
                        self.assertEqual(list(got.gross_units), want[2])
                        self.assertEqual(list(got.exit_ts), want[3])
                        self.assertEqual((got.entry_empty, got.exit_unavailable), want[4:])
                        checked += 1
                        trades += got.n
        self.assertEqual(checked, 60 * 2 * 3 * 5)
        self.assertGreater(trades, 500)   # the comparison must not be vacuous


if __name__ == "__main__":
    unittest.main()
