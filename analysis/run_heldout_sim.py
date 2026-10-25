"""v2 held-out evaluation of H2 (plus a descriptive grid). The held-out days are used ONCE.

    python3 analysis/run_heldout_sim.py --export-dir data/export \
        --selection results/<dev run>/selection.json --out results/<run> --final

--final runs on config.HELDOUT_DAYS. It creates results/HELDOUT_SIM_USED before computing
anything and refuses if that file exists. Pre-checks that read no data (selection file,
export files present, no output file already there) run first, so a typo cannot burn the
single use.

--rehearsal runs the same code on config.DEV_DAYS with no lock. It proves the pipeline on
real data before the one-way step; its verdict is not a study result.

Frozen rule (docs/design.md, "v2 decisions", item 6): per symbol, only the variant selected
on development days is tested. H2 is rejected for that symbol only if its mean net P&L per
trade at the reference cell (latency 100 us, fee $0.001 per share) is positive on every
held-out day. A day with no trades is not positive. A symbol with no selected variant is
not rejected.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as C  # noqa: E402
import run_strategy_sim as R  # noqa: E402
import sim  # noqa: E402

MARKER = "HELDOUT_SIM_USED"
OUTPUTS = ("grid.csv", "pooled.csv", "baseline.csv", "h2_per_day.csv", "h2_verdict.csv",
           "h2_verdict.txt", "meta_sim.txt")


def load_selection(path):
    if not os.path.isfile(path):
        raise SystemExit(f"REFUSING: selection file not found: {path}")
    with open(path) as f:
        sel = json.load(f)
    symbols = [s["symbol"] for s in sel["symbols"]]
    if sorted(symbols) != sorted(C.SYMBOLS):
        raise SystemExit(f"REFUSING: selection symbols {symbols} do not match config {C.SYMBOLS}")
    return sel


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def claim(results_root, selection_path):
    """Create the one-use marker. Refuses if it exists. Written before any computation."""
    marker = os.path.join(results_root, MARKER)
    if os.path.exists(marker):
        raise SystemExit(f"REFUSING: held-out simulation was already run ({marker})")
    os.makedirs(results_root, exist_ok=True)
    with open(marker, "x") as f:
        f.write(f"held-out simulation used {datetime.datetime.now().isoformat(timespec='seconds')} "
                f"at commit {R.git('rev-parse', 'HEAD')}; selection {selection_path} "
                f"sha256 {sha256_of(selection_path)}\n")
    return marker


def verdict_rows(grid_rows, selection, n_days):
    """Apply the frozen H2 rule. Returns (summary rows, per-day rows)."""
    key = R.fee_key(C.REF_FEE_PER_SHARE)
    summary, per_day = [], []
    for s in selection["symbols"]:
        sym, sel = s["symbol"], s["selected"]
        if sel is None:
            summary.append({"symbol": sym, "threshold": "", "spread_limit_ticks": "",
                            "days": n_days, "days_net_positive": 0, "h2_rejected": False,
                            "note": "no variant had enough development trades: H2 not rejected"})
            continue
        thr, lim = sel["threshold"], str(sel["spread_limit_ticks"])
        rows = [r for r in grid_rows
                if r["symbol"] == sym and r["threshold"] == thr
                and str(r["spread_limit_ticks"]) == lim and r["latency_ns"] == C.REF_LATENCY_NS]
        if len(rows) != n_days:
            raise RuntimeError(f"{sym}: expected {n_days} per-day rows, found {len(rows)}")
        days_pos = 0
        for r in rows:
            positive = bool(r["trades"] > 0 and r[key] > 0)
            days_pos += positive
            per_day.append({"symbol": sym, "threshold": thr, "spread_limit_ticks": lim,
                            "day": r["day"], "trades": r["trades"], "net_mean_usd": r[key],
                            "positive": positive})
        rejected = days_pos == n_days
        summary.append({"symbol": sym, "threshold": thr, "spread_limit_ticks": lim,
                        "days": n_days, "days_net_positive": days_pos, "h2_rejected": rejected,
                        "note": ("H2 REJECTED: positive on every day" if rejected
                                 else "H2 not rejected")})
    return summary, per_day


def verdict_text(summary, per_day, days, rehearsal):
    lines = []
    if rehearsal:
        lines += ["REHEARSAL on development days. Nothing below is a study result.", ""]
    lines += [f"H2 on {'development (rehearsal)' if rehearsal else 'held-out'} days: "
              f"{', '.join(days)}",
              f"Cell: latency {C.REF_LATENCY_NS} ns, fee ${C.REF_FEE_PER_SHARE} per share, "
              f"1 share, hold {C.HOLD_NS // 1_000_000} ms. Rule: reject H2 for a symbol only if "
              f"the selected variant's mean net P&L per trade is positive on all {len(days)} days.", ""]
    for s in summary:
        lines.append(f"{s['symbol']}: " + ("no selected variant" if s["threshold"] == "" else
                     f"threshold {s['threshold']}, spread limit {s['spread_limit_ticks']}"))
        for d in [d for d in per_day if d["symbol"] == s["symbol"]]:
            net = d["net_mean_usd"]
            lines.append(f"   {d['day']}: {d['trades']:>7} trades, net {net:+.5f} USD per trade"
                         + ("  (positive)" if d["positive"] else ""))
        lines.append(f"   positive on {s['days_net_positive']} of {s['days']} days -> {s['note']}")
    n_rej = sum(1 for s in summary if s["h2_rejected"])
    chance = len(summary) / 2 ** len(days)
    lines += ["", f"H2 rejected for {n_rej} of {len(summary)} symbols. If days were a coin flip, "
              f"about {chance:.2f} symbols would pass by chance."]
    return "\n".join(lines) + "\n"


def write_meta(path, argv, started, ended, mode, days, selection_path):
    lines = [
        f"mode: {mode}",
        f"command: python3 analysis/run_heldout_sim.py {' '.join(argv)}",
        f"started_utc: {started.isoformat(timespec='seconds')}",
        f"ended_utc: {ended.isoformat(timespec='seconds')}",
        f"wall_seconds: {(ended - started).total_seconds():.1f}",
        f"machine_label: {os.environ.get('MACHINE_LABEL', 'host load not controlled')}",
        f"git_commit: {R.git('rev-parse', 'HEAD')}",
        f"git_dirty_files: {R.git('status', '--short') or 'none'}",
        f"selection_file: {selection_path}",
        f"selection_sha256: {sha256_of(selection_path)}",
        f"days: {days}",
        f"python: {sys.version.split()[0]}  numpy: {np.__version__}  pandas: {pd.__version__}",
        f"reference cell: latency {C.REF_LATENCY_NS} ns, fee {C.REF_FEE_PER_SHARE}, hold {C.HOLD_NS} ns",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export-dir", required=True)
    ap.add_argument("--selection", required=True, help="selection.json of the development run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--final", action="store_true", help="held-out days, used once")
    ap.add_argument("--rehearsal", action="store_true", help="development days, no lock")
    args = ap.parse_args(argv)
    argv_used = list(sys.argv[1:] if argv is None else argv)

    if args.final == args.rehearsal:
        raise SystemExit("REFUSING: give exactly one of --final (held-out days, used once) "
                         "or --rehearsal (development days, no lock)")
    days = C.DEV_DAYS if args.rehearsal else C.HELDOUT_DAYS

    # pre-checks: they read no data, so a mistake here cannot use up the single run
    selection = load_selection(args.selection)
    missing = [R.export_path(args.export_dir, d, s) for d in days for s in C.SYMBOLS
               if not os.path.isfile(R.export_path(args.export_dir, d, s))]
    if missing:
        print("missing export files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2
    present = [n for n in OUTPUTS if os.path.exists(os.path.join(args.out, n))]
    if present:
        print(f"refusing to overwrite {present} in {args.out}", file=sys.stderr)
        return 2

    if args.final:
        claim(args.results_root, args.selection)
    started = datetime.datetime.now(datetime.timezone.utc)
    os.makedirs(args.out, exist_ok=True)

    grid, pooled, baseline = [], [], []
    for symbol in C.SYMBOLS:
        loaded = {d: sim.Day(sim.load_day(R.export_path(args.export_dir, d, symbol))) for d in days}
        g, p, b = R.run_symbol(symbol, loaded, C.FEES_PER_SHARE)
        grid += g
        pooled += p
        baseline += b
        print(f"{symbol}: done", flush=True)

    summary, per_day = verdict_rows(grid, selection, len(days))
    R.write_csv(os.path.join(args.out, "grid.csv"), grid)
    R.write_csv(os.path.join(args.out, "pooled.csv"), pooled)
    R.write_csv(os.path.join(args.out, "baseline.csv"), baseline)
    R.write_csv(os.path.join(args.out, "h2_per_day.csv"), per_day)
    R.write_csv(os.path.join(args.out, "h2_verdict.csv"), summary)
    text = verdict_text(summary, per_day, days, args.rehearsal)
    with open(os.path.join(args.out, "h2_verdict.txt"), "w") as f:
        f.write(text)
    write_meta(os.path.join(args.out, "meta_sim.txt"), argv_used, started,
               datetime.datetime.now(datetime.timezone.utc),
               "REHEARSAL (development days, no lock)" if args.rehearsal else "FINAL (held-out days)",
               days, args.selection)
    print("\n" + text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
