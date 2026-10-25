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
--
<!-- v1-results:end -->

## What the numbers show

<!-- v1-shown:begin -->
### v1
--
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
