"""Where does a trade's P&L go? Read-only diagnostic on the DEVELOPMENT days (trial 5).

For every taken trade, gross P&L splits exactly into

    gross = signed mid move - (entry spread + exit spread) / 2

with all terms in ticks, where the mid and spread are those of the rows the entry and exit
actually filled on, and the signed mid move is side x (exit mid - entry mid). The identity is
checked on every trade. It changes no rule: it only explains the numbers of trial 4.

    python3 analysis/diagnose_sim.py --export-dir data/export \
        --selection results/<dev run>/selection.json --out results --label vm-v2-diag

It opens development days only. Writes results/<label>-<timestamp>/decomposition.csv,
decomposition.txt and meta_diag.txt.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import config as C  # noqa: E402
import run_strategy_sim as R  # noqa: E402
import sim  # noqa: E402


def decompose(day, threshold, limit_ticks, latency_ns, hold_ns=None):
    """Per-trade decomposition arrays for one symbol-day, in ticks.

    Only trades whose entry and exit rows have both sides present are decomposable (the mid
    needs both). `n_trades` counts all trades, `n_usable` the decomposable ones.
    """
    r = sim.simulate(day, threshold, limit_ticks, latency_ns, hold_ns)
    empty = np.array([], dtype=np.float64)
    if r.n == 0:
        return {"n_trades": 0, "n_usable": 0, "entry_half": empty, "exit_half": empty,
                "signed_move": empty, "gross": empty, "identity_error": empty}
    e = np.searchsorted(day.ts, r.entry_ts + latency_ns, side="right") - 1
    x = np.searchsorted(day.ts, r.exit_ts, side="right") - 1
    both = day.bid_ok[e] & day.ask_ok[e] & day.bid_ok[x] & day.ask_ok[x]
    s_e = (day.ask_px[e] - day.bid_px[e]).astype(np.float64)
    s_x = (day.ask_px[x] - day.bid_px[x]).astype(np.float64)
    mid_e = (day.ask_px[e] + day.bid_px[e]) / 2.0
    mid_x = (day.ask_px[x] + day.bid_px[x]) / 2.0
    signed = r.side * (mid_x - mid_e)
    gross = r.gross_units.astype(np.float64)
    err = gross - (signed - (s_e + s_x) / 2.0)
    t = float(C.TICK)
    return {"n_trades": r.n, "n_usable": int(both.sum()),
            "entry_half": (s_e / 2.0 / t)[both], "exit_half": (s_x / 2.0 / t)[both],
            "signed_move": (signed / t)[both], "gross": (gross / t)[both],
            "identity_error": np.abs(err / t)[both]}


def pool(parts):
    """Concatenate per-day decompositions and take means."""
    def cat(k):
        return np.concatenate([p[k] for p in parts]) if parts else np.array([])
    n_usable = sum(p["n_usable"] for p in parts)
    out = {"trades": sum(p["n_trades"] for p in parts), "usable_trades": n_usable}
    for k in ("entry_half", "exit_half", "signed_move", "gross"):
        a = cat(k)
        out[k + "_ticks"] = float(a.mean()) if len(a) else float("nan")
    err = cat("identity_error")
    out["max_identity_error_ticks"] = float(err.max()) if len(err) else float("nan")
    return out


def load_selection(path):
    with open(path) as f:
        sel = json.load(f)
    return {s["symbol"]: s["selected"] for s in sel["symbols"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export-dir", default="data/export")
    ap.add_argument("--selection", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--label", required=True)
    args = ap.parse_args(argv)
    argv_used = list(sys.argv[1:] if argv is None else argv)

    selection = load_selection(args.selection)
    missing = [R.export_path(args.export_dir, d, s) for d in C.DEV_DAYS for s in C.SYMBOLS
               if not os.path.isfile(R.export_path(args.export_dir, d, s))]
    if missing:
        print("missing export files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 2
    started = datetime.datetime.now(datetime.timezone.utc)
    out_name = f"{args.label}-{started.strftime('%Y%m%d-%H%M%S')}"
    out_dir = os.path.join(args.out, out_name)
    if os.path.exists(out_dir):
        print(f"refusing to overwrite {out_dir}", file=sys.stderr)
        return 2

    rows = []
    for symbol in C.SYMBOLS:
        sel = selection.get(symbol)
        if sel is None:
            continue
        thr = sel["threshold"]
        lim = None if str(sel["spread_limit_ticks"]) == "any" else int(sel["spread_limit_ticks"])
        days = [sim.Day(sim.load_day(R.export_path(args.export_dir, d, symbol))) for d in C.DEV_DAYS]
        for lat in C.LATENCIES_NS:
            res = pool([decompose(d, thr, lim, lat) for d in days])
            rows.append({"symbol": symbol, "threshold": thr, "spread_limit_ticks": R.lim_name(lim),
                         "latency_ns": lat, **res})
        print(f"{symbol}: done", flush=True)

    os.makedirs(out_dir)
    R.write_csv(os.path.join(out_dir, "decomposition.csv"), rows)
    lines = ["Gross P&L per trade (ticks) = signed mid move - (entry spread + exit spread) / 2",
             "Selected variant per symbol, development days pooled. 1 tick = $0.01.", ""]
    hdr = f"{'symbol':<5} {'thr':>4} {'lim':>3} {'latency_ns':>10} {'trades':>8} {'usable':>8} " \
          f"{'entry_half':>10} {'exit_half':>10} {'signed_move':>11} {'gross':>8} {'max_err':>8}"
    lines.append(hdr)
    for r in rows:
        lines.append(f"{r['symbol']:<5} {r['threshold']:>4} {r['spread_limit_ticks']:>3} "
                     f"{r['latency_ns']:>10} {r['trades']:>8} {r['usable_trades']:>8} "
                     f"{r['entry_half_ticks']:>10.3f} {r['exit_half_ticks']:>10.3f} "
                     f"{r['signed_move_ticks']:>11.3f} {r['gross_ticks']:>8.3f} "
                     f"{r['max_identity_error_ticks']:>8.1e}")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "decomposition.txt"), "w") as f:
        f.write(text)
    ended = datetime.datetime.now(datetime.timezone.utc)
    with open(os.path.join(out_dir, "meta_diag.txt"), "w") as f:
        f.write("\n".join([
            f"run: {out_name}",
            f"command: python3 analysis/diagnose_sim.py {' '.join(argv_used)}",
            f"started_utc: {started.isoformat(timespec='seconds')}",
            f"wall_seconds: {(ended - started).total_seconds():.1f}",
            f"machine_label: {os.environ.get('MACHINE_LABEL', 'host load not controlled')}",
            f"git_commit: {R.git('rev-parse', 'HEAD')}",
            f"git_dirty_files: {R.git('status', '--short') or 'none'}",
            f"selection: {args.selection}",
            f"dev_days: {C.DEV_DAYS}",
            "read-only diagnostic: no rule or constant changed",
        ]) + "\n")
    print("\n" + text)
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
