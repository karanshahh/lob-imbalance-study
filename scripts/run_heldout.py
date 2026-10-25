#!/usr/bin/env python3
"""scripts/run_heldout.py <label> <selection.json of the development run>

THE ONE-WAY STEP. Exports the held-out days, then runs, once each:
  1. H2 (strategy simulation) with analysis/run_heldout_sim.py --final
  2. H1 (signal study) with analysis/run_signal_study.py --set heldout --final
Each has its own lock file (results/HELDOUT_SIM_USED, results/HELDOUT_USED), created
before anything is computed. Everything that can be checked without reading held-out
data is checked first: committed code and selection, release build, input files, locks.
Env: ITCH_DIR (default ~/itch/psx-study), MACHINE_LABEL (host condition), PYTHON.
Run from the repo root.
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

import datetime
import hashlib

os.chdir(repo_root())


def refuse(msg):
    print(f"REFUSING: {msg}", file=sys.stderr)
    sys.exit(1)


def tee_append(cmd, path):
    with open(path, "a") as f:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, errors="replace")
        for chunk in p.stdout:
            print(chunk, end="", flush=True)
            f.write(chunk)
        rc = p.wait()
    if rc:
        sys.exit(rc)


def main(argv):
    if len(argv) < 2:
        print("usage: scripts/run_heldout.py <label> <selection.json of the development run>", file=sys.stderr)
        return 1
    label, selection = argv[0], argv[1]
    itch_dir = os.environ.get("ITCH_DIR") or os.path.expanduser("~/itch/psx-study")
    exe = "build-release/lob_export"
    py = project_python()

    if not os.access(exe, os.X_OK):
        refuse("build first: python3 scripts/build.py release")
    with open("build-release/CMakeCache.txt") as f:
        lines = f.read().splitlines()
    if "CMAKE_BUILD_TYPE:STRING=Release" not in lines:
        refuse("build-release is not Release")
    if "SANITIZE:STRING=" not in lines:
        refuse("build-release has sanitizers on")
    if not os.path.isfile(selection):
        refuse(f"selection file not found: {selection}")
    if subprocess.run(["git", "ls-files", "--error-unmatch", selection],
                      capture_output=True).returncode != 0:
        refuse(f"{selection} is not committed")
    status = out(["git", "status", "--short"])
    if status:
        print(status, file=sys.stderr)
        refuse("uncommitted changes (commit first)")
    for m in ("results/HELDOUT_USED", "results/HELDOUT_SIM_USED"):
        if os.path.exists(m):
            refuse(f"{m} exists: the held-out days were already used")

    env = dict(os.environ, PYTHONPATH="analysis")
    syms = subprocess.run([py, "-c", 'import config; print(" ".join(config.SYMBOLS))'],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()
    days = subprocess.run([py, "-c", 'import config; print(" ".join(config.HELDOUT_DAYS))'],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()
    for d in days.split():
        if not os.path.isfile(f"{itch_dir}/{d}.PSX_ITCH_50"):
            refuse(f"missing {itch_dir}/{d}.PSX_ITCH_50 (gunzip first)")

    with open(selection, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    commit = out(["git", "rev-parse", "HEAD"])
    print(f"Held-out days : {days}")
    print(f"Symbols       : {syms}")
    print(f"Selection     : {selection} (committed; sha256 {sha})")
    print(f"Commit        : {commit}")
    print()
    print("This uses the held-out days ONCE (H2 and H1). It cannot be repeated.")
    try:
        answer = input("Type USE-HELDOUT to continue: ")
    except EOFError:
        answer = ""
    if answer != "USE-HELDOUT":
        print("not confirmed; nothing was run")
        return 1

    outdir = f"results/{label}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(outdir)
    u = os.uname()
    ncpu = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    pyver = out([py, "-c", 'import sys, numpy, pandas; print(sys.version.split()[0], "numpy", numpy.__version__, "pandas", pandas.__version__)'], "")
    with open(f"{outdir}/machine.txt", "w") as f:
        f.write("\n".join([
            f"label        {label}",
            f"machine      {os.environ.get('MACHINE_LABEL') or 'host load not controlled'}",
            f"date (UTC)   {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"kernel       {u.sysname} {u.release} {u.machine}",
            f"cpus         {ncpu}",
            f"commit       {commit} (clean tree)",
            f"selection    {selection}",
            f"python       {pyver}",
            f"itch dir     {itch_dir}",
            f"days         {days}",
            f"symbols      {syms}",
        ]) + "\n")

    for d in days.split():
        print(f"--- export {d}", flush=True)
        log = f"{outdir}/export_{d}.txt"
        with open(log, "w") as f:
            f.write(f"command: {exe} {itch_dir}/{d}.PSX_ITCH_50 data/export/{d} {syms}\n")
        tee_append([exe, f"{itch_dir}/{d}.PSX_ITCH_50", f"data/export/{d}", *syms.split()], log)

    print("--- H2: strategy simulation (held-out, final)", flush=True)
    run([py, "analysis/run_heldout_sim.py", "--export-dir", "data/export", "--selection", selection,
         "--out", outdir, "--results-root", "results", "--final"])
    print("--- H1: signal study (held-out, final)", flush=True)
    run([py, "analysis/run_signal_study.py", "--export-dir", "data/export", "--set", "heldout", "--final",
         "--out", outdir, "--results-root", "results"])

    print()
    print(f"results in {outdir}")
    print("locks: results/HELDOUT_SIM_USED results/HELDOUT_USED (commit them with the results)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
