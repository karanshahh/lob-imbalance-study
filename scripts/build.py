#!/usr/bin/env python3
"""scripts/build.py release|asan|tsan|python|all

Configures, builds and runs ctest for each build; "all" also runs the Python tests.
Python: $PYTHON, else .venv/bin/python, else python3 (needs numpy and pandas).
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


os.chdir(repo_root())
PY = project_python()


def one(name, build_type, sanitize):
    print(f"=== {name}", flush=True)
    run(["cmake", "-S", ".", "-B", f"build-{name}", "-G", "Ninja",
         f"-DCMAKE_BUILD_TYPE={build_type}", f"-DSANITIZE={sanitize}"])
    run(["cmake", "--build", f"build-{name}"])
    run(["ctest", "--test-dir", f"build-{name}", "--output-on-failure"])


def py_tests():
    print(f"=== python ({PY})", flush=True)
    run([PY, "-m", "unittest", "discover", "-s", "analysis"])


def main(argv):
    what = argv[0] if argv else ""
    if what == "release":
        one("release", "Release", "")
    elif what == "asan":
        one("asan", "Debug", "address,undefined")
    elif what == "tsan":
        one("tsan", "Debug", "thread")
    elif what == "python":
        py_tests()
    elif what == "all":
        one("asan", "Debug", "address,undefined")
        one("tsan", "Debug", "thread")
        one("release", "Release", "")
        py_tests()
    else:
        print("usage: scripts/build.py release|asan|tsan|python|all")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
