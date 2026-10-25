"""Independent reference: rebuild one symbol's top of book from raw ITCH 5.0 bytes in
plain Python (standard library only), with the same row-per-op rules as lob_export,
and compare with an export file.

  python3 analysis/itch_ref.py <itch file> <SYMBOL> --compare <export.csv> [--max-rows N]

Shares no code with orderbook: its own message parsing, order tracking and price
levels. Rules mirrored from orderbook's ReplayBuilder: add = 1 op; execute/cancel =
reduce, or remove when nothing is left; delete = remove; replace = remove + add;
messages for an unknown order reference produce no op.
"""
import argparse
import sys

SIZES = {"R": 39, "A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19, "U": 35}


def be(b, o, n):
    return int.from_bytes(b[o:o + n], "big")


def messages(f):
    while True:
        hdr = f.read(2)
        if len(hdr) < 2:
            return
        n = be(hdr, 0, 2)
        body = f.read(n)
        if len(body) < n:
            return
        yield body


class RefBook:
    def __init__(self):
        self.orders = {}             # ref -> [side, price, shares]
        self.levels = {"B": {}, "S": {}}

    def _level_add(self, side, px, q):
        lv = self.levels[side]
        lv[px] = lv.get(px, 0) + q
        if lv[px] == 0:
            del lv[px]

    def add(self, ref, side, shares, px):
        if ref in self.orders:       # same ref seen again: the earlier one is replaced
            old = self.orders[ref]
            self._level_add(old[0], old[1], -old[2])
        self.orders[ref] = [side, px, shares]
        if shares > 0:
            self._level_add(side, px, shares)
        return True

    def shrink(self, ref, by):
        o = self.orders.get(ref)
        if o is None:
            return False
        if by >= o[2]:
            return self.remove(ref)
        o[2] -= by
        self._level_add(o[0], o[1], -by)
        return True

    def remove(self, ref):
        o = self.orders.pop(ref, None)
        if o is None:
            return False
        self._level_add(o[0], o[1], -o[2])
        return True

    def top(self):
        b, s = self.levels["B"], self.levels["S"]
        bp = max(b) if b else 0
        ap = min(s) if s else 0
        return bp, (b[bp] if b else 0), ap, (s[ap] if s else 0)


def reference_rows(path, symbol, max_rows=None):
    """Yields (seq, ts, bid_px, bid_qty, ask_px, ask_qty), one per op."""
    want = symbol.encode().ljust(8)
    locate = None
    book = RefBook()
    seq = 0
    with open(path, "rb") as f:
        for m in messages(f):
            t = chr(m[0])
            if t not in SIZES or len(m) < SIZES[t]:
                continue
            loc = be(m, 1, 2)
            if t == "R":
                if m[11:19] == want:
                    locate = loc
                continue
            if loc != locate:
                continue
            ts = be(m, 5, 6)
            ops = 0
            if t in "AF":
                ops += book.add(be(m, 11, 8), chr(m[19]) if chr(m[19]) == "B" else "S", be(m, 20, 4), be(m, 32, 4))
            elif t in "EC" or t == "X":
                ops += book.shrink(be(m, 11, 8), be(m, 19, 4))
            elif t == "D":
                ops += book.remove(be(m, 11, 8))
            elif t == "U":
                old = book.orders.get(be(m, 11, 8))
                if old is not None:
                    side = old[0]
                    book.remove(be(m, 11, 8))
                    seq_rows = [book.top()]
                    book.add(be(m, 19, 8), side, be(m, 27, 4), be(m, 31, 4))
                    seq_rows.append(book.top())
                    for top in seq_rows:
                        yield (seq, ts, *top)
                        seq += 1
                        if max_rows is not None and seq >= max_rows:
                            return
                continue
            if ops:
                yield (seq, ts, *book.top())
                seq += 1
                if max_rows is not None and seq >= max_rows:
                    return


def compare(itch_path, symbol, export_path, max_rows=None):
    """Returns (rows compared, first mismatch or None)."""
    n = 0
    with open(export_path) as f:
        header = f.readline().strip()
        if header != "seq,ts_ns,bid_px,bid_qty,ask_px,ask_qty":
            return 0, f"bad header: {header}"
        for ref in reference_rows(itch_path, symbol, max_rows):
            line = f.readline()
            if not line:
                return n, f"export ended early at row {n}; reference has {ref}"
            got = tuple(int(x) for x in line.strip().split(","))
            if got != ref:
                return n, f"row {n}: export {got} vs reference {ref}"
            n += 1
        if max_rows is None and f.readline():
            return n, f"export has more rows than the reference ({n})"
    return n, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("itch")
    ap.add_argument("symbol")
    ap.add_argument("--compare", required=True)
    ap.add_argument("--max-rows", type=int)
    a = ap.parse_args(argv)
    n, err = compare(a.itch, a.symbol, a.compare, a.max_rows)
    if err:
        print(f"MISMATCH after {n} matching rows: {err}")
        return 1
    print(f"OK: {n} rows match ({a.symbol})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
