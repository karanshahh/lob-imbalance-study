#!/usr/bin/env python3
"""scripts/run_bench.py <label> [day]

Times lob_export (parse + export of all symbols) on one day, 3 runs, Release build.
Writes results/<label>-<timestamp>.txt. Env: ITCH_DIR, MACHINE_LABEL, PIN (CPU list for taskset).
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
import tempfile

os.chdir(repo_root())


def main(argv):
    if not argv:
        print("usage: scripts/run_bench.py <label> [day]", file=sys.stderr)
        return 1
    label = argv[0]
    day = argv[1] if len(argv) > 1 else "20190130"
    itch_dir = os.environ.get("ITCH_DIR") or os.path.expanduser("~/itch/psx-study")
    exe = "build-release/lob_export"
    if not os.access(exe, os.X_OK):
        print("build first: python3 scripts/build.py release")
        return 1
    with open("build-release/CMakeCache.txt") as f:
        if "CMAKE_BUILD_TYPE:STRING=Release" not in f.read().splitlines():
            print("build-release is not Release")
            return 1
    sys.path.insert(0, "analysis")
    import config
    syms = " ".join(config.SYMBOLS)
    path = f"results/{label}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    tmp = tempfile.mkdtemp()
    pin = os.environ.get("PIN", "")
    pincmd = ["taskset", "-c", pin] if pin else []
    os.makedirs("results", exist_ok=True)
    u = os.uname()
    ncpu = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    itch_file = f"{itch_dir}/{day}.PSX_ITCH_50"
    with open(path, "w") as f:
        def line(s):
            print(s, flush=True)
            f.write(s + "\n")
            f.flush()
        line(f"label    {label}")
        line(f"machine  {os.environ.get('MACHINE_LABEL') or 'host load not controlled'}")
        line(f"date     {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        line(f"kernel   {u.sysname} {u.release} {u.machine}; cpus {ncpu}; pin {pin or 'none'}")
        line(f"commit   {out(['git', 'rev-parse', 'HEAD'], 'none')}")
        line(f"command  {' '.join(pincmd)} {exe} {itch_file} <tmp> {syms}")
        for r in (1, 2, 3):
            line(f"--- run {r}")
            p = subprocess.Popen([*pincmd, exe, itch_file, tmp, *syms.split()],
                                 stdout=subprocess.PIPE, text=True, errors="replace")
            for chunk in p.stdout:
                print(chunk, end="", flush=True)
                f.write(chunk)
                f.flush()
            if p.wait():
                return p.returncode
    print(f"raw output in {path} (exports written to {tmp}, safe to delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
