# Progress and trials log

Every signal, parameter set and evaluation run is logged here, including failures.
The count of strategy variants tried feeds the deflated Sharpe in v2.

| Version | Item | Status |
|---|---|---|
| v1 | Exporter, reference check, signal study on development days | built |
| v1 | Real-data reference check on a prefix of each symbol | -- |
| v1 | Development-day results | -- |
| v2 | Strategy simulation | not started |
| v2 | Held-out evaluation (once) | not started |

## Trials
| # | Date | Set | What | Parameters | Outcome |
|---|---|---|---|---|---|
| 1 | 2026-10-25 | dev | v1 signal study (H1, frozen design) | 5 symbols x 6 horizons | run vm-v1-20261025-161440; see README v1 results |
| 2 | 2026-10-25 | dev | Diagnostic: PSX spread, tail share of covariance, Spearman | top 0.1% of rows by abs change | run vm-v1-diag-20261025-161947: Spearman > 0 for all 5 symbols and 6 horizons; AAPL Pearson < 0 from rare huge jumps; tail-share ratio unstable (near-zero denominator), not used |
| 3 | 2026-10-25 | dev | Decision after trial 2, before held-out | Spearman as frozen secondary H1 test; v2 spread limit 1, 2, any (12 variants) | logged in docs/design.md |
