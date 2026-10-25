"""Signal computations for the imbalance study. Pure functions on arrays and frames.

Rows come from lob_export (one row per book op). Several ops can share one ITCH
timestamp (an Order Replace is a cancel then an add, both at the same nanosecond),
and the book between them is not a state anyone could observe. So the first step
keeps only the last row per timestamp: one row = one observable book update.
"""
import numpy as np
import pandas as pd

import config as C

COLUMNS = ["seq", "ts_ns", "bid_px", "bid_qty", "ask_px", "ask_qty"]


def load_export(path):
    df = pd.read_csv(path, dtype="int64")
    if list(df.columns) != COLUMNS:
        raise ValueError(f"{path}: unexpected columns {list(df.columns)}")
    return df


def collapse_same_timestamp(df):
    """Keep the book state after the last op at each timestamp."""
    return df.drop_duplicates("ts_ns", keep="last").reset_index(drop=True)


def mid_and_imbalance(df):
    """Mid in ticks ($0.01) and imbalance I = (bid_qty - ask_qty) / (bid_qty + ask_qty).
    Both are NaN when either side of the book is empty."""
    bq = df["bid_qty"].to_numpy(dtype=float)
    aq = df["ask_qty"].to_numpy(dtype=float)
    two_sided = (bq > 0) & (aq > 0)
    mid = np.where(two_sided, (df["bid_px"].to_numpy() + df["ask_px"].to_numpy()) / 2 / C.TICK, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        imb = np.where(two_sided, (bq - aq) / (bq + aq), np.nan)
    return mid, imb


def forward_change_events(mid, ts, h):
    """mid[i + h] - mid[i]; NaN past the end or when the later row is after the close."""
    out = np.full(len(mid), np.nan)
    if h < len(mid):
        out[:-h] = mid[h:] - mid[:-h]
        late = np.zeros(len(mid), dtype=bool)
        late[:-h] = ts[h:] > C.CLOSE_NS
        out[late] = np.nan
    return out


def forward_change_time(mid, ts, tau):
    """Mid at the last row with ts <= t + tau, minus mid at t. NaN when t + tau is past
    the close or past the last row of the day (no state known there)."""
    target = ts + tau
    j = np.searchsorted(ts, target, side="right") - 1
    out = mid[j] - mid
    out[(target > C.CLOSE_NS) | (target > ts[-1])] = np.nan
    return out


def in_session(ts):
    return (ts >= C.SESSION_START_NS) & (ts <= C.SESSION_END_NS)


def signal_stats(signal, change):
    """Statistics of `change` against `signal` over rows where both are finite."""
    ok = np.isfinite(signal) & np.isfinite(change)
    x, y = signal[ok], change[ok]
    res = {"n": int(ok.sum()), "share_zero": np.nan, "corr": np.nan, "slope": np.nan}
    if res["n"] == 0:
        return res, [np.nan] * (len(C.BUCKET_EDGES) - 1)
    res["share_zero"] = float(np.mean(y == 0))
    if res["n"] > 1 and np.std(x) > 0 and np.std(y) > 0:
        res["corr"] = float(np.corrcoef(x, y)[0, 1])
        res["slope"] = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
    b = np.clip(np.digitize(x, C.BUCKET_EDGES[1:-1]), 0, len(C.BUCKET_EDGES) - 2)
    buckets = [float(y[b == k].mean()) if np.any(b == k) else np.nan for k in range(len(C.BUCKET_EDGES) - 1)]
    return res, buckets


def horizons():
    return [("ev", h) for h in C.EVENT_HORIZONS] + [("ns", t) for t in C.TIME_HORIZONS_NS]


def horizon_name(kind, h):
    if kind == "ev":
        return f"{h}ev"
    return f"{h // 1_000_000}ms" if h < C.NS else f"{h // C.NS}s"


def day_stats(df):
    """One row per horizon for one symbol-day."""
    df = collapse_same_timestamp(df)
    ts = df["ts_ns"].to_numpy()
    mid, imb = mid_and_imbalance(df)
    sess = in_session(ts)
    out = []
    for kind, h in horizons():
        d = forward_change_events(mid, ts, h) if kind == "ev" else forward_change_time(mid, ts, h)
        s, buckets = signal_stats(np.where(sess, imb, np.nan), d)
        row = {"horizon": horizon_name(kind, h), **s}
        row.update({f"bucket{k}": v for k, v in enumerate(buckets)})
        out.append(row)
    return out, {"rows_raw": int(len(df)), "rows_in_session": int(sess.sum()),
                 "two_sided_in_session": int((sess & np.isfinite(imb)).sum())}
