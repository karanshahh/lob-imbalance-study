"""Diagnostic (development days only): describes the PSX spread and how much of the
imbalance-vs-change relation comes from a few large mid jumps. It does not change the
frozen test; anything it leads to is logged as a trial in docs/progress.md.

  python3 analysis/diagnose.py --export-dir data/export --out results/<run>

Per symbol-day: spread in ticks (share at one tick, median, p90, p99), median mid ($).
Per horizon: Pearson and Spearman (rank) correlation, the share of the covariance that
comes from the 0.1% of rows with the largest |change|, p99.9 and max |change|, and the
share of |change| > 10 ticks.
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

import config as C
import study

TOP = 0.001   # top 0.1% of rows by |change|


def spread_stats(spread):
    s = spread[np.isfinite(spread)]
    if len(s) == 0:
        return {"spread_share_1": np.nan, "spread_median": np.nan, "spread_p90": np.nan, "spread_p99": np.nan}
    return {"spread_share_1": float(np.mean(s == 1)), "spread_median": float(np.median(s)),
            "spread_p90": float(np.quantile(s, 0.90)), "spread_p99": float(np.quantile(s, 0.99))}


def tail_stats(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    out = {"n": int(len(x)), "pearson": np.nan, "spearman": np.nan, "top_cov_share": np.nan,
           "abs_p999": np.nan, "abs_max": np.nan, "share_gt10": np.nan}
    if len(x) < 2:
        return out
    a = np.abs(y)
    out["abs_p999"] = float(np.quantile(a, 0.999))
    out["abs_max"] = float(a.max())
    out["share_gt10"] = float(np.mean(a > 10))
    if np.std(x) > 0 and np.std(y) > 0:
        out["pearson"] = float(np.corrcoef(x, y)[0, 1])
        rx = pd.Series(x).rank().to_numpy()
        ry = pd.Series(y).rank().to_numpy()
        out["spearman"] = float(np.corrcoef(rx, ry)[0, 1])
        prod = (x - x.mean()) * (y - y.mean())
        k = max(1, math.ceil(TOP * len(x)))
        top = np.argsort(-a, kind="stable")[:k]
        out["top_cov_share"] = float(prod[top].sum() / prod.sum()) if prod.sum() != 0 else np.nan
    return out


def day_diag(df):
    df = study.collapse_same_timestamp(df)
    ts = df["ts_ns"].to_numpy()
    mid, imb = study.mid_and_imbalance(df)
    sess = study.in_session(ts)
    spread = np.where(np.isfinite(mid), (df["ask_px"].to_numpy() - df["bid_px"].to_numpy()) / C.TICK, np.nan)
    spread = np.where(sess, spread, np.nan)
    info = spread_stats(spread)
    info["mid_median_usd"] = float(np.nanmedian(np.where(sess, mid, np.nan)) / 100)
    rows = []
    for kind, h in study.horizons():
        d = study.forward_change_events(mid, ts, h) if kind == "ev" else study.forward_change_time(mid, ts, h)
        rows.append({"horizon": study.horizon_name(kind, h), **tail_stats(np.where(sess, imb, np.nan), d)})
    return info, rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    spreads, per = [], []
    for day in C.DEV_DAYS:            # development days only, by design
        for sym in C.SYMBOLS:
            path = os.path.join(a.export_dir, day, f"{sym}.csv")
            if not os.path.exists(path):
                raise SystemExit(f"missing export: {path}")
            info, rows = day_diag(study.load_export(path))
            spreads.append({"day": day, "symbol": sym, **info})
            per += [{"day": day, "symbol": sym, **r} for r in rows]
            print(f"{day} {sym}: median spread {info['spread_median']:.0f} ticks, "
                  f"one tick {info['spread_share_1']:.1%}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    spreads, per = pd.DataFrame(spreads), pd.DataFrame(per)
    spreads.to_csv(os.path.join(a.out, "diag_spread_dev.csv"), index=False)
    per.to_csv(os.path.join(a.out, "diag_tails_per_day_dev.csv"), index=False)
    s1 = spreads.groupby("symbol", sort=False)[["mid_median_usd", "spread_share_1", "spread_median",
                                                "spread_p90", "spread_p99"]].mean()
    s2 = per.groupby(["symbol", "horizon"], sort=False).agg(
        pearson=("pearson", "mean"), spearman=("spearman", "mean"),
        spearman_pos_days=("spearman", lambda v: int((v > 0).sum())),
        top_cov_share=("top_cov_share", "mean"), abs_p999=("abs_p999", "mean"),
        abs_max=("abs_max", "max"), share_gt10=("share_gt10", "mean"))
    with open(os.path.join(a.out, "diag_summary_dev.txt"), "w") as f:
        f.write(f"diagnostic, development days only: {', '.join(C.DEV_DAYS)}\n")
        f.write("spread in ticks ($0.01), in session, two-sided book; mean across days\n\n")
        f.write(s1.to_string(float_format=lambda v: f"{v:.3f}") + "\n\n")
        f.write("per horizon: mean across days (abs_max: max across days); top_cov_share = share of the\n"
                f"covariance from the top {TOP:.1%} of rows by |change|\n\n")
        f.write(s2.to_string(float_format=lambda v: f"{v:.4f}") + "\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
