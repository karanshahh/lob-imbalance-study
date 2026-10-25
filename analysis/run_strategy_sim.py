"""v2 strategy simulation on the DEVELOPMENT days only (trial 4).

Runs the frozen grid (12 variants x 4 latencies x 3 fees x 5 symbols x 5 days), the
random-direction baseline, and the variant selection. It cannot read held-out days: it
only ever opens config.DEV_DAYS. The held-out evaluation is a separate program.

    python3 analysis/run_strategy_sim.py --data data/export --out results --label vm-v2-dev

Writes results/<label>-<timestamp>/ with grid.csv, pooled.csv, baseline.csv,
selection.json and meta.txt. Refuses to write into an existing folder.
"""
import argparse
import csv
import datetime
import json
import os
import platform
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as C  # noqa: E402
import sim  # noqa: E402


def variants():
    return [(thr, lim) for thr in C.THRESHOLDS for lim in C.SPREAD_LIMITS_TICKS]


def lim_name(lim):
    return "any" if lim is None else str(lim)


def fee_key(fee):
    return f"net_mean_usd_fee{fee}"


def export_path(data_dir, day, symbol):
    return os.path.join(data_dir, day, f"{symbol}.csv")


def pooled_stats(results, fees):
    """Pool trades across days for one (symbol, variant, latency)."""
    gross = np.concatenate([r.gross_units for r in results]) if results else np.array([])
    n = len(gross)
    row = {
        "trades": n,
        "days_with_trades": sum(1 for r in results if r.n > 0),
        "trades_per_day": n / len(results) if results else 0.0,
        "shares_per_day": 2 * n / len(results) if results else 0.0,   # 1 share, 2 legs
        "candidates": sum(r.n_candidates for r in results),
        "entry_empty": sum(r.entry_empty for r in results),
        "exit_unavailable": sum(r.exit_unavailable for r in results),
        "gross_mean_ticks": float(gross.mean() / C.TICK) if n else float("nan"),
    }
    for fee in fees:
        net = sim.net_dollars(gross, fee)
        _, mean, sr, se = sim.sharpe_stats(net)
        day_means = [float(sim.net_dollars(r.gross_units, fee).mean()) if r.n else float("nan")
                     for r in results]
        row[fee_key(fee)] = mean
        row[f"hit_rate_fee{fee}"] = float((net > 0).mean()) if n else float("nan")
        row[f"sharpe_per_trade_fee{fee}"] = sr
        row[f"sharpe_se_fee{fee}"] = se
        row[f"days_net_positive_fee{fee}"] = sum(1 for m in day_means if m > 0)
    return row


def run_symbol(symbol, days, fees):
    """days: {day: sim.Day}. Returns (grid_rows, pooled_rows, baseline_rows)."""
    grid, pooled, baseline = [], [], []
    for vi, (thr, lim) in enumerate(variants()):
        for lat in C.LATENCIES_NS:
            results = []
            for day_name, d in days.items():
                r = sim.simulate(d, thr, lim, lat)
                results.append(r)
                row = {"symbol": symbol, "day": day_name, "threshold": thr,
                       "spread_limit_ticks": lim_name(lim), "latency_ns": lat,
                       "candidates": r.n_candidates, "trades": r.n,
                       "entry_empty": r.entry_empty, "exit_unavailable": r.exit_unavailable,
                       "gross_mean_ticks": float(r.gross_units.mean() / C.TICK) if r.n else float("nan")}
                for fee in fees:
                    row[fee_key(fee)] = (float(sim.net_dollars(r.gross_units, fee).mean())
                                         if r.n else float("nan"))
                grid.append(row)
            prow = {"symbol": symbol, "threshold": thr, "spread_limit_ticks": lim_name(lim),
                    "latency_ns": lat}
            prow.update(pooled_stats(results, fees))
            pooled.append(prow)
            if lat == C.REF_LATENCY_NS:
                lg = np.concatenate([r.long_gross for r in results])
                lo = np.concatenate([r.long_ok for r in results])
                sg = np.concatenate([r.short_gross for r in results])
                so = np.concatenate([r.short_ok for r in results])
                seed = C.RANDOM_SEED + 1000 * C.SYMBOLS.index(symbol) + vi
                for fee in fees:
                    m = sim.random_direction_means(lg, lo, sg, so, fee, C.RANDOM_REPS, seed)
                    m = m[~np.isnan(m)]
                    baseline.append({
                        "symbol": symbol, "threshold": thr, "spread_limit_ticks": lim_name(lim),
                        "latency_ns": lat, "fee": fee, "reps": C.RANDOM_REPS,
                        "reps_with_trades": len(m), "entry_rows": len(lg),
                        "random_mean_usd": float(m.mean()) if len(m) else float("nan"),
                        "random_p05_usd": float(np.percentile(m, 5)) if len(m) else float("nan"),
                        "random_p95_usd": float(np.percentile(m, 95)) if len(m) else float("nan"),
                    })
    return grid, pooled, baseline


def select_variant(pooled_rows, symbol):
    """Best development mean net P&L per trade at the reference cell, with enough trades."""
    key = fee_key(C.REF_FEE_PER_SHARE)
    cell = [r for r in pooled_rows if r["symbol"] == symbol and r["latency_ns"] == C.REF_LATENCY_NS]
    eligible = [r for r in cell if r["trades"] >= C.MIN_TRADES_SELECT and r[key] == r[key]]
    best = None
    for r in eligible:                       # first maximum wins (grid order)
        if best is None or r[key] > best[key]:
            best = r
    return {
        "symbol": symbol,
        "selected": None if best is None else {
            "threshold": best["threshold"],
            "spread_limit_ticks": best["spread_limit_ticks"],
            "dev_trades": best["trades"],
            "dev_net_mean_usd_at_ref": best[key],
        },
        "eligible_variants": len(eligible),
        "variants_total": len(cell),
    }


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unavailable"


def write_meta(path, argv, started, ended, out_name):
    lines = [
        f"run: {out_name}",
        f"command: python3 analysis/run_strategy_sim.py {' '.join(argv)}",
        f"started_utc: {started.isoformat(timespec='seconds')}",
        f"ended_utc: {ended.isoformat(timespec='seconds')}",
        f"wall_seconds: {(ended - started).total_seconds():.1f}",
        f"machine_label: {os.environ.get('MACHINE_LABEL', 'host load not controlled')}",
        f"git_commit: {git('rev-parse', 'HEAD')}",
        f"git_dirty_files: {git('status', '--short') or 'none'}",
        f"python: {platform.python_version()}  numpy: {np.__version__}  pandas: {pd.__version__}",
        f"platform: {platform.platform()}  machine: {platform.machine()}  cpus: {os.cpu_count()}",
        "config:",
        f"  symbols: {C.SYMBOLS}",
        f"  dev_days: {C.DEV_DAYS}",
        f"  thresholds: {C.THRESHOLDS}  spread_limits_ticks: {C.SPREAD_LIMITS_TICKS}",
        f"  latencies_ns: {C.LATENCIES_NS}  fees_per_share: {C.FEES_PER_SHARE}",
        f"  hold_ns: {C.HOLD_NS}  ref_latency_ns: {C.REF_LATENCY_NS}  ref_fee: {C.REF_FEE_PER_SHARE}",
        f"  min_trades_select: {C.MIN_TRADES_SELECT}  random_reps: {C.RANDOM_REPS}  seed: {C.RANDOM_SEED}",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default="data/export", help="folder with <day>/<SYMBOL>.csv")
    ap.add_argument("--out", default="results")
    ap.add_argument("--label", required=True, help="e.g. vm-v2-dev")
    args = ap.parse_args(argv)
    argv_used = list(sys.argv[1:] if argv is None else argv)

    missing = [export_path(args.data, d, s) for d in C.DEV_DAYS for s in C.SYMBOLS
               if not os.path.isfile(export_path(args.data, d, s))]
    if missing:
        print("missing export files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2

    started = datetime.datetime.now(datetime.timezone.utc)
    out_name = f"{args.label}-{started.strftime('%Y%m%d-%H%M%S')}"
    out_dir = os.path.join(args.out, out_name)
    if os.path.exists(out_dir):
        print(f"refusing to overwrite {out_dir}", file=sys.stderr)
        return 2

    fees = C.FEES_PER_SHARE
    grid, pooled, baseline, selection = [], [], [], []
    for symbol in C.SYMBOLS:
        t0 = time.time()
        days = {d: sim.Day(sim.load_day(export_path(args.data, d, symbol))) for d in C.DEV_DAYS}
        g, p, b = run_symbol(symbol, days, fees)
        grid += g
        pooled += p
        baseline += b
        selection.append(select_variant(pooled, symbol))
        print(f"{symbol}: {sum(d.n for d in days.values())} rows, {time.time() - t0:.1f} s", flush=True)

    os.makedirs(out_dir)
    write_csv(os.path.join(out_dir, "grid.csv"), grid)
    write_csv(os.path.join(out_dir, "pooled.csv"), pooled)
    write_csv(os.path.join(out_dir, "baseline.csv"), baseline)
    with open(os.path.join(out_dir, "selection.json"), "w") as f:
        json.dump({"rule": "best development mean net USD per trade at the reference cell, "
                           f"latency {C.REF_LATENCY_NS} ns, fee {C.REF_FEE_PER_SHARE}, "
                           f"at least {C.MIN_TRADES_SELECT} trades",
                   "symbols": selection}, f, indent=2)
    write_meta(os.path.join(out_dir, "meta.txt"), argv_used, started,
               datetime.datetime.now(datetime.timezone.utc), out_name)

    key = fee_key(C.REF_FEE_PER_SHARE)
    print(f"\nReference cell: latency {C.REF_LATENCY_NS} ns, fee ${C.REF_FEE_PER_SHARE}/share "
          f"(net mean USD per trade, development days pooled)")
    for s in selection:
        sym = s["symbol"]
        sel = s["selected"]
        print(f"\n{sym}: selected = " + ("none eligible (H2 stands)" if sel is None else
              f"threshold {sel['threshold']}, spread limit {sel['spread_limit_ticks']}, "
              f"{sel['dev_trades']} trades, net {sel['dev_net_mean_usd_at_ref']:.5f}"))
        for r in pooled:
            if r["symbol"] == sym and r["latency_ns"] == C.REF_LATENCY_NS:
                print(f"   thr {r['threshold']} lim {r['spread_limit_ticks']:>3}: "
                      f"trades {r['trades']:>8}  gross {r['gross_mean_ticks']:+.3f} ticks  "
                      f"net {r[key]:+.5f}")
    print(f"\nwrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
