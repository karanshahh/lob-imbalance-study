"""Tests for analysis/run_heldout_sim.py: the frozen H2 rule, the one-use lock, and the
rehearsal mode. Synthetic exports only; no real held-out data is read."""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import run_heldout_sim as H  # noqa: E402
import run_strategy_sim as R  # noqa: E402
import test_run_strategy_sim as TR  # noqa: E402

MS = 1_000_000
BASE = C.SESSION_START_NS + 1_000_000_000
KEY = R.fee_key(C.REF_FEE_PER_SHARE)


def write_book(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("seq,ts_ns,bid_px,bid_qty,ask_px,ask_qty\n")
        for k, (ms, bp, bq, ap, aq) in enumerate(rows):
            f.write(f"{k},{BASE + ms * MS},{bp},{bq},{ap},{aq}\n")


# One long trade per day: buy 10100, exit at 100 ms into bid 10300: +200 units, net +0.018
# at the reference fee. Every day is positive.
WINNING = [(0, 10000, 90, 10100, 10), (100, 10300, 50, 10400, 50)]


def make_exports(root, days, winners=("SPY",)):
    for d in days:
        for s in C.SYMBOLS:
            path = os.path.join(root, d, f"{s}.csv")
            if s in winners:
                write_book(path, WINNING)
            else:
                TR.write_constant_book(path)    # every trade loses one spread


def write_selection(path, none_for=()):
    syms = []
    for s in C.SYMBOLS:
        sel = None if s in none_for else {"threshold": 0.2, "spread_limit_ticks": "1",
                                          "dev_trades": 500, "dev_net_mean_usd_at_ref": -0.01}
        syms.append({"symbol": s, "selected": sel})
    with open(path, "w") as f:
        json.dump({"rule": "test", "symbols": syms}, f)


def grid_row(sym, day, trades, net, thr=0.2, lim="1", lat=None):
    return {"symbol": sym, "day": day, "threshold": thr, "spread_limit_ticks": lim,
            "latency_ns": C.REF_LATENCY_NS if lat is None else lat, "trades": trades, KEY: net}


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


class Verdict(unittest.TestCase):
    def sel(self, none_for=()):
        return {"symbols": [{"symbol": s, "selected": None if s in none_for else
                             {"threshold": 0.2, "spread_limit_ticks": "1"}} for s in C.SYMBOLS]}

    def rows_for(self, sym, nets, trades=10, **kw):
        return [grid_row(sym, f"d{i}", trades if n == n else 0, n, **kw) for i, n in enumerate(nets)]

    def verdict_for(self, grid, sym="SPY", n_days=4, none_for=()):
        full = list(grid)
        for s in C.SYMBOLS:
            if s != sym:
                full += self.rows_for(s, [-0.01] * n_days)
        summary, per_day = H.verdict_rows(full, self.sel(none_for), n_days)
        return {r["symbol"]: r for r in summary}[sym], per_day

    def test_positive_on_all_days_rejects(self):
        v, _ = self.verdict_for(self.rows_for("SPY", [0.01, 0.002, 0.03, 0.001]))
        self.assertTrue(v["h2_rejected"])
        self.assertEqual(v["days_net_positive"], 4)

    def test_one_negative_day_does_not_reject(self):
        v, _ = self.verdict_for(self.rows_for("SPY", [0.01, 0.002, -0.0001, 0.001]))
        self.assertFalse(v["h2_rejected"])
        self.assertEqual(v["days_net_positive"], 3)

    def test_exactly_zero_is_not_positive(self):
        v, _ = self.verdict_for(self.rows_for("SPY", [0.01, 0.0, 0.01, 0.01]))
        self.assertFalse(v["h2_rejected"])
        self.assertEqual(v["days_net_positive"], 3)

    def test_a_day_with_no_trades_is_not_positive(self):
        v, _ = self.verdict_for(self.rows_for("SPY", [0.01, float("nan"), 0.01, 0.01]))
        self.assertFalse(v["h2_rejected"])
        self.assertEqual(v["days_net_positive"], 3)

    def test_symbol_without_selection_is_not_rejected(self):
        v, per_day = self.verdict_for(self.rows_for("SPY", [0.5] * 4), none_for=("SPY",))
        self.assertFalse(v["h2_rejected"])
        self.assertEqual(v["days_net_positive"], 0)
        self.assertEqual([d for d in per_day if d["symbol"] == "SPY"], [])

    def test_only_the_selected_variant_counts(self):
        # The selected variant (0.2, "1") loses; another variant of the same symbol wins on
        # every day. The other variant must not matter.
        grid = (self.rows_for("SPY", [-0.01] * 4)
                + self.rows_for("SPY", [0.5] * 4, thr=0.8)
                + self.rows_for("SPY", [0.5] * 4, lim="2"))
        v, _ = self.verdict_for(grid)
        self.assertFalse(v["h2_rejected"])

    def test_only_the_reference_latency_counts(self):
        grid = self.rows_for("SPY", [-0.01] * 4) + self.rows_for("SPY", [0.5] * 4, lat=0)
        v, _ = self.verdict_for(grid)
        self.assertFalse(v["h2_rejected"])

    def test_only_the_reference_fee_counts(self):
        rows = self.rows_for("SPY", [-0.01] * 4)
        for r in rows:
            r[R.fee_key(0.0)] = 0.5          # another fee column that would reject
        v, _ = self.verdict_for(rows)
        self.assertFalse(v["h2_rejected"])

    def test_wrong_number_of_day_rows_is_an_error(self):
        with self.assertRaises(RuntimeError):
            self.verdict_for(self.rows_for("SPY", [0.01] * 3))

    def test_text_reports_counts_and_chance(self):
        v, per_day = self.verdict_for(self.rows_for("SPY", [0.01] * 4))
        summary, per_day = H.verdict_rows(
            self.rows_for("SPY", [0.01] * 4) + sum((self.rows_for(s, [-0.01] * 4)
                                                    for s in C.SYMBOLS if s != "SPY"), []),
            self.sel(), 4)
        text = H.verdict_text(summary, per_day, ("a", "b", "c", "d"), rehearsal=False)
        self.assertIn("H2 rejected for 1 of 5 symbols", text)
        self.assertIn("0.31", text)       # 5 / 16
        self.assertNotIn("REHEARSAL", text)
        text = H.verdict_text(summary, per_day, ("a", "b", "c", "d"), rehearsal=True)
        self.assertIn("REHEARSAL", text)


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        self.data = os.path.join(t, "export")
        self.results = os.path.join(t, "results")
        self.out = os.path.join(self.results, "run")
        self.sel = os.path.join(t, "selection.json")
        write_selection(self.sel)
        self.marker = os.path.join(self.results, H.MARKER)

    def run_main(self, *flags, out=None, sel=None):
        argv = ["--export-dir", self.data, "--selection", sel or self.sel,
                "--out", out or self.out, "--results-root", self.results, *flags]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = H.main(argv)
        return code, buf.getvalue()

    def test_final_run_known_answers_and_one_use_lock(self):
        make_exports(self.data, C.HELDOUT_DAYS)          # SPY wins every day, others lose
        code, text = self.run_main("--final")
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.isfile(self.marker))
        for name in H.OUTPUTS:
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        verdict = {r["symbol"]: r for r in read_csv(os.path.join(self.out, "h2_verdict.csv"))}
        self.assertEqual(verdict["SPY"]["h2_rejected"], "True")
        self.assertEqual(verdict["SPY"]["days_net_positive"], "4")
        for s in ("QQQ", "IWM", "MSFT", "AAPL"):
            self.assertEqual(verdict[s]["h2_rejected"], "False", s)
            self.assertEqual(verdict[s]["days_net_positive"], "0", s)
        per_day = [r for r in read_csv(os.path.join(self.out, "h2_per_day.csv")) if r["symbol"] == "SPY"]
        self.assertEqual(len(per_day), 4)
        self.assertAlmostEqual(float(per_day[0]["net_mean_usd"]), 0.018)     # 0.02 - 2 x 0.001
        qqq = [r for r in read_csv(os.path.join(self.out, "h2_per_day.csv")) if r["symbol"] == "QQQ"]
        self.assertAlmostEqual(float(qqq[0]["net_mean_usd"]), -0.012)        # one tick + fees
        with open(os.path.join(self.out, "meta_sim.txt")) as f:
            meta = f.read()
        self.assertIn("mode: FINAL", meta)
        self.assertIn("selection_sha256:", meta)
        self.assertIn(str(C.HELDOUT_DAYS), meta)
        # second use is refused, and nothing new is written
        with self.assertRaises(SystemExit) as cm:
            self.run_main("--final", out=os.path.join(self.results, "run2"))
        self.assertIn("already run", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.results, "run2")))

    def test_needs_exactly_one_mode_flag(self):
        make_exports(self.data, C.HELDOUT_DAYS)
        with self.assertRaises(SystemExit):
            self.run_main()
        with self.assertRaises(SystemExit):
            self.run_main("--final", "--rehearsal")
        self.assertFalse(os.path.exists(self.marker))
        self.assertFalse(os.path.exists(self.out))

    def test_missing_export_does_not_use_up_the_run(self):
        make_exports(self.data, C.HELDOUT_DAYS)
        os.remove(os.path.join(self.data, C.HELDOUT_DAYS[3], "AAPL.csv"))
        code, text = self.run_main("--final")
        self.assertEqual(code, 2)
        self.assertIn("AAPL.csv", text)
        self.assertFalse(os.path.exists(self.marker))
        self.assertFalse(os.path.exists(self.out))

    def test_missing_or_bad_selection_does_not_use_up_the_run(self):
        make_exports(self.data, C.HELDOUT_DAYS)
        with self.assertRaises(SystemExit):
            self.run_main("--final", sel=os.path.join(self.tmp.name, "nope.json"))
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w") as f:
            json.dump({"symbols": [{"symbol": "SPY", "selected": None}]}, f)
        with self.assertRaises(SystemExit):
            self.run_main("--final", sel=bad)
        self.assertFalse(os.path.exists(self.marker))

    def test_existing_output_does_not_use_up_the_run(self):
        make_exports(self.data, C.HELDOUT_DAYS)
        os.makedirs(self.out)
        with open(os.path.join(self.out, "grid.csv"), "w") as f:
            f.write("x")
        code, text = self.run_main("--final")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.marker))

    def test_lock_is_claimed_before_computing(self):
        # If the computation dies, the single use is still spent (documented behaviour).
        make_exports(self.data, C.HELDOUT_DAYS)
        with mock.patch.object(R, "run_symbol", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_main("--final")
        self.assertTrue(os.path.isfile(self.marker))
        with self.assertRaises(SystemExit):
            self.run_main("--final", out=os.path.join(self.results, "again"))

    def test_final_reads_only_held_out_days(self):
        # Development exports are absent: a final run must not need them.
        make_exports(self.data, C.HELDOUT_DAYS)
        for d in C.DEV_DAYS:
            self.assertFalse(os.path.exists(os.path.join(self.data, d)))
        code, text = self.run_main("--final")
        self.assertEqual(code, 0, text)

    def test_rehearsal_uses_development_days_and_no_lock(self):
        make_exports(self.data, C.DEV_DAYS)              # no held-out exports exist
        code, text = self.run_main("--rehearsal")
        self.assertEqual(code, 0, text)
        self.assertFalse(os.path.exists(self.marker))
        with open(os.path.join(self.out, "h2_verdict.txt")) as f:
            self.assertIn("REHEARSAL", f.read())
        with open(os.path.join(self.out, "meta_sim.txt")) as f:
            self.assertIn("mode: REHEARSAL", f.read())
        rows = read_csv(os.path.join(self.out, "h2_per_day.csv"))
        self.assertEqual(sorted({r["day"] for r in rows}), sorted(C.DEV_DAYS))
        # a rehearsal can be repeated into a new folder, any number of times
        code, _ = self.run_main("--rehearsal", out=os.path.join(self.results, "run_b"))
        self.assertEqual(code, 0)

    def test_rehearsal_refuses_to_overwrite(self):
        make_exports(self.data, C.DEV_DAYS)
        self.assertEqual(self.run_main("--rehearsal")[0], 0)
        self.assertEqual(self.run_main("--rehearsal")[0], 2)


if __name__ == "__main__":
    unittest.main()
