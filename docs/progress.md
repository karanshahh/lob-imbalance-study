# Progress and trials log

Every signal, parameter set and evaluation run is logged here, including failures.
The count of strategy variants tried feeds the deflated Sharpe in v2.

| Version | Item | Status |
|---|---|---|
| v1 | Exporter, reference check, signal study on development days | built |
| v1 | Real-data reference check | QQQ 20190130 and AAPL 20190327, first 200,000 rows each: match |
| v1 | Development-day results | results/vm-v1-20261025-162612 (rerun of results/vm-v1-20261025-161440, identical); export benchmark results/vm-v1-export-20261025-162724.txt |
| v2 | Strategy simulation | built and tested; development grid run (trial 4): results/vm-v2-dev-20261025-220832 |
| v2 | Held-out evaluation (once) | not started |

## Trials
| # | Date | Set | What | Parameters | Outcome |
|---|---|---|---|---|---|
| 1 | 2026-10-25 | dev | v1 signal study (H1, frozen design) | 5 symbols x 6 horizons | run vm-v1-20261025-161440; see README v1 results |
| 2 | 2026-10-25 | dev | Diagnostic: PSX spread, tail share of covariance, Spearman | top 0.1% of rows by abs change | run vm-v1-diag-20261025-161947: Spearman > 0 for all 5 symbols and 6 horizons; AAPL Pearson < 0 from rare huge jumps; tail-share ratio unstable (near-zero denominator), not used |
| 3 | 2026-10-25 | dev | Decision after trial 2, before held-out | Spearman as frozen secondary H1 test; v2 spread limit 1, 2, any (12 variants) | logged in docs/design.md |
| 4 | 2026-10-25 | dev | v2 strategy simulation, full development grid | 12 variants x 4 latencies x 3 fees x 5 symbols, 5 development days; random-direction baseline, 200 repetitions per variant | run results/vm-v2-dev-20261025-220832 (commit 2d1983a): every variant has negative mean net P&L per trade at the reference cell; selection in selection.json |
