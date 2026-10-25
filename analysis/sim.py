"""Strategy simulation for lob-imbalance-study v2.

Rules are in docs/design.md ("Strategy simulation (v2)" and "v2 decisions").

Prices are ITCH units (1/10,000 dollar); one tick is config.TICK units ($0.01).
A trade is 1 share, aggressive on both legs, one position at a time:

  signal row t   : |I| >= threshold, spread <= limit, inside the session
  entry          : at t + L, buy at the best ask (I > 0) or sell at the best bid (I < 0),
                   using the last row with timestamp <= t + L
  exit           : sent at t + L + hold, fills at t + hold + 2L at the opposite best price,
                   using the last row with timestamp <= that time
  empty side     : entry skipped; exit uses the first later row that has the side;
                   no such row before 16:00 -> trade dropped (all counted)
"""
import os
import sys
from bisect import bisect_left

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config as C  # noqa: E402

COLUMNS = ["seq", "ts_ns", "bid_px", "bid_qty", "ask_px", "ask_qty"]
UNITS_PER_DOLLAR = 10_000

OK, ENTRY_EMPTY, EXIT_UNAVAILABLE = 0, 1, 2


def collapse(df):
    """One row per timestamp: the last op's state (same rule as the v1 study)."""
    df = df.sort_values("seq", kind="stable")
    return df[~df["ts_ns"].duplicated(keep="last")].reset_index(drop=True)


def load_day(path):
    df = pd.read_csv(path, dtype=np.int64)
    if list(df.columns) != COLUMNS:
        raise ValueError(f"{path}: unexpected columns {list(df.columns)}")
    return collapse(df)


def _next_true(ok):
    """For each index k, the smallest j >= k with ok[j], or len(ok) if none."""
    n = len(ok)
    idx = np.where(ok, np.arange(n), n)
    return np.minimum.accumulate(idx[::-1])[::-1]


class Day:
    """One symbol-day, collapsed to one row per timestamp, with derived arrays."""

    def __init__(self, df):
        self.ts = df["ts_ns"].to_numpy(dtype=np.int64)
        self.bid_px = df["bid_px"].to_numpy(dtype=np.int64)
        self.bid_qty = df["bid_qty"].to_numpy(dtype=np.int64)
        self.ask_px = df["ask_px"].to_numpy(dtype=np.int64)
        self.ask_qty = df["ask_qty"].to_numpy(dtype=np.int64)
        self.n = len(self.ts)
        if self.n > 1 and not np.all(np.diff(self.ts) > 0):
            raise ValueError("timestamps are not strictly increasing after the collapse")
        self.bid_ok = (self.bid_qty > 0) & (self.bid_px > 0)
        self.ask_ok = (self.ask_qty > 0) & (self.ask_px > 0)
        self.spread = self.ask_px - self.bid_px
        # a usable signal row has both sides and a positive spread
        self.valid = self.bid_ok & self.ask_ok & (self.spread > 0)
        total = (self.bid_qty + self.ask_qty).astype(np.float64)
        diff = (self.bid_qty - self.ask_qty).astype(np.float64)
        self.imb = np.full(self.n, np.nan)
        np.divide(diff, total, out=self.imb, where=self.valid)
        self.in_session = (self.ts >= C.SESSION_START_NS) & (self.ts <= C.SESSION_END_NS)
        self.next_bid = _next_true(self.bid_ok)
        self.next_ask = _next_true(self.ask_ok)

    def candidates(self, threshold, limit_ticks):
        """Row indices where the rule fires (before position and fill constraints)."""
        mask = self.in_session & self.valid & (np.abs(self.imb) >= threshold)
        if limit_ticks is not None:
            mask &= self.spread <= limit_ticks * C.TICK
        return np.flatnonzero(mask)

    def _leg(self, e, r, tf, entry_ok_arr, entry_px_arr, exit_next, exit_px_arr, sign):
        """Both legs of one direction for every candidate. sign = +1 long, -1 short."""
        xi = exit_next[r]
        in_range = xi < self.n
        xc = np.minimum(xi, self.n - 1)
        exit_ts = np.maximum(tf, self.ts[xc])
        exit_ok = in_range & (exit_ts < C.CLOSE_NS)
        entry_ok = entry_ok_arr[e]
        gross = sign * (exit_px_arr[xc] - entry_px_arr[e])
        code = np.where(~entry_ok, ENTRY_EMPTY, np.where(~exit_ok, EXIT_UNAVAILABLE, OK))
        return gross, exit_ts, code

    def plan(self, cand, latency_ns, hold_ns=None):
        """Fill and exit for every candidate row, ignoring the one-position rule."""
        hold = C.HOLD_NS if hold_ns is None else hold_ns
        t = self.ts[cand]
        e = np.searchsorted(self.ts, t + latency_ns, side="right") - 1
        tf = t + hold + 2 * latency_ns
        r = np.searchsorted(self.ts, tf, side="right") - 1
        long_ = self._leg(e, r, tf, self.ask_ok, self.ask_px, self.next_bid, self.bid_px, +1)
        short = self._leg(e, r, tf, self.bid_ok, self.bid_px, self.next_ask, self.ask_px, -1)
        side = np.where(self.imb[cand] > 0, 1, -1)
        return Plan(t, side, long_, short)


class Plan:
    def __init__(self, ts, side, long_, short):
        self.ts = ts
        self.side = side
        self.long_gross, self.long_exit_ts, self.long_code = long_
        self.short_gross, self.short_exit_ts, self.short_code = short

    def strategy_view(self):
        is_long = self.side == 1
        gross = np.where(is_long, self.long_gross, self.short_gross)
        exit_ts = np.where(is_long, self.long_exit_ts, self.short_exit_ts)
        code = np.where(is_long, self.long_code, self.short_code)
        return gross, exit_ts, code


def select_trades(ts, code, exit_ts):
    """Walk candidates in time order, one position at a time.

    A candidate is ignored while a position is open (its signal time is before the exit
    fill). A candidate that cannot be filled does not open a position.
    """
    cl = ts.tolist()
    cd = code.tolist()
    xt = exit_ts.tolist()
    n = len(cl)
    taken = []
    entry_empty = exit_unavailable = 0
    next_free = -1
    i = 0
    while i < n:
        if cl[i] < next_free:
            i = bisect_left(cl, next_free, i + 1)
            continue
        c = cd[i]
        if c == OK:
            taken.append(i)
            next_free = xt[i]
        elif c == ENTRY_EMPTY:
            entry_empty += 1
        else:
            exit_unavailable += 1
        i += 1
    return np.array(taken, dtype=np.int64), entry_empty, exit_unavailable


class Result:
    def __init__(self, plan, taken, entry_empty, exit_unavailable, n_candidates):
        gross, exit_ts, _ = plan.strategy_view()
        self.taken = taken
        self.entry_ts = plan.ts[taken]
        self.side = plan.side[taken]
        self.gross_units = gross[taken]
        self.exit_ts = exit_ts[taken]
        self.n_candidates = n_candidates
        self.entry_empty = entry_empty
        self.exit_unavailable = exit_unavailable
        self.n = len(taken)
        # for the random-direction baseline: both directions at the same entry rows
        self.long_gross = plan.long_gross[taken]
        self.long_ok = plan.long_code[taken] == OK
        self.short_gross = plan.short_gross[taken]
        self.short_ok = plan.short_code[taken] == OK


def simulate(day, threshold, limit_ticks, latency_ns, hold_ns=None):
    cand = day.candidates(threshold, limit_ticks)
    plan = day.plan(cand, latency_ns, hold_ns)
    gross, exit_ts, code = plan.strategy_view()
    taken, ee, eu = select_trades(plan.ts, code, exit_ts)
    return Result(plan, taken, ee, eu, len(cand))


def net_dollars(gross_units, fee_per_share):
    """Net P&L per share in dollars. The fee is paid on both legs."""
    return np.asarray(gross_units, dtype=np.float64) / UNITS_PER_DOLLAR - 2.0 * fee_per_share


def sharpe_stats(x):
    """Per-trade Sharpe (mean / sample std) and its iid standard error.

    se = sqrt((1 + 0.5 * sr^2) / n), the usual large-sample approximation for iid
    returns. Trades are not independent, so this understates the uncertainty.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    if sd == 0.0:
        return n, mean, float("nan"), float("nan")
    sr = mean / sd
    se = float(np.sqrt((1.0 + 0.5 * sr * sr) / n))
    return n, mean, sr, se


def random_direction_means(long_gross, long_ok, short_gross, short_ok, fee, reps, seed):
    """Net mean P&L per share for `reps` random-direction runs at the same entry rows.

    Each repetition gives every entry a random direction. A trade whose random direction
    cannot be filled is dropped. The one-position rule is not re-applied (stated in the
    README). Returns an array of length `reps` (nan if every trade was dropped).
    Repetitions are drawn in chunks to bound memory; the result depends only on the
    inputs and the seed.
    """
    rng = np.random.default_rng(seed)
    k = len(long_gross)
    out = np.full(reps, np.nan)
    if k == 0:
        return out
    chunk = max(1, 4_000_000 // k)
    done = 0
    while done < reps:
        m = min(chunk, reps - done)
        pick_long = rng.integers(0, 2, size=(m, k)).astype(bool)
        gross = np.where(pick_long, long_gross[None, :], short_gross[None, :])
        ok = np.where(pick_long, long_ok[None, :], short_ok[None, :])
        net = gross / UNITS_PER_DOLLAR - 2.0 * fee
        cnt = ok.sum(axis=1)
        tot = np.where(ok, net, 0.0).sum(axis=1)
        good = cnt > 0
        seg = np.full(m, np.nan)
        seg[good] = tot[good] / cnt[good]
        out[done:done + m] = seg
        done += m
    return out
