"""Frozen study choices (docs/design.md). Changing anything here after results exist
must be logged in docs/progress.md (the trials log)."""

SYMBOLS = ("SPY", "QQQ", "IWM", "MSFT", "AAPL")

# Nasdaq PSX ITCH 5.0 days. Chronological split fixed before any result.
DEV_DAYS = ("20181228", "20190130", "20190327", "20190530", "20190730")
HELDOUT_DAYS = ("20190830", "20191030", "20191230", "20200130")

EVENT_HORIZONS = (1, 10, 100)                                   # book updates ahead
TIME_HORIZONS_NS = (100_000_000, 1_000_000_000, 10_000_000_000)  # 100 ms, 1 s, 10 s

NS = 1_000_000_000
SESSION_START_NS = (9 * 3600 + 35 * 60) * NS     # 09:35 ET
SESSION_END_NS = (15 * 3600 + 55 * 60) * NS      # 15:55 ET
CLOSE_NS = 16 * 3600 * NS                        # 16:00 ET; no forward value past this

TICK = 100                                       # $0.01 in ITCH price units (1/10,000 $)
BUCKET_EDGES = (-1.0, -0.6, -0.2, 0.2, 0.6, 1.0)  # imbalance buckets for the summary table

# v2 (strategy simulation), frozen now, used later.
THRESHOLDS = (0.2, 0.4, 0.6, 0.8)
SPREAD_LIMITS_TICKS = (1, 2, None)   # trade only when the PSX spread is at most this (None: any)
LATENCIES_NS = (0, 10_000, 100_000, 1_000_000)
FEES_PER_SHARE = (0.0, 0.001, 0.003)

# v2 simulation decisions (docs/design.md, "v2 decisions"). Made before any v2 run.
HOLD_NS = 100_000_000             # exit is sent this long after the entry fill (100 ms)
REF_LATENCY_NS = 100_000          # reference cell used to select the variant (100 us)
REF_FEE_PER_SHARE = 0.001         # reference fee used to select the variant ($0.001/share)
MIN_TRADES_SELECT = 100           # a variant needs this many development trades to be eligible
RANDOM_REPS = 200                 # random-direction baseline repetitions
RANDOM_SEED = 20261025            # fixed seed for the random baseline
