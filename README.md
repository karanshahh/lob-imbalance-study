# lob-imbalance-study

Does order-book imbalance predict the next short-term move in the mid price, and would a
rule that trades on it survive the spread and fees? This study rebuilds the Nasdaq PSX
book from raw ITCH messages with a C++ order book, then tests the question in Python with
every choice fixed in advance and four days held out.

## Who, what, where, why

| | |
|---|---|
| Who | Reviewers of market-microstructure research and low-latency C++ work |
| What | A C++ exporter on top of [orderbook](https://github.com/karanshahh/orderbook) (v2.1.0) that writes the top of the book after every update, and a Python study of imbalance vs forward mid changes |
| Where | OrbStack Ubuntu VM on Apple Silicon (VM numbers); CI on GitHub's x86 runners |
| Why | Imbalance is one of the simplest short-horizon signals. Testing it honestly, with a held-out set and costs, shows whether it carries information and whether that information is tradable |

## Primer
- **Order book:** resting buy orders (bids) and sell orders (asks) at each price. The
  **best bid** is the highest bid, the **best ask** the lowest ask.
- **Mid price:** halfway between the best bid and best ask. **Spread:** the gap between them.
- **Imbalance** I = (bid size - ask size) / (bid size + ask size) at the best prices, from
  -1 (all size on the ask) to +1 (all on the bid). The idea: when much more size waits to
  buy than to sell, the price is more likely to tick up next.
- **ITCH:** Nasdaq's binary feed of every add, execution, cancel, delete and replace.
  Replaying it rebuilds the exchange's book. **PSX** is one of Nasdaq's smaller venues.
- **Held-out days:** days not looked at until every rule is frozen, used once, so the
  result can't be tuned to them.

## Main parts

| Part | What it does |
|---|---|
| `tools/lob_export` | One pass over an ITCH file; per symbol, writes seq, timestamp, best bid/ask price and size after every book op |
| `include/lobstudy/export.hpp` | The replay-and-export logic used by the tool and the tests |
| `analysis/study.py` | Mid, imbalance, forward changes (event and time horizons), session filter, statistics |
| `analysis/run_signal_study.py` | Runs the study over a day set; held-out days need `--final` and work once |
| `analysis/itch_ref.py` | Independent Python rebuild of the top of book from raw ITCH, to check the export |
| `analysis/config.py` | Every frozen choice: symbols, days, horizons, session, v2 grids |
| `analysis/sim.py` | v2 rules: fills with latency, one position at a time, fees, random-direction baseline, per-trade Sharpe |
| `analysis/run_strategy_sim.py` | Development-day grid (12 variants x 4 latencies x 3 fees x 5 symbols) and variant selection; cannot open held-out days |
| `analysis/run_heldout_sim.py` | The H2 test on held-out days, once (own lock file); `--rehearsal` runs it on development days |
| `analysis/diagnose_sim.py` | Splits each trade's P&L exactly into signed mid move minus half entry and exit spread |
| `scripts/run_heldout.sh` | The one-way step: exports held-out days, runs H2 then H1, each behind a lock |

## Versions

### v1: signal study
No trading. For each symbol, development day and horizon: the correlation and slope of
the forward mid change against imbalance, the share of zero changes, and mean changes by
imbalance bucket. Days are the unit of inference.

| Design choice | Why |
|---|---|
| Book rebuilt with orderbook's v1 engine, pinned v2.1.0 | Proven identical to v2 on real data; no capacity setup |
| Export only the top of book; compute signals in Python | One job per side, each easy to check |
| Keep the last row per timestamp | An Order Replace is two ops at one nanosecond; the state between them never existed |
| Horizons 1/10/100 updates and 100 ms/1 s/10 s | Event and clock time; fixed before any result |
| Session 09:35 to 15:55 ET | The open and close behave differently |

### v2: strategy simulation
Trades the signal with simulated costs, against baselines, then one held-out evaluation. When flat and
inside the session, if |I| is at least a threshold and the PSX spread is at most a limit, the rule crosses
the spread: buy at the best ask if I > 0, sell at the best bid if I < 0. The order fills on the book that
exists after a latency delay. The exit is sent 100 ms after the entry fill and crosses the spread the other
way. One share, one position at a time, fees on both legs.

| Design choice | Why |
|---|---|
| Aggressive orders only (cross the spread) | The cost is known exactly from the book; no queue model is needed |
| 1 share, one position at a time, 100 ms hold | The size never exceeds the size at the best price, so no market-impact model; the hold was picked after v1 (correlations were strongest at 100 ms), which favours the signal |
| Latency 0, 10 us, 100 us, 1 ms; fees $0, $0.001, $0.003 per share | Shows how fast the edge disappears; every cell is reported |
| 12 variants: threshold 0.2, 0.4, 0.6, 0.8 x spread limit 1, 2, any ticks | Fixed before any run; all 12 count as trials |
| One variant per symbol, picked on development days and tested once on held-out days | Best mean net P&L per trade at 100 us and $0.001 with at least 100 trades; H2 is rejected for a symbol only if that variant is positive on all 4 held-out days |
| Baselines: random direction at the same entry rows (200 repetitions), always flat | Separates what the direction is worth from what crossing the spread costs |

Run it (needs the exports from `scripts/run_study.sh`):

```
.venv/bin/python analysis/run_strategy_sim.py --data data/export --out results --label vm-v2-dev
.venv/bin/python analysis/diagnose_sim.py --export-dir data/export --selection results/<dev run>/selection.json --out results --label vm-v2-diag
.venv/bin/python analysis/run_heldout_sim.py --export-dir data/export --selection results/<dev run>/selection.json --out /tmp/rehearsal --rehearsal
bash scripts/run_heldout.sh <label> results/<dev run>/selection.json    # held-out days, once
```

## Data
Nasdaq PSX TotalView-ITCH 5.0 sample days from https://emi.nasdaq.com/ITCH/, uncompressed
before use. Development days: 20181228, 20190130, 20190327, 20190530, 20190730. Held-out:
20190830, 20191030, 20191230, 20200130. Symbols: SPY, QQQ, IWM, MSFT (by a rule on
development days) and AAPL (by choice). Raw data is not committed.

## How correctness is checked

| Check | What it proves |
|---|---|
| C++ known-answer tests | Best-level sums, cancels and reduces, one-sided books, seq and timestamp columns |
| Determinism test | Same ops give byte-identical output |
| End to end (ctest) | On a synthetic ITCH file, the export matches an independent Python rebuild row for row |
| Real-data reference check | On a prefix of each real export, the same comparison |
| Python known-answer tests | Mid, imbalance, both horizon kinds, session edges, timestamp collapse, statistics |
| No-look-ahead and cheating-signal tests | The signal ignores later rows; a signal that sees the future is detected |
| Held-out lock test | The held-out days cannot be used twice |
| Slow reference simulator (v2) | A plain row-by-row implementation of the written rules matches the vectorised code on 1,800 random books (3,371 trades), including empty sides and crossed books |
| Known-answer tests (v2) | Hand-worked fills, latency, shorts, fees on both legs, one position at a time, and a constant book where every trade loses exactly one spread |
| Selection and held-out rule tests (v2) | The variant selection and the H2 rule are tested on hand-built tables, including a day with no trades and a net of exactly zero |
| Held-out locks and rehearsal (v2) | A typo or missing file cannot use up the single run; a second use is refused; the same code is rehearsed on development days |
| Mutation check | 71 deliberate bugs (18 for v1, 53 for v2), each caught by the tests |
| Sanitizers and CI | ASan+UBSan, TSan and Release locally; the same on x86 CI, plus the Python tests |

## Build, test, run

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/build.sh all                  # ASan+UBSan, TSan, Release, then Python tests
./scripts/mutation_check.sh             # every mutation must be caught
python3 analysis/itch_ref.py ~/itch/psx-study/20190130.PSX_ITCH_50 QQQ \
    --compare data/export/20190130/QQQ.csv --max-rows 200000
MACHINE_LABEL="VM numbers (OrbStack, Apple Silicon; Chrome closed)" ./scripts/run_study.sh vm-v1
MACHINE_LABEL="VM numbers (...)" PIN=2 ./scripts/run_bench.sh vm-v1-export
```

## Results

<!-- v1-results:begin -->
### v1
Development days only: 20181228, 20190130, 20190327, 20190530, 20190730. The held-out days are untouched.

Method: one row per book update (last op per timestamp); signals from 09:35 to 15:55 ET; statistics per
symbol-day, then the mean across the 5 days (days are the unit); in brackets, days with a positive value.
Machine: VM numbers (OrbStack, Apple Silicon aarch64, 8 CPUs; Chrome closed); GCC 15.2.0, Release -O3 -DNDEBUG;
Python 3.14.4 numpy 2.4.4 pandas 3.0.2; commit eeb74f9.
Raw output: `results/vm-v1-20261025-162612/` (full table: `signal_summary_dev.txt`, per day: `signal_per_day_dev.csv`); first run
`results/vm-v1-20261025-161440/` (identical); diagnostic `results/vm-v1-diag-20261025-161947/`.

| Symbol | PSX spread: one-tick share, median (ticks) | Zero changes at 1 update | Pearson, 10 updates | Spearman, 10 updates | Pearson, 1 s | Spearman, 1 s |
|---|---|---|---|---|---|---|
| SPY | 27.3%, 2.2 | 76% | 0.162 (4/5) | 0.200 (4/5) | 0.084 (4/5) | 0.108 (4/5) |
| QQQ | 38.3%, 1.6 | 82% | 0.098 (4/5) | 0.199 (5/5) | 0.045 (3/5) | 0.107 (5/5) |
| IWM | 36.2%, 1.6 | 82% | 0.167 (5/5) | 0.190 (5/5) | 0.095 (5/5) | 0.115 (5/5) |
| MSFT | 20.9%, 2.2 | 69% | 0.021 (4/5) | 0.150 (5/5) | 0.012 (4/5) | 0.115 (5/5) |
| AAPL | 1.4%, 5.2 | 56% | -0.037 (1/5) | 0.108 (4/5) | -0.049 (1/5) | 0.077 (3/5) |

Export (`lob_export`), 20190130, pinned to one CPU, 3 runs; raw output `results/vm-v1-export-20261025-162724.txt`:

| Step | Runs | Time | Rate |
|---|---|---|---|
| Parse and replay-build, 1 day (41,448,696 messages, 5 symbols) | 2-3 | 1.27 s | 32.6 M messages/s |
| Same, run 1 | 1 | 4.68 s | 8.9 M messages/s |
| Export all 5 symbols (3,115,286 rows) | 1-3 | 0.48-0.58 s | 5.4-6.5 M rows/s |

Run 1 of the parse is slower; likely the file was read from disk, and runs 2-3 from the page cache.
<!-- v1-results:end -->

<!-- v2-results:begin -->
### v2
Development days (5) for the grid and the selection; held-out days (4) for the single evaluation. 1 share,
100 ms hold, reference cell latency 100 us and fee $0.001 per share; 1 tick = $0.01; net = gross - $0.002 (fee
on both legs). Python numbers are per trade.
Machine: VM numbers (OrbStack Ubuntu, Apple Silicon aarch64, 8 CPUs; Chrome closed, Mac idle); 3.14.4  numpy: 2.4.4  pandas: 3.0.2. Commits: development grid 2d1983a, decomposition 4f74475, held-out 45f139d.
Raw output: `results/vm-v2-dev-20261025-220832/` (grid.csv, pooled.csv, baseline.csv, selection.json), `results/vm-v2-diag-20261025-223356/` (decomposition.csv),
`results/vm-v2-heldout-20261025-173948/` (h2_*.csv, signal_summary_heldout.*); locks `results/HELDOUT_SIM_USED` and `results/HELDOUT_USED`.

**Development grid: the selected variant per symbol (5 days pooled)**

| Symbol | Selected variant (threshold, spread limit) | Trades | Gross (ticks) | Net (USD per trade) | Random direction, same entry rows (USD) | Difference (USD) |
|---|---|---|---|---|---|---|
| SPY | 0.8, 1 tick | 22,652 | -1.235 | -0.01435 | -0.01607 | +0.00172 |
| QQQ | 0.8, 1 tick | 124,842 | -1.189 | -0.01389 | -0.01505 | +0.00115 |
| IWM | 0.8, 1 tick | 38,947 | -1.170 | -0.01370 | -0.01478 | +0.00108 |
| MSFT | 0.2, 1 tick | 66,300 | -1.900 | -0.02100 | -0.02036 | -0.00065 |
| AAPL | 0.8, 1 tick | 423 | -1.969 | -0.02169 | -0.03339 | +0.01169 |

All 60 variants (12 per symbol) have a negative mean net P&L per trade at the reference cell. Full grid, every
latency and fee: `pooled.csv`.

**Where a trade's P&L goes** (selected variant, 5 development days, ticks per trade). Gross = signed mid move -
entry half-spread - exit half-spread, exactly, on every trade.

| Symbol | Latency | Signed mid move | Entry half-spread | Exit half-spread | Gross |
|---|---|---|---|---|---|
| SPY | 0 | +0.275 | 0.500 | 0.800 | -1.024 |
| SPY | 10 us | +0.260 | 0.516 | 0.800 | -1.057 |
| SPY | 100 us | +0.172 | 0.607 | 0.800 | -1.235 |
| SPY | 1 ms | +0.082 | 0.681 | 0.800 | -1.399 |
| QQQ | 0 | +0.187 | 0.500 | 0.730 | -1.043 |
| QQQ | 10 us | +0.178 | 0.509 | 0.730 | -1.061 |
| QQQ | 100 us | +0.115 | 0.574 | 0.730 | -1.189 |
| QQQ | 1 ms | +0.066 | 0.640 | 0.730 | -1.303 |
| IWM | 0 | +0.163 | 0.500 | 0.715 | -1.052 |
| IWM | 10 us | +0.152 | 0.512 | 0.715 | -1.076 |
| IWM | 100 us | +0.108 | 0.562 | 0.716 | -1.170 |
| IWM | 1 ms | +0.060 | 0.614 | 0.717 | -1.271 |
| MSFT | 0 | -0.013 | 0.500 | 1.179 | -1.693 |
| MSFT | 10 us | -0.026 | 0.526 | 1.181 | -1.733 |
| MSFT | 100 us | -0.065 | 0.657 | 1.179 | -1.900 |
| MSFT | 1 ms | -0.084 | 0.772 | 1.182 | -2.038 |
| AAPL | 0 | +1.259 | 0.500 | 2.487 | -1.728 |
| AAPL | 10 us | +1.251 | 0.513 | 2.487 | -1.749 |
| AAPL | 100 us | +1.199 | 0.681 | 2.487 | -1.969 |
| AAPL | 1 ms | +1.011 | 0.940 | 2.487 | -2.416 |

**Held-out, H2** (selected variant; mean net USD per trade per day, trades in brackets)

| Symbol | Variant | 20190830 | 20191030 | 20191230 | 20200130 | Days positive | H2 |
|---|---|---|---|---|---|---|---|
| SPY | 0.8, 1 tick | -0.01416 (4,319) | -0.01873 (2,111) | -0.01374 (11,217) | -0.01784 (10,415) | 0 of 4 | not rejected |
| QQQ | 0.8, 1 tick | -0.01376 (8,894) | -0.01578 (12,904) | -0.01360 (27,968) | -0.01462 (44,936) | 0 of 4 | not rejected |
| IWM | 0.8, 1 tick | -0.01329 (7,114) | -0.01645 (110) | -0.01402 (5,418) | -0.01413 (8,322) | 0 of 4 | not rejected |
| MSFT | 0.2, 1 tick | -0.01596 (5,648) | -0.06471 (2,698) | -0.01731 (10,909) | -0.05145 (5,012) | 0 of 4 | not rejected |
| AAPL | 0.8, 1 tick | -0.01723 (218) | -0.57229 (34) | -2.79200 (6) | -0.02200 (4) | 0 of 4 | not rejected |

H2 is rejected for a symbol only if its net is positive on all 4 days. It was rejected for 0 of 5 symbols (about
0.31 would pass by chance if days were a coin flip).

**Held-out, H1** (mean daily correlation of imbalance with the forward mid change; days with a positive value in
brackets). Frozen rule: positive on all 4 days.

Pearson (primary):

| Symbol | 1 update | 10 updates | 100 updates | 100 ms | 1 s | 10 s |
|---|---|---|---|---|---|---|
| SPY | 0.118 (4/4) | 0.143 (4/4) | 0.080 (4/4) | 0.136 (4/4) | 0.087 (4/4) | 0.031 (4/4) |
| QQQ | 0.039 (4/4) | 0.033 (4/4) | 0.025 (4/4) | 0.034 (4/4) | 0.031 (3/4) | 0.023 (4/4) |
| IWM | 0.068 (4/4) | 0.077 (4/4) | 0.039 (4/4) | 0.076 (4/4) | 0.062 (4/4) | 0.037 (4/4) |
| MSFT | 0.007 (2/4) | 0.013 (3/4) | 0.037 (4/4) | 0.014 (4/4) | 0.006 (3/4) | 0.038 (4/4) |
| AAPL | 0.009 (3/4) | 0.008 (3/4) | 0.019 (3/4) | 0.013 (3/4) | 0.006 (3/4) | 0.023 (3/4) |

Spearman (secondary):

| Symbol | 1 update | 10 updates | 100 updates | 100 ms | 1 s | 10 s |
|---|---|---|---|---|---|---|
| SPY | 0.166 (4/4) | 0.184 (4/4) | 0.091 (4/4) | 0.175 (4/4) | 0.111 (4/4) | 0.048 (4/4) |
| QQQ | 0.173 (4/4) | 0.159 (4/4) | 0.065 (4/4) | 0.167 (4/4) | 0.093 (4/4) | 0.039 (4/4) |
| IWM | 0.180 (4/4) | 0.164 (4/4) | 0.070 (4/4) | 0.168 (4/4) | 0.119 (4/4) | 0.055 (4/4) |
| MSFT | 0.114 (3/4) | 0.082 (3/4) | 0.081 (4/4) | 0.064 (3/4) | 0.045 (3/4) | 0.085 (4/4) |
| AAPL | 0.089 (3/4) | 0.067 (3/4) | 0.057 (2/4) | 0.096 (3/4) | 0.083 (3/4) | 0.075 (3/4) |

The rule passed on 20 of 30 symbol-horizon tests with Pearson and 20 of 30 with Spearman; about 1.9 would pass
by chance if there were no effect.
<!-- v2-results:end -->

## What the numbers show

<!-- v1-shown:begin -->
### v1
Shown (development days):
- For the three ETFs, imbalance is positively related to the next mid change at every horizon: mean daily
  Pearson correlation 0.02 to 0.17, positive on 3 to 5 of 5 days; IWM positive on all 5 days at all 6 horizons.
- The relation is strongest at the shortest horizons and fades: SPY 0.14 to 0.16 at 1 to 10 updates and
  100 ms, 0.03 at 10 s.
- Most short-horizon updates do not move the mid: 76% to 82% zero changes at 1 update for the ETFs, under
  10% at 10 s.
- The effect is small in price terms: for the ETFs, slopes of 0.04 to 0.24 ticks per unit of imbalance,
  well under a one-tick spread. Whether it can be traded is H2 (v2).
- On ranks (Spearman), the relation is positive on average for all 5 symbols at all 6 horizons, positive on
  3 to 5 of 5 days.
- AAPL's Pearson correlation is negative (-0.03 to -0.05). Its PSX book is thin (one-tick spread 1.4% of
  updates) and its mid makes rare huge jumps (99.9th percentile 330 to 380 ticks, max 1,024).
- A second run reproduced every number. The export matches an independent Python rebuild from raw ITCH on
  the first 200,000 rows of QQQ (20190130) and AAPL (20190327).

Likely:
- AAPL's negative Pearson comes from PSX book artifacts (the best level empties and the next PSX order is far
  away) rather than market moves; Spearman, which ignores jump size, is positive.
- The slower first parse is disk reads; runs 2-3 read from the page cache.

What did not work:
- The share of covariance from the top 0.1% of rows: unstable (-4.8 to 101 for MSFT) because the total
  covariance is near zero. Reported, not used.

To measure next (v2):
- Whether a rule that crosses the spread survives fees and latency, with the spread-limit grid; then the
  single held-out evaluation of H1 (Pearson primary, Spearman secondary) and H2.
<!-- v1-shown:end -->

<!-- v2-shown:begin -->
### v2
Shown (development and held-out days, VM numbers):
- On development days all 60 variants lose money per trade at the reference cell, and lose before fees too.
- On held-out days the selected variant of every symbol loses on every day: 20 of 20 symbol-days are negative and
  H2 is rejected for none of the 5 symbols. For the ETFs the held-out loss is $0.0133 to $0.0187
  per trade, the same size as the development loss.
- The signal has value, but far less than the cost of crossing the spread. For SPY, QQQ and IWM the mid moves in
  the signal's direction by 0.11 to 0.17 ticks on average, while the trade pays 1.28 to 1.41
  ticks of half-spreads plus 0.2 ticks of fees. Even at zero latency and zero fees SPY loses 1.02 ticks per trade.
- Delay eats the move: SPY's signed move falls from +0.275 ticks at zero latency to +0.082 at 1 ms while its entry
  half-spread grows from 0.500 to 0.681 ticks; QQQ and IWM show the same pattern.
- Direction beats random on development days for the ETFs: in all 12 one-tick-limit ETF variants the strategy does
  better than a random direction at the same entry rows, by $0.0004 to $0.0017 per trade, and the
  gap grows with the threshold. For MSFT it is worse than random in all 4. AAPL's selected variant (423 trades) is
  inside the random range. The random range reflects only the random directions, not uncertainty across days.
- H1 holds out of sample for the ETFs: SPY and IWM pass at all six horizons, QQQ at five of six with Pearson (1 s
  fails, 3 of 4 days) and six of six with Spearman; mean Pearson 0.02 to 0.14. MSFT passes 3 of 6
  (Spearman 2 of 6) and AAPL none. On held-out days 73% to 77% of ETF updates do not move the mid at 1 update.
- The held-out ETF slopes are 0.09 to 0.46 ticks per unit of imbalance, larger than the development
  range (0.04 to 0.24). Not explained.

Likely (not tested):
- The exit spread (SPY: about 1.6 ticks, a half-spread of 0.80) is wider than the 1 tick or less required at the
  signal, because entries are taken at the 1-tick minimum and the spread tends to widen afterwards.
- MSFT's heavy-loss days (20181228 at $0.117 per trade on development days; 20191030 and 20200130 on held-out days)
  and AAPL's sparse held-out days (4 to 218 trades per day, two with losses of $0.57 and $2.79 per trade) come from
  thin PSX books. Not investigated.

Not done:
- Deflated Sharpe: not computed. Every variant's mean net P&L is negative, so deflating a Sharpe could only make it
  lower. The trial counts are in docs/progress.md (12 variants per symbol, 60 in the grid, trials 1 to 6).
- The order flow imbalance baseline (Cont, Kukanov and Stoikov, 2014): not built; it is in the v3 options.

To measure next:
- Whether the held-out direction value (strategy minus random direction) matches the development figure; the
  held-out baseline.csv exists and has not been read.
- Why the held-out ETF slopes are larger than the development ones.
- Spread at exit against spread at entry, to test the guess above.
- Passive orders with a queue model (they could earn the spread instead of paying it); deeper books on main-Nasdaq
  days; a final run on a rented x86 Linux box.
<!-- v2-shown:end -->

## Repository layout

```
CMakeLists.txt            C++23; orderbook v2.1.0 and GoogleTest via FetchContent
include/lobstudy/         export.hpp
tools/                    lob_export.cpp
tests/                    export_test.cpp
analysis/                 config, study, runner, ITCH reference, end-to-end check, tests
scripts/                  build.sh, mutation_check.sh, run_study.sh, run_bench.sh
docs/                     design.md, progress.md
results/                  raw outputs of each run, committed
.github/workflows/        CI: sanitizer matrix and Release with Python tests
```
