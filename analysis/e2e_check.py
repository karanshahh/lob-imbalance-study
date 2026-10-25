"""End-to-end check run by ctest: write a small synthetic ITCH file, run lob_export on
it, and require the export to match the independent Python reference row for row.

  python3 analysis/e2e_check.py <path to lob_export>
"""
import os
import subprocess
import sys
import tempfile

import itch_ref


def msg(t, locate, ts, payload=b""):
    body = t.encode() + locate.to_bytes(2, "big") + b"\x00\x00" + ts.to_bytes(6, "big") + payload
    return len(body).to_bytes(2, "big") + body


def sym(s):
    return s.encode().ljust(8)


def R(loc, ts, s):  # stock directory: stock at 11, padded to 39 bytes
    return msg("R", loc, ts, sym(s) + b"\x00" * 20)


def A(loc, ts, ref, side, shares, s, px):
    return msg("A", loc, ts, ref.to_bytes(8, "big") + side.encode() + shares.to_bytes(4, "big") + sym(s) + px.to_bytes(4, "big"))


def F(loc, ts, ref, side, shares, s, px):
    return A(loc, ts, ref, side, shares, s, px)[:2].replace(b"\x00\x24", b"\x00\x28") + b"F" + \
        A(loc, ts, ref, side, shares, s, px)[3:] + b"MPID"


def E(loc, ts, ref, shares):
    return msg("E", loc, ts, ref.to_bytes(8, "big") + shares.to_bytes(4, "big") + b"\x00" * 8)


def X(loc, ts, ref, shares):
    return msg("X", loc, ts, ref.to_bytes(8, "big") + shares.to_bytes(4, "big"))


def D(loc, ts, ref):
    return msg("D", loc, ts, ref.to_bytes(8, "big"))


def U(loc, ts, old, new, shares, px):
    return msg("U", loc, ts, old.to_bytes(8, "big") + new.to_bytes(8, "big") + shares.to_bytes(4, "big") + px.to_bytes(4, "big"))


def synthetic():
    T = 34_500_000_000_000  # 09:35
    out = [msg("S", 0, 1, b"O"),                       # system event: ignored type
           R(5, 2, "TEST"), R(6, 3, "OTHR"),
           A(5, T + 1, 1, "B", 100, "TEST", 10000),
           A(5, T + 2, 2, "B", 50, "TEST", 10000),
           A(6, T + 3, 3, "B", 999, "OTHR", 50000),    # other symbol: must not appear
           A(5, T + 4, 4, "S", 200, "TEST", 10100),
           F(5, T + 5, 5, "S", 30, "TEST", 10200),
           E(5, T + 6, 4, 50),                         # partial execution of the best ask
           X(5, T + 7, 1, 100),                        # cancel all of order 1 -> removed
           D(5, T + 8, 999),                           # unknown ref: no op
           U(5, T + 9, 2, 6, 80, 10050),               # replace: two ops at one timestamp
           E(5, T + 10, 4, 150),                       # executes the rest of the best ask
           D(5, T + 11, 6),
           A(5, T + 12, 7, "B", 10, "TEST", 9900)]
    return b"".join(out)


def main(argv):
    exe = argv[1]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "synthetic.itch")
        with open(path, "wb") as f:
            f.write(synthetic())
        r = subprocess.run([exe, path, d, "TEST", "OTHR"], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            return 1
        n, err = itch_ref.compare(path, "TEST", os.path.join(d, "TEST.csv"))
        if err or n != 11:
            print(f"TEST: {n} rows, {err or 'expected 11 rows'}")
            return 1
        n2, err2 = itch_ref.compare(path, "OTHR", os.path.join(d, "OTHR.csv"))
        if err2 or n2 != 1:
            print(f"OTHR: {n2} rows, {err2 or 'expected 1 row'}")
            return 1
    print("e2e OK: export matches the Python reference (11 + 1 rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
