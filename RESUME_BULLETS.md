# Resume bullets

XYZ format: accomplished **X**, measured by **Y**, by doing **Z**. Every number is read from `results/metrics.json` by `report.py` (generated 2026-09-14, data through 2026-09-14).

- Built and backtested a long-only time-series-momentum strategy (12-1 momentum + 200-day SMA filter, vol-scaled, monthly rebalance) on 10 ETFs over 21 years, cutting max drawdown to -14.5% vs -55.2% for SPY at a 0.78 Sharpe (SPY 0.64), net of 10 bps/side costs, with fills at the next open and a unit test that proves the signal has no look-ahead.
- Validated the strategy out-of-sample (2016-2026: Sharpe 0.96, max drawdown -12.0%) and across 36 rolling 3-year walk-forward windows (median Sharpe 0.70, 100% positive), and reported honestly that it beats SPY's Sharpe in only 36% of windows and trails SPY on CAGR (7.9% vs 11.0%).
- Shipped the paper-trading stack around it: Alpaca paper executor with market-on-open orders, idempotent daily runs, a JSON trade journal, and a risk manager (3% daily / 15% peak drawdown circuit breakers, 20% position and 100% gross caps, market-hours check), plus backtest diagnostics showing the position cap, not the vol target, sets size in 99.8% of position-months and that costs take 0.4%/yr off CAGR.

*Source: results/metrics.json, results/walk_forward.csv, results/sensitivity.csv.*
