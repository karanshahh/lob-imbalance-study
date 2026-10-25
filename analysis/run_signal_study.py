"""v1 signal study: imbalance vs forward mid change, per symbol, day and horizon.

  python3 analysis/run_signal_study.py --export-dir data/export --set dev --out results/<run>

Held-out days are used once: --set heldout needs --final, and refuses if
results/HELDOUT_USED exists. It writes that file before computing anything.
"""
import argparse
import datetime as dt
import math
import os
import subprocess
import sys

import pandas as pd

import config as C
import study


def claim_heldout(results_root):
    marker = os.path.join(results_root, "HELDOUT_USED")
    if os.path.exists(marker):
        raise SystemExit(f"REFUSING: held-out days were already used ({marker})")
    os.makedirs(results_root, exist_ok=True)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = "unknown"
    with open(marker, "x") as f:
        f.write(f"held-out days used {dt.datetime.now().isoformat(timespec='seconds')} at commit {commit}\n")
    return marker


def summarize(per_day):
    """Across days: mean daily corr, its standard error, days with positive corr."""
    rows = []
    for (sym, hz), g in per_day.groupby(["symbol", "horizon"], sort=False):
        c = g["corr"].dropna()
        se = c.std(ddof=1) / math.sqrt(len(c)) if len(c) > 1 else float("nan")
        rows.append({"symbol": sym, "horizon": hz, "days": len(c), "mean_corr": c.mean(), "se": se,
                     "pos_days": int((c > 0).sum()), "mean_share_zero": g["share_zero"].mean(),
                     "mean_slope": g["slope"].mean(), "n_total": int(g["n"].sum())})
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--set", choices=["dev", "heldout"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--final", action="store_true", help="required for --set heldout")
    a = ap.parse_args(argv)

    if a.set == "heldout":
        if not a.final:
            raise SystemExit("REFUSING: held-out days need --final (they are used once)")
        claim_heldout(a.results_root)
    days = C.DEV_DAYS if a.set == "dev" else C.HELDOUT_DAYS

    per_day, data_rows = [], []
    for day in days:
        for sym in C.SYMBOLS:
            path = os.path.join(a.export_dir, day, f"{sym}.csv")
            if not os.path.exists(path):
                raise SystemExit(f"missing export: {path}")
            stats, info = study.day_stats(study.load_export(path))
            data_rows.append({"day": day, "symbol": sym, **info})
            for r in stats:
                per_day.append({"day": day, "symbol": sym, **r})
            print(f"{day} {sym}: {info['rows_raw']} updates, {info['two_sided_in_session']} two-sided in session",
                  flush=True)

    os.makedirs(a.out, exist_ok=True)
    per_day = pd.DataFrame(per_day)
    summary = summarize(per_day)
    pd.DataFrame(data_rows).to_csv(os.path.join(a.out, f"data_{a.set}.csv"), index=False)
    per_day.to_csv(os.path.join(a.out, f"signal_per_day_{a.set}.csv"), index=False)
    summary.to_csv(os.path.join(a.out, f"signal_summary_{a.set}.csv"), index=False)
    with open(os.path.join(a.out, f"signal_summary_{a.set}.txt"), "w") as f:
        f.write(f"set {a.set}; days {', '.join(days)}; symbols {', '.join(C.SYMBOLS)}\n")
        f.write("corr = correlation of imbalance with forward mid change (ticks), per day; "
                "mean and standard error across days\n\n")
        f.write(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        f.write("\n")
        if a.set == "heldout":
            passed = summary[summary["pos_days"] == len(days)]
            f.write(f"\nRule (frozen): H1 holds for a symbol and horizon if corr > 0 on all {len(days)} "
                    f"held-out days. Passed: {len(passed)} of {len(summary)}; about "
                    f"{len(summary) / 2 ** len(days):.1f} would pass by chance if there were no effect.\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
