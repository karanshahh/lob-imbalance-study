# Design: lob-imbalance-study

## What and which track
Does order-book imbalance on Nasdaq PSX predict the next short-horizon mid-price move,
and does any trading rule built on it survive the spread and fees? Track: both.
C++ rebuilds the book from ITCH and exports the top of the book (dev); Python analyses
it and later simulates trading.

## Repo and dependency
- New repo `lob-imbalance-study`.
- orderbook is pulled with FetchContent, pinned to tag `v2.1.0`: the v1 book, the ITCH
  decoder and ReplayBuilder, with message timestamps (added in v2.1.0 for this study).
- The study uses the v1 book (std::map levels). orderbook's differential test shows v1
  and v2 produce identical events on real data, and v1 needs no capacity configuration.

## Versions
- **v1 Signal study.** No trading. Imbalance vs forward mid change, per symbol, day and
  horizon, on development days only.
- **v2 Strategy simulation.** Aggressive (spread-crossing) orders only, with fees and
  latency, against baselines; threshold chosen on development days. Then the single
  held-out evaluation of H1 and H2 together.
- **v3 (optional)** Multi-level imbalance (needs a read-only level accessor, orderbook
  v2.2.0), passive fills with a queue model, or a deeper-book check on main-Nasdaq days.

## Data
- Source: Nasdaq PSX TotalView-ITCH 5.0 sample days, https://emi.nasdaq.com/ITCH/
  (folder "Nasdaq PSX ITCH"), downloaded 2026-10-25. Uncompressed before use (the
  reader needs raw files). Raw data is never committed; `data/` is ignored.
- Integrity: Nasdaq's .md5sum files returned 404, so their checksums could not be
  checked. Each file matched the listed size byte for byte and passed `gzip -t`; our own
  md5s are in `~/itch/psx-study/md5_computed_20261025.txt` on the VM.
- 9 days have data. Split fixed before any result, chronological:
  - development: 20181228, 20190130, 20190327, 20190530, 20190730
  - held-out: 20190830, 20191030, 20191230, 20200130 (used once, everything frozen)
  The days are 1-2 months apart, so conditions differ between days (a limitation, and
  the held-out days are out of time as well as out of sample).
- Symbols, chosen on development days only:
  - SPY, QQQ, IWM, MSFT by rule: top 15 by add orders on all 5 development days,
    excluding leveraged and volatility products (TQQQ, UVXY, VXX, TVIX, ...).
  - AAPL by choice (one of the largest US companies); top 15 on only 2 of 5 days.
- Locate codes come from each file's own Stock Directory messages.
- Limitations: PSX is one small venue, not the national best bid and offer. Its books are
  shallow (QQQ peak 133 resting orders, MSFT 38 on 20190130). Results describe PSX only.

## Definitions
- **Row:** lob_export writes the top of the book after every book op. Several ops can
  share one timestamp (an Order Replace is a cancel then an add at the same nanosecond),
  and the book between them was never observable. Analysis keeps the last row per
  timestamp: one row = one **book update**.
- **Mid** = (best bid + best ask) / 2, in ticks of $0.01. **Imbalance**
  I = (bid_qty - ask_qty) / (bid_qty + ask_qty) at the best prices, in [-1, 1].
  Both undefined when a side is empty.
- **Forward mid change:** event horizons 1, 10, 100 book updates ahead; time horizons
  100 ms, 1 s, 10 s ahead (mid of the update in force at t + horizon). No forward value
  past 16:00 or past the last update of the day.
- **Session:** signals only from 09:35:00 to 15:55:00 ET (ITCH timestamps are ns since
  midnight ET).
- Change logged before any result: the horizons were first frozen as "book ops"; they
  were redefined as book updates (last op per timestamp) when the replace case showed
  that intermediate op states are not real book states.

## Hypotheses (written before any run)
- **H1:** I is positively related to the forward mid change at every horizon.
  Frozen rule: H1 holds for a symbol and horizon if the daily correlation is positive on
  all 4 held-out days (one-sided sign test, p = 1/16 per test). With 5 symbols x 6
  horizons = 30 tests, about 1.9 would pass by chance; the count passing is reported
  against that.
  Secondary (frozen after the development diagnostic, before any held-out use): the same
  rule with Spearman (rank) correlation. Both are reported whichever way they go.
- **H2:** a rule that crosses the spread when |I| >= threshold does NOT have positive
  mean P&L per trade after spread and fees on held-out days. A clean negative result is
  a valid outcome.
- Risk: the mid often does not move at short horizons (large tick relative to price).
  The share of zero changes is reported for every horizon.

## Changes after development results (logged before any held-out use)
- Trial 2 (diagnostic) found AAPL's negative Pearson correlation came from rare huge
  PSX mid jumps (99.9th percentile 330-380 ticks, max 1,024 ticks) on a thin book
  (one-tick spread 1.4% of the time), while its Spearman correlation was positive.
- Trial 3 (decision): H1 keeps Pearson as the primary test; Spearman added as a frozen
  secondary test. No data filter for H1. The v2 grid adds a spread limit (below).

## Signals
- Baseline 1 (v1): top-of-book imbalance.
- Baseline 2 (v3, optional): multi-level imbalance, levels 1-5.
- Baseline 3 (v2): order flow imbalance after Cont, Kukanov and Stoikov (2014); verify
  the paper and its definition before implementing.
- Every signal and parameter set tried is logged in docs/progress.md, with the count
  used for a deflated Sharpe (Bailey and Lopez de Prado, 2014).

## Strategy simulation (v2), frozen now
- Trade when |I| >= threshold and the PSX spread is at most a limit. Grid: threshold
  0.2, 0.4, 0.6, 0.8 x spread limit 1 tick, 2 ticks, any = 12 variants, chosen on
  development days; all 12 count as trials for the deflated Sharpe.
- Fill model: aggressive only. Buy at the best ask, sell at the best bid, using the book
  in force after a latency delay of 0, 10 us, 100 us or 1 ms (all reported). Own market
  impact is ignored, and that is stated.
- Fees (simulated): $0, $0.001, $0.003 per share, all reported.
- No look-ahead by design: the signal at time t uses rows up to t; the fill uses the book
  at t + latency.
- Baselines: random direction with the same number of trades; always flat.

## What we measure
- v1: per symbol, day and horizon: updates, share of zero mid changes, correlation (Pearson, and Spearman on ranks),
  regression slope (ticks per unit of I), mean change by imbalance bucket
  (edges -1, -0.6, -0.2, 0.2, 0.6, 1). Across days: mean daily correlation, its standard
  error, and days with positive correlation (days are the unit, which handles the
  overlap of forward windows within a day).
- v2: mean P&L per trade, hit rate, trades per day, turnover, Sharpe with uncertainty,
  max drawdown; development and held-out reported separately.
- Systems: lob_export run time per day (parse + export, all symbols), 3 runs, VM numbers.

## Correctness plan
- C++ known-answer tests on hand-built op sequences (best-level sums, cancel moving to
  the next level, reduce in place, one-sided book, seq and timestamp columns), and a
  determinism test.
- Independent reference: `analysis/itch_ref.py` rebuilds the top of the book from raw
  ITCH bytes in plain Python (no shared code with orderbook). ctest runs it end to end on
  a synthetic ITCH file (adds, executions, partial cancel, delete, replace, unknown
  reference, a second symbol, an ignored message type); on real data it checks a prefix
  of each export.
- Python known-answer tests: mid, imbalance, forward changes at both kinds of horizon,
  session boundaries, the same-timestamp collapse, statistics; a no-look-ahead test; a
  cheating signal (the future change) must show correlation about 1; noise about 0;
  the held-out lock refuses a second use.
- Mutation check (18, each must be caught): bid quantity read from the ask side; reduce
  treated as cancel; seq starting at 1; timestamp dropped; messages fed to one symbol
  only; imbalance sign flipped; event horizon off by one; time horizon taking the wrong
  row; one-sided rows kept; first row per timestamp kept; session starting 09:30;
  held-out lock not checked; reference ignoring replace; reference reading the price at
  the wrong offset; Spearman without ranks; one-tick share counting wider spreads; tail
  share taking the smallest changes; the study's Spearman without ranks.
- All C++ tests under ASan+UBSan, TSan and Release; CI on x86 runs the same plus the
  Python tests.

## Concepts exercised
- C++: strong types and `std::optional` from orderbook's API, RAII file streams,
  `std::to_chars` for fast formatting, `std::variant` messages (orderbook), FetchContent
  and version pinning.
- Research: pre-registration, a fixed split, day-level inference, multiple-testing
  accounting, a no-look-ahead design, an independent reference implementation.
- Python: numpy vectorised horizons (`searchsorted`), pandas.

## Done means
- All tests green, all mutations caught, CI green.
- v1 and v2 results in the README with machine, method and raw files; held-out days
  touched once; trials log committed.
- The README states the honest conclusion, whichever way it goes.

