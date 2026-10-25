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

## v2 decisions (2026-10-25, fixed before any v2 run)
These choices were fixed before any v2 number existed.
Implementation: analysis/sim.py (rules), analysis/run_strategy_sim.py (development days
only), tests with a slow independent reference in analysis/test_sim.py.

1. **Entry.** When flat, a row inside the session with |I| >= threshold and PSX spread
   <= limit fires. I > 0: buy at the best ask. I < 0: sell at the best bid. The fill uses
   the last row with timestamp <= t + latency.
2. **Exit.** Sent 100 ms after the entry fill (t + latency + 100 ms), filled at the
   opposite best price using the last row with timestamp <= t + 100 ms + 2 x latency.
3. **Position.** One share, one position at a time. A signal while a position is open is
   ignored (signal time before the exit fill time). Fees are charged on both legs.
4. **Empty side.** Entry side empty at the fill row: trade skipped, no position opened.
   Exit side empty: use the first later row that has it. None before 16:00: trade dropped.
   Skipped and dropped trades are counted and reported per cell.
5. **Selection.** Per symbol, the variant with the highest development-day mean net P&L
   per trade at the reference cell (latency 100 us, fee $0.001 per share), among variants
   with at least 100 development trades. If none qualifies, H2 stands for that symbol.
6. **H2 test (held-out, once).** Only the selected variant is run. H2 is rejected for a
   symbol only if its mean net P&L per trade at the reference cell is positive on all 4
   held-out days; a day with no trades counts as not positive. Chance level is 1/16 per
   symbol (about 0.31 of 5 expected). Other latencies, fees and variants are descriptive.
7. **Baselines.** Random direction at the same entry rows (200 repetitions, fixed seed,
   one-position rule not re-applied, unfillable directions dropped) and always flat (zero).
8. **Sharpe.** Per-trade Sharpe with an iid standard error, which understates the
   uncertainty because trades are not independent. The deflated Sharpe (N = 12 trials per
   symbol, N = 60 overall) is added only after its definition is checked against Bailey
   and Lopez de Prado (2014); until then it is not reported.
9. **OFI baseline.** A signal comparison only (correlation with the forward change, as in
   v1), not a traded rule. Cont, Kukanov and Stoikov (2014), Journal of Financial
   Econometrics 12(1), 47-88, exists and defines OFI at the best bid and ask. The exact
   event formula must be read from the paper (Section 2.1) before implementing. Here OFI
   would be computed from consecutive collapsed rows, which nets out events inside one
   timestamp, and trailing OFI against the forward change is our own extension, not the
   paper's test. Not implemented yet.

Limits stated up front:
- The 100 ms hold was chosen after seeing v1 development results (correlations were
  strongest at 100 ms). That favours the signal, so a negative result is stronger.
- One share means the size at the touch never limits a fill. Own market impact and the
  borrow cost of shorts are ignored.
- PSX only: one small venue, shallow books. Results describe PSX, not the market.
- Trial 4 in docs/progress.md is the development grid: 12 variants per symbol.

## v2 held-out procedure and diagnostics (added 2026-10-25, before any held-out use)
- **Trial 4 (development grid).** Run on the 5 development days: every one of the 60
  variants (12 per symbol, 5 symbols) has a negative mean net P&L per trade at the
  reference cell. Raw output: results/vm-v2-dev-20261025-220832/. The variant selected
  per symbol is written by the code (selection.json), not chosen by hand.
- **Trial 5 (diagnostic, development days, read-only).** analysis/diagnose_sim.py splits
  each selected variant's gross P&L per trade exactly into: signed mid move minus half the
  entry spread minus half the exit spread, at each latency. It changes no rule or constant.
- **Held-out procedure.** scripts/run_heldout.sh runs once, in this order: H2 with
  analysis/run_heldout_sim.py --final (lock results/HELDOUT_SIM_USED), then H1 with
  analysis/run_signal_study.py --set heldout --final (lock results/HELDOUT_USED). Each lock
  is created before anything is computed. The script first checks, without reading
  held-out data: Release build, a clean git tree, the selection file committed, the
  input files present, no lock present, and a typed confirmation.
- **A failure after a lock is claimed spends that use.** Re-running then needs a decision
  logged in docs/progress.md, not a quiet retry.
- **Rehearsal.** run_heldout_sim.py --rehearsal runs the same code on the development days
  with no lock, to prove the pipeline on real data first. Its verdict is not a result.
- **Reading the held-out results.** The verdict rules are the frozen ones: H2 item 6 of
  "v2 decisions", and H1 as written under Hypotheses (Pearson primary, Spearman secondary).
  Both are reported whichever way they go. The selected variants are not revisited.

## v2 outcome notes (added 2026-10-25, after the held-out run; no rule changed)
- Deflated Sharpe (item 8 of "v2 decisions"): not computed. Every variant's mean net P&L per trade is negative on
  development and held-out days, so deflating a Sharpe could only lower it. Trial counts: 12 variants per symbol,
  60 in the grid; trials 1 to 6 are logged in docs/progress.md.
- OFI baseline (item 9): not implemented. Moved to the v3 options.
- The held-out baseline.csv (random direction) was written by the run and has not been read.
