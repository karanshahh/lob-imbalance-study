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
Planned: cross the spread when |I| is past a threshold, with simulated fees and latency,
against random and flat baselines; then the single held-out evaluation. See
docs/design.md.

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
| Mutation check | 18 deliberate bugs, each caught by the tests |
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
