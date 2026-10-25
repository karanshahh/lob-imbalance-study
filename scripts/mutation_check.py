#!/usr/bin/env python3
"""scripts/mutation_check.py [name filter]

Applies one exact-text mutation at a time to a temporary copy of the repo and reports
"caught" or "SURVIVED". Every mutation must be caught. Exit 1 if any survived, 2 if no
mutation matched the filter.
  C++ mutations: build the copy with ASan+UBSan and run ctest.
  Python mutations: run the Python tests, plus the end-to-end check with this repo's
  build-asan/lob_export.
Needs build-asan first (python3 scripts/build.py asan); its downloaded sources are reused.
MUTATION_KINDS=py runs only the Python mutations. Run from the repo root.
"""
import os
import subprocess
import sys


def repo_root():
    """The repo root: the current directory if it is one, else the parent of scripts/."""
    if os.path.isfile("CMakeLists.txt"):
        return os.getcwd()
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def project_python():
    """$PYTHON, else .venv/bin/python, else python3 (needs numpy and pandas)."""
    py = os.environ.get("PYTHON", "")
    if not py:
        py = ".venv/bin/python" if os.access(".venv/bin/python", os.X_OK) else "python3"
    return py


def run(cmd, **kw):
    """Run a command; stop with its exit status if it fails (like set -e)."""
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        sys.exit(r.returncode)
    return r


def out(cmd, default=""):
    """Stdout of a command, stripped; `default` if it cannot run or fails."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else default
    except OSError:
        return default

_script = os.path.abspath(__file__)
os.chdir(repo_root())
_py = project_python()
if os.environ.get("_MUTATION_CHECK_REEXEC") != "1" and _py != sys.executable:
    os.environ["_MUTATION_CHECK_REEXEC"] = "1"
    os.execvp(_py, [_py, _script, *sys.argv[1:]])
if not os.access("build-asan/lob_export", os.X_OK):
    print("run python3 scripts/build.py asan first")
    sys.exit(1)

import os, shutil, subprocess, sys, tempfile

ROOT = os.getcwd()
FILTER = sys.argv[1] if len(sys.argv) > 1 else ""
KINDS = os.environ.get("MUTATION_KINDS", "cpp,py").split(",")
TIMEOUT = "20"   # per test, so a hung test fails fast instead of waiting 300 s

M = [  # kind, file, name, old, new
 ("cpp", "include/lobstudy/export.hpp", "bid qty read from the ask side",
  "t.bid_qty = b.volume_at(ob::Side::Buy, *p).value;", "t.bid_qty = b.volume_at(ob::Side::Sell, *p).value;"),
 ("cpp", "include/lobstudy/export.hpp", "reduce treated as cancel",
  "case itch::ReplayOp::Kind::Reduce: b.modify(op.order.id, op.order.price, op.order.remaining); break;",
  "case itch::ReplayOp::Kind::Reduce: b.cancel(op.order.id); break;"),
 ("cpp", "include/lobstudy/export.hpp", "seq starts at 1",
  "put(static_cast<std::uint64_t>(i), ',');", "put(static_cast<std::uint64_t>(i + 1), ',');"),
 ("cpp", "include/lobstudy/export.hpp", "timestamp column dropped",
  "put(ops[i].ts, ',');", "put(std::uint64_t{0}, ',');"),
 ("cpp", "tools/lob_export.cpp", "messages fed only to the first symbol",
  "        for (auto& b : builders) {\n            b.count(r);\n            if (r) b.feed(*r);\n        }",
  "        builders.front().count(r);\n        if (r) builders.front().feed(*r);"),
 ("py", "analysis/study.py", "imbalance sign flipped", "(bq - aq) / (bq + aq)", "(aq - bq) / (bq + aq)"),
 ("py", "analysis/study.py", "event horizon off by one",
  "out[:-h] = mid[h:] - mid[:-h]", "out[:-h] = mid[h - 1:-1] - mid[:-h]"),
 ("py", "analysis/study.py", "time horizon takes the wrong row", 'side="right") - 1', 'side="left") - 1'),
 ("py", "analysis/study.py", "one-sided rows kept",
  "two_sided = (bq > 0) & (aq > 0)", "two_sided = (bq >= 0) & (aq >= 0)"),
 ("py", "analysis/study.py", "first row per timestamp kept", 'keep="last"', 'keep="first"'),
 ("py", "analysis/config.py", "session starts 09:30", "(9 * 3600 + 35 * 60)", "(9 * 3600 + 30 * 60)"),
 ("py", "analysis/run_signal_study.py", "held-out lock not checked",
  "    if os.path.exists(marker):\n        raise SystemExit", "    if False:\n        raise SystemExit"),
 ("py", "analysis/itch_ref.py", "reference ignores replace", '            elif t == "U":', '            elif t == "U-off":'),
 ("py", "analysis/itch_ref.py", "reference reads price at the wrong offset",
  "be(m, 20, 4), be(m, 32, 4))", "be(m, 20, 4), be(m, 28, 4))"),
 ("py", "analysis/diagnose.py", "spearman without ranks",
  "rx = pd.Series(x).rank().to_numpy()\n        ry = pd.Series(y).rank().to_numpy()",
  "rx = pd.Series(x).to_numpy()\n        ry = pd.Series(y).to_numpy()"),
 ("py", "analysis/diagnose.py", "one-tick share counts wider spreads",
  "np.mean(s == 1)", "np.mean(s >= 1)"),
 ("py", "analysis/diagnose.py", "tail share takes the smallest changes",
  "np.argsort(-a, kind=\"stable\")", "np.argsort(a, kind=\"stable\")"),
 ("py", "analysis/study.py", "study spearman without ranks",
  "rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()",
  "rx, ry = pd.Series(x).to_numpy(), pd.Series(y).to_numpy()"),
 ("py", 'analysis/sim.py', 'v2 sim: one-position rule uses <= instead of <',
  'if cl[i] < next_free:', 'if cl[i] <= next_free:'),
 ("py", 'analysis/sim.py', 'v2 sim: one-position rule removed',
  'if cl[i] < next_free:', 'if False:'),
 ("py", 'analysis/sim.py', 'v2 sim: threshold uses > instead of >=',
  'np.abs(self.imb) >= threshold', 'np.abs(self.imb) > threshold'),
 ("py", 'analysis/sim.py', 'v2 sim: spread limit uses < instead of <=',
  'self.spread <= limit_ticks * C.TICK', 'self.spread < limit_ticks * C.TICK'),
 ("py", 'analysis/sim.py', 'v2 sim: session start ignored',
  '(self.ts >= C.SESSION_START_NS) & ', ''),
 ("py", 'analysis/sim.py', 'v2 sim: exit time forgets the second latency',
  'tf = t + hold + 2 * latency_ns', 'tf = t + hold + latency_ns'),
 ("py", 'analysis/sim.py', 'v2 sim: entry ignores latency',
  'e = np.searchsorted(self.ts, t + latency_ns, side="right") - 1', 'e = np.searchsorted(self.ts, t, side="right") - 1'),
 ("py", 'analysis/sim.py', 'v2 sim: close check removed',
  'exit_ok = in_range & (exit_ts < C.CLOSE_NS)', 'exit_ok = in_range'),
 ("py", 'analysis/sim.py', 'v2 sim: fee on one leg only',
  '- 2.0 * fee_per_share', '- 1.0 * fee_per_share'),
 ("py", 'analysis/sim.py', 'v2 sim: short entry uses the ask',
  'short = self._leg(e, r, tf, self.bid_ok, self.bid_px, self.next_ask, self.ask_px, -1)', 'short = self._leg(e, r, tf, self.ask_ok, self.ask_px, self.next_ask, self.ask_px, -1)'),
 ("py", 'analysis/sim.py', 'v2 sim: short sign not flipped',
  'gross = sign * (exit_px_arr[xc] - entry_px_arr[e])', 'gross = (exit_px_arr[xc] - entry_px_arr[e])'),
 ("py", 'analysis/sim.py', 'v2 sim: exit fallback to a later row off',
  'xi = exit_next[r]', 'xi = np.where(exit_px_arr[r] > 0, r, self.n)'),
 ("py", 'analysis/sim.py', 'v2 sim: collapse keeps the first row per timestamp',
  'keep="last"', 'keep="first"'),
 ("py", 'analysis/sim.py', 'v2 sim: imbalance sign flipped',
  'diff = (self.bid_qty - self.ask_qty)', 'diff = (self.ask_qty - self.bid_qty)'),
 ("py", 'analysis/sim.py', 'v2 sim: crossed books allowed',
  '(self.spread > 0)', '(self.spread > -10**9)'),
 ("py", 'analysis/sim.py', 'v2 sim: random baseline ignores the fee',
  'net = gross / UNITS_PER_DOLLAR - 2.0 * fee', 'net = gross / UNITS_PER_DOLLAR'),
 ("py", 'analysis/sim.py', 'v2 sim: sharpe uses ddof 0',
  'x.std(ddof=1)', 'x.std(ddof=0)'),
 ("py", 'analysis/sim.py', 'v2 sim: timestamp order check removed',
  'if self.n > 1 and not np.all(np.diff(self.ts) > 0):', 'if False:'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection picks the lowest net',
  'if best is None or r[key] > best[key]:', 'if best is None or r[key] < best[key]:'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection ignores the minimum trade count',
  'r["trades"] >= C.MIN_TRADES_SELECT and r[key] == r[key]', 'r[key] == r[key]'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection minimum is strict',
  'r["trades"] >= C.MIN_TRADES_SELECT', 'r["trades"] > C.MIN_TRADES_SELECT'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection accepts nan',
  ' and r[key] == r[key]', ''),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection uses the wrong latency',
  'r["symbol"] == symbol and r["latency_ns"] == C.REF_LATENCY_NS]', 'r["symbol"] == symbol and r["latency_ns"] == 0]'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection uses the wrong fee',
  '    key = fee_key(C.REF_FEE_PER_SHARE)\n    cell =', '    key = fee_key(0.0)\n    cell ='),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: selection ignores the symbol',
  'if r["symbol"] == symbol and r["latency_ns"] == C.REF_LATENCY_NS]', 'if r["latency_ns"] == C.REF_LATENCY_NS]'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: shares per day counts one leg',
  '2 * n / len(results)', '1 * n / len(results)'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: trades per day divides by days with trades',
  '"trades_per_day": n / len(results) if results else 0.0', '"trades_per_day": n / max(1, sum(1 for r in results if r.n > 0)) if results else 0.0'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: hit rate counts zero as a win',
  'float((net > 0).mean())', 'float((net >= 0).mean())'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: positive days counted backwards',
  'if m > 0)', 'if m < 0)'),
 ("py", 'analysis/run_strategy_sim.py', 'v2 run: gross mean in units not ticks',
  'float(gross.mean() / C.TICK) if n', 'float(gross.mean()) if n'),
 ("py", 'analysis/config.py', 'v2 config: hold changed to 200 ms',
  'HOLD_NS = 100_000_000', 'HOLD_NS = 200_000_000'),
 ("py", 'analysis/config.py', 'v2 config: reference fee changed',
  'REF_FEE_PER_SHARE = 0.001', 'REF_FEE_PER_SHARE = 0.003'),
 ("py", 'analysis/config.py', 'v2 config: minimum trades changed',
  'MIN_TRADES_SELECT = 100 ', 'MIN_TRADES_SELECT = 10  '),
 ("py", 'analysis/config.py', 'v2 config: reference latency changed',
  'REF_LATENCY_NS = 100_000 ', 'REF_LATENCY_NS = 10_000  '),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: rejects with one negative day',
  'rejected = days_pos == n_days', 'rejected = days_pos >= n_days - 1'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: zero net counts as positive',
  'bool(r["trades"] > 0 and r[key] > 0)', 'bool(r["trades"] > 0 and r[key] >= 0)'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: no-trade day counts as positive',
  'bool(r["trades"] > 0 and r[key] > 0)', 'bool(r["trades"] == 0 or r[key] > 0)'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: lock not checked',
  '    if os.path.exists(marker):\n        raise SystemExit(f"REFUSING: held-out simulation was already run', '    if False:\n        raise SystemExit(f"REFUSING: held-out simulation was already run'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: lock never claimed',
  '        claim(args.results_root, args.selection)', '        pass'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: mode flags not checked',
  'if args.final == args.rehearsal:', 'if False:'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: rehearsal reads held-out days',
  'days = C.DEV_DAYS if args.rehearsal else C.HELDOUT_DAYS', 'days = C.HELDOUT_DAYS'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: final reads development days',
  'days = C.DEV_DAYS if args.rehearsal else C.HELDOUT_DAYS', 'days = C.DEV_DAYS'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: verdict uses the wrong latency',
  'and str(r["spread_limit_ticks"]) == lim and r["latency_ns"] == C.REF_LATENCY_NS]', 'and str(r["spread_limit_ticks"]) == lim and r["latency_ns"] == 0]'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: verdict uses the wrong fee',
  'key = R.fee_key(C.REF_FEE_PER_SHARE)\n    summary, per_day = [], []', 'key = R.fee_key(0.0)\n    summary, per_day = [], []'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: verdict ignores the spread limit',
  'and str(r["spread_limit_ticks"]) == lim and r["latency_ns"]', 'and r["latency_ns"]'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: existing outputs not checked',
  '    if present:', '    if False:'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: missing exports not checked before the claim',
  '    if missing:', '    if False:'),
 ("py", 'analysis/run_heldout_sim.py', 'v2 heldout: selection symbols not validated',
  'if sorted(symbols) != sorted(C.SYMBOLS):', 'if False:'),
 ("py", 'analysis/diagnose_sim.py', 'v2 diag: exit row taken as the entry row',
  'x = np.searchsorted(day.ts, r.exit_ts, side="right") - 1', 'x = e'),
 ("py", 'analysis/diagnose_sim.py', 'v2 diag: half spread not halved',
  '"entry_half": (s_e / 2.0 / t)[both]', '"entry_half": (s_e / t)[both]'),
 ("py", 'analysis/diagnose_sim.py', 'v2 diag: mid move ignores the side',
  'signed = r.side * (mid_x - mid_e)', 'signed = (mid_x - mid_e)'),
 ("py", 'analysis/diagnose_sim.py', 'v2 diag: entry ignores latency',
  'e = np.searchsorted(day.ts, r.entry_ts + latency_ns, side="right") - 1', 'e = np.searchsorted(day.ts, r.entry_ts, side="right") - 1'),
 ("py", 'analysis/diagnose_sim.py', 'v2 diag: unusable trades kept',
  'both = day.bid_ok[e] & day.ask_ok[e] & day.bid_ok[x] & day.ask_ok[x]', 'both = np.ones(len(e), dtype=bool)'),
]

def copy_repo(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("build*", "data", ".venv", ".git", "results", "__pycache__"))

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode

failed = 0
ran = 0
for kind, path, name, old, new in M:
    if kind not in KINDS or (FILTER and FILTER not in name):
        continue
    ran += 1
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "repo")
        copy_repo(d)
        f = os.path.join(d, path)
        text = open(f).read()
        if text.count(old) != 1:
            print(f"BAD PATTERN ({text.count(old)} matches): {name}")
            failed += 1
            continue
        open(f, "w").write(text.replace(old, new))
        if kind == "cpp":
            deps = os.path.join(ROOT, "build-asan", "_deps")
            cfg = ["cmake", "-S", ".", "-B", "b", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Debug",
                   "-DSANITIZE=address,undefined", f"-DLOBSTUDY_TEST_TIMEOUT={TIMEOUT}",
                   f"-DFETCHCONTENT_SOURCE_DIR_ORDERBOOK={deps}/orderbook-src",
                   f"-DFETCHCONTENT_SOURCE_DIR_GOOGLETEST={deps}/googletest-src"]
            if run(cfg, d) or run(["cmake", "--build", "b"], d):
                print(f"caught (does not build): {name}")
                continue
            bad = run(["ctest", "--test-dir", "b", "--timeout", TIMEOUT], d)
        else:
            exe = os.path.join(ROOT, "build-asan", "lob_export")
            bad = run([sys.executable, "-m", "unittest", "discover", "-s", "analysis"], d) or \
                  run([sys.executable, "analysis/e2e_check.py", exe], d)
        if bad:
            print(f"caught: {name}")
        else:
            print(f"SURVIVED: {name}")
            failed += 1
if ran == 0:
    print("No mutation matched; nothing was run.")
    sys.exit(2)
print("all mutations caught" if failed == 0 else f"{failed} mutation(s) survived or had a bad pattern")
sys.exit(1 if failed else 0)
