"""End-to-end test of analysis/run_strategy_sim.py on a tiny synthetic export."""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import run_strategy_sim as R  # noqa: E402

MS = 1_000_000
BASE = C.SESSION_START_NS + 1_000_000_000


def write_constant_book(path):
    """101 rows, 10 ms apart. Bid 10000 (qty 90), ask 10100 (qty 10): I = 0.8, spread 1 tick.
    Every trade buys 10100 and sells 10000, so it loses exactly one tick."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("seq,ts_ns,bid_px,bid_qty,ask_px,ask_qty\n")
        for k in range(101):
            f.write(f"{k},{BASE + 10 * k * MS},10000,90,10100,10\n")


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


class EndToEnd(unittest.TestCase):
    def run_main(self, data, out, label="t"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = R.main(["--data", data, "--out", out, "--label", label])
        return code, buf.getvalue()

    def test_constant_book_known_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, out = os.path.join(tmp, "export"), os.path.join(tmp, "results")
            for d in C.DEV_DAYS:
                for s in C.SYMBOLS:
                    write_constant_book(os.path.join(data, d, f"{s}.csv"))
            code, text = self.run_main(data, out)
            self.assertEqual(code, 0, text)
            runs = os.listdir(out)
            self.assertEqual(len(runs), 1)
            folder = os.path.join(out, runs[0])
            for name in ("grid.csv", "pooled.csv", "baseline.csv", "selection.json", "meta.txt"):
                self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)

            n_var = len(C.THRESHOLDS) * len(C.SPREAD_LIMITS_TICKS)
            grid = read_csv(os.path.join(folder, "grid.csv"))
            pooled = read_csv(os.path.join(folder, "pooled.csv"))
            self.assertEqual(len(grid), len(C.SYMBOLS) * len(C.DEV_DAYS) * n_var * len(C.LATENCIES_NS))
            self.assertEqual(len(pooled), len(C.SYMBOLS) * n_var * len(C.LATENCIES_NS))

            # Latency 0: 11 trades per day (entries at 0, 100, ..., 1000 ms), 5 days = 55.
            row = [r for r in pooled if r["symbol"] == "SPY" and r["threshold"] == "0.2"
                   and r["spread_limit_ticks"] == "1" and r["latency_ns"] == "0"][0]
            self.assertEqual(int(row["trades"]), 55)
            self.assertAlmostEqual(float(row["gross_mean_ticks"]), -1.0)
            self.assertAlmostEqual(float(row["net_mean_usd_fee0.0"]), -0.01)
            self.assertAlmostEqual(float(row["net_mean_usd_fee0.001"]), -0.012)
            self.assertAlmostEqual(float(row["net_mean_usd_fee0.003"]), -0.016)
            self.assertEqual(int(row["days_net_positive_fee0.0"]), 0)
            self.assertAlmostEqual(float(row["hit_rate_fee0.0"]), 0.0)
            self.assertAlmostEqual(float(row["shares_per_day"]), 22.0)

            # The random baseline loses the same spread in this book.
            base = [b for b in read_csv(os.path.join(folder, "baseline.csv"))
                    if b["symbol"] == "SPY" and b["threshold"] == "0.2"
                    and b["spread_limit_ticks"] == "1" and b["fee"] == "0.001"][0]
            self.assertAlmostEqual(float(base["random_mean_usd"]), -0.012)
            self.assertAlmostEqual(float(base["random_p05_usd"]), -0.012)

            # Fewer than MIN_TRADES_SELECT trades at the reference cell: nobody is eligible.
            with open(os.path.join(folder, "selection.json")) as f:
                sel = json.load(f)
            self.assertEqual(len(sel["symbols"]), len(C.SYMBOLS))
            for s in sel["symbols"]:
                self.assertIsNone(s["selected"])
                self.assertEqual(s["variants_total"], n_var)

            with open(os.path.join(folder, "meta.txt")) as f:
                meta = f.read()
            self.assertIn("git_commit:", meta)
            self.assertIn("machine_label:", meta)

    def test_missing_export_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, out = os.path.join(tmp, "export"), os.path.join(tmp, "results")
            for d in C.DEV_DAYS:
                for s in C.SYMBOLS:
                    write_constant_book(os.path.join(data, d, f"{s}.csv"))
            os.remove(os.path.join(data, C.DEV_DAYS[2], "MSFT.csv"))
            code, text = self.run_main(data, out)
            self.assertEqual(code, 2)
            self.assertIn("MSFT.csv", text)
            self.assertFalse(os.path.exists(out))

    def test_runner_never_references_held_out_days(self):
        # The development runner must not be able to open held-out days at all.
        self.assertTrue(set(C.DEV_DAYS).isdisjoint(C.HELDOUT_DAYS))
        with open(R.__file__) as f:
            self.assertNotIn("HELDOUT_DAYS", f.read())


if __name__ == "__main__":
    unittest.main()
