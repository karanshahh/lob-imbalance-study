#!/usr/bin/env python3
"""scripts/run_study.py <label>

Exports the development days for every symbol with the Release build, then runs the
v1 signal study. Writes results/<label>-<timestamp>/ (machine info, export logs, outputs).
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

os.chdir(repo_root())


def cache_value(key):
    with open("build-release/CMakeCache.txt") as f:
        for l in f.read().splitlines():
            if l.startswith(key + ":"):
                return l.split("=", 1)[1] if "=" in l else ""
    return ""


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
    if not argv:
        print("usage: scripts/run_study.py <label>", file=sys.stderr)
        return 1
    label = argv[0]
    itch_dir = os.environ.get("ITCH_DIR") or os.path.expanduser("~/itch/psx-study")
    exe = "build-release/lob_export"
    py = project_python()
    if not os.access(exe, os.X_OK):
        print("build first: python3 scripts/build.py release")
        return 1
    with open("build-release/CMakeCache.txt") as f:
        lines = f.read().splitlines()
    if "CMAKE_BUILD_TYPE:STRING=Release" not in lines:
        print("build-release is not Release")
        return 1
    if "SANITIZE:STRING=" not in lines:
        print("build-release has sanitizers on")
        return 1

    env = dict(os.environ, PYTHONPATH="analysis")
    syms = subprocess.run([py, "-c", 'import config; print(" ".join(config.SYMBOLS))'],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()
    days = subprocess.run([py, "-c", 'import config; print(" ".join(config.DEV_DAYS))'],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()
    for d in days.split():
        if not os.path.isfile(f"{itch_dir}/{d}.PSX_ITCH_50"):
            print(f"missing {itch_dir}/{d}.PSX_ITCH_50 (gunzip first)")
            return 1

    dirty = len(out(["git", "status", "--short"]).splitlines())   # before the results folder exists
    now = datetime.datetime.now()
    outdir = f"results/{label}-{now.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(outdir)
    u = os.uname()
    ncpu = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    compiler = cache_value("CMAKE_CXX_COMPILER")
    version = out([compiler, "-dumpfullversion"], "")
    pyver = out([py, "-c", 'import sys, numpy, pandas; print(sys.version.split()[0], "numpy", numpy.__version__, "pandas", pandas.__version__)'], "")
    info = [
        f"label        {label}",
        f"machine      {os.environ.get('MACHINE_LABEL') or 'host load not controlled'}",
        f"date (UTC)   {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"kernel       {u.sysname} {u.release} {u.machine}",
        f"cpus         {ncpu}",
        f"compiler     {compiler} {version}",
        f"flags        Release: {cache_value('CMAKE_CXX_FLAGS_RELEASE')}",
        f"commit       {out(['git', 'rev-parse', 'HEAD'], 'none')} ({dirty} uncommitted changes)",
        "orderbook    v2.1.0 (FetchContent)",
        f"python       {pyver}",
        f"itch dir     {itch_dir}",
        f"days         {days}",
        f"symbols      {syms}",
    ]
    lscpu = out(["lscpu"])
    for l in lscpu.splitlines():
        if "Model name" in l or "Architecture" in l or l.startswith("CPU(s)"):
            info.append(l)
    text = "\n".join(info) + "\n"
    with open(f"{outdir}/machine.txt", "w") as f:
        f.write(text)
    print(text, end="", flush=True)

    for d in days.split():
        print(f"--- export {d}", flush=True)
        log = f"{outdir}/export_{d}.txt"
        with open(log, "w") as f:
            f.write(f"command: {exe} {itch_dir}/{d}.PSX_ITCH_50 data/export/{d} {syms}\n")
        tee_append([exe, f"{itch_dir}/{d}.PSX_ITCH_50", f"data/export/{d}", *syms.split()], log)
    run([py, "analysis/run_signal_study.py", "--export-dir", "data/export", "--set", "dev",
         "--out", outdir, "--results-root", "results"])
    print(f"results in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
