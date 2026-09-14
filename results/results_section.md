<!-- results:start -->
_Generated 2026-09-14 from `results/metrics.json`, data through 2026-09-14. Strategy is active from 2006-02-01 (first date with 12 months of history + a 200-day SMA)._

### Key findings

- **Return:** the strategy compounds at 6.4% a year over the full period versus 11.0% for SPY and 8.2% for 60/40. It does **not** beat buy-and-hold SPY on return.
- **Risk:** its worst drawdown is -11.6% against -55.2% for SPY and -32.3% for 60/40, at 8.3% annualised vol. The edge is drawdown control, not return.
- **Risk-adjusted:** full-period Sharpe 0.78 (SPY 0.64, 60/40 0.78); Calmar 0.55 vs 0.20 / 0.25.
- **In-sample vs out-of-sample:** Sharpe 0.66 in-sample and 0.91 out-of-sample. Out-of-sample is *better*, which says more about 2016-2026 (a long trending bull market with two sharp, momentum-friendly sell-offs) than about the strategy. SPY's own Sharpe rose from 0.43 to 0.88 over the same split.
- **Walk-forward:** across 36 rolling 3-year windows the Sharpe ranges 0.31 to 1.32 (median 0.69); 100% of windows are positive but the strategy beats SPY's Sharpe in only 31% of them.
- **Sensitivity:** full-period Sharpe across the 3x3 grid spans 0.71 to 0.80; longer lookbacks are monotonically better and the vol target changes almost nothing. Results are not fragile, but 12 months (the literature default) is also the best cell, so treat the point estimate as optimistic.
- **What sets the size:** under portfolio-level vol targeting the 10% target is the binding constraint in 18% of active months, the 20% single-name cap in 77%, and the strategy is fully invested in 5%. Average gross exposure when active is 76% (minimum 20%); all cash 7% of months; average 5.4 positions on.
- **Costs:** 10 bps per side on 1.46x annual one-way turnover costs 0.3% of CAGR a year (6.7% gross to 6.4% net).
- **Design changes (ablation table below):** replacing per-position vol scaling with portfolio-level vol targeting moved full-period Sharpe from 0.78 to 0.78, vol from 10.5% to 8.3%, max drawdown from -14.5% to -11.6% and average gross exposure from 85% to 74%. Adding a 2pp rebalance band on top cut annual turnover from 1.58x to 1.46x and cost drag from 0.3% to 0.3% of CAGR a year, at a Sharpe of 0.78.

### In-sample (2005-2015)

Period: 2006-02-01 to 2015-12-31 (9.91 years)

| metric | Strategy | SPY B&H | 60/40 |
|---|---|---|---|
| CAGR | 5.4% | 7.0% | 6.9% |
| Annualised vol | 8.5% | 20.8% | 11.2% |
| Sharpe (rf=0) | 0.66 | 0.43 | 0.65 |
| Sortino | 0.93 | 0.61 | 0.93 |
| Max drawdown | -10.6% | -55.2% | -32.3% |
| Max DD duration (days) | 659 | 1772 | 1091 |
| Calmar | 0.51 | 0.13 | 0.21 |
| Trades | 373 | 0 | 46 |
| Avg holding period (days) | 270 | 3620 | 3620 |
| Time in market | 100.0% | 100.0% | 100.0% |
| Avg gross exposure | 75.8% | 100.1% | 100.0% |
| Annual one-way turnover | 1.37x | 0.00x | 0.06x |
| Best month | 4.7% | 10.9% | 6.5% |
| Worst month | -5.9% | -16.5% | -10.3% |

### Out-of-sample (2016-present)

Period: 2016-01-04 to 2026-09-14 (10.69 years)

| metric | Strategy | SPY B&H | 60/40 |
|---|---|---|---|
| CAGR | 7.3% | 15.1% | 9.6% |
| Annualised vol | 8.1% | 17.7% | 10.5% |
| Sharpe (rf=0) | 0.91 | 0.88 | 0.92 |
| Sortino | 1.26 | 1.25 | 1.31 |
| Max drawdown | -11.6% | -33.7% | -21.2% |
| Max DD duration (days) | 798 | 708 | 786 |
| Calmar | 0.63 | 0.45 | 0.45 |
| Trades | 412 | 0 | 46 |
| Avg holding period (days) | 233 | 3906 | 3906 |
| Time in market | 94.7% | 100.0% | 100.0% |
| Avg gross exposure | 73.0% | 100.0% | 100.0% |
| Annual one-way turnover | 1.51x | 0.00x | 0.06x |
| Best month | 5.4% | 12.7% | 8.1% |
| Worst month | -6.3% | -12.5% | -7.5% |

### Full period

Period: 2006-02-01 to 2026-09-14 (20.62 years)

| metric | Strategy | SPY B&H | 60/40 |
|---|---|---|---|
| CAGR | 6.4% | 11.0% | 8.2% |
| Annualised vol | 8.3% | 19.3% | 10.8% |
| Sharpe (rf=0) | 0.78 | 0.64 | 0.78 |
| Sortino | 1.09 | 0.91 | 1.12 |
| Max drawdown | -11.6% | -55.2% | -32.3% |
| Max DD duration (days) | 798 | 1772 | 1091 |
| Calmar | 0.55 | 0.20 | 0.25 |
| Trades | 785 | 0 | 92 |
| Avg holding period (days) | 253 | 7530 | 7530 |
| Time in market | 97.2% | 100.0% | 100.0% |
| Avg gross exposure | 74.4% | 100.1% | 100.0% |
| Annual one-way turnover | 1.46x | 0.00x | 0.06x |
| Best month | 5.4% | 12.7% | 8.1% |
| Worst month | -6.3% | -16.5% | -10.3% |

### Walk-forward: rolling 3-year windows

36 rolling 3-year windows, stepped every 6 months.

| statistic | value |
|---|---|
| Sharpe: min / 25th pct / median / 75th pct / max | 0.31 / 0.58 / 0.69 / 0.85 / 1.32 |
| Windows with positive Sharpe | 100% |
| Windows where strategy Sharpe > SPY Sharpe | 31% |
| Worst window max drawdown | -11.6% |

### Sensitivity grid

**Sharpe, full period** (rows: momentum lookback in months; columns: vol target)

| lookback | 8% | 10% | 12% |
|---|---|---|---|
| 6 | 0.73 | 0.71 | 0.72 |
| 9 | 0.78 | 0.78 | 0.80 |
| 12 | 0.79 | 0.78 | 0.80 |

**Sharpe, out-of-sample** (rows: momentum lookback in months; columns: vol target)

| lookback | 8% | 10% | 12% |
|---|---|---|---|
| 6 | 0.81 | 0.84 | 0.89 |
| 9 | 0.96 | 1.02 | 1.05 |
| 12 | 0.88 | 0.91 | 0.92 |

**Max drawdown, full period** (rows: momentum lookback in months; columns: vol target)

| lookback | 8% | 10% | 12% |
|---|---|---|---|
| 6 | -12.5% | -14.1% | -14.3% |
| 9 | -12.6% | -14.1% | -14.1% |
| 12 | -10.9% | -11.6% | -11.4% |

**CAGR, full period** (rows: momentum lookback in months; columns: vol target)

| lookback | 8% | 10% | 12% |
|---|---|---|---|
| 6 | 5.4% | 5.8% | 6.2% |
| 9 | 5.7% | 6.4% | 6.9% |
| 12 | 5.9% | 6.4% | 6.8% |

### Ablation: sizing rule and rebalance band

Full period, same data and costs; only the sizing rule and the rebalance band change.

| config | CAGR | vol | Sharpe | max DD | OOS Sharpe | avg gross | trades | turnover | cost drag |
|---|---|---|---|---|---|---|---|---|---|
| v1 per-position vol, 0.5% dust filter (original) | 7.9% | 10.5% | 0.78 | -14.5% | 0.96 | 85% | 1138 | 1.73x | 0.4%/yr |
| v1 per-position vol + 2pp band | 8.2% | 10.5% | 0.80 | -14.4% | 1.00 | 85% | 792 | 1.63x | 0.3%/yr |
| v2 portfolio vol, 0.5% dust filter | 6.4% | 8.3% | 0.78 | -11.6% | 0.90 | 74% | 1239 | 1.58x | 0.3%/yr |
| v2 portfolio vol + 2pp band (current) | 6.4% | 8.3% | 0.78 | -11.6% | 0.91 | 74% | 785 | 1.46x | 0.3%/yr |

### Monthly returns (strategy, %)

| year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Year |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2006 |  | -0.8 | +1.8 | +1.6 | -4.1 | +0.3 | +0.8 | +1.0 | +0.4 | +2.8 | +2.9 | -0.1 | +6.6 |
| 2007 | +1.2 | +0.1 | +0.9 | +1.8 | +0.5 | -1.0 | -1.4 | +0.9 | +4.4 | +4.4 | -0.9 | +0.7 | +12.0 |
| 2008 | +0.1 | +3.1 | -0.7 | -0.9 | +0.5 | +1.2 | -1.8 | -1.1 | -1.6 | -0.7 | +4.7 | +3.9 | +6.7 |
| 2009 | -3.7 | -0.5 | +1.5 | -2.6 | +1.5 | -1.4 | +0.5 | +0.0 | +1.2 | -0.4 | +4.3 | +1.1 | +1.4 |
| 2010 | -3.0 | +1.8 | +3.4 | +1.6 | -4.4 | -0.3 | -0.3 | +1.2 | +1.3 | +2.0 | -0.5 | +3.0 | +5.7 |
| 2011 | +0.1 | +2.8 | +0.6 | +3.9 | -1.5 | -2.1 | +1.5 | -1.2 | -5.9 | -0.5 | +0.6 | -0.9 | -3.0 |
| 2012 | +1.7 | +0.1 | +0.9 | +1.2 | -1.2 | +2.2 | +1.5 | +1.1 | +0.1 | -1.8 | +0.5 | +1.1 | +7.7 |
| 2013 | +1.8 | -0.0 | +1.5 | +2.4 | -1.9 | -1.7 | +3.4 | -2.1 | +3.8 | +3.0 | +1.0 | +1.8 | +13.5 |
| 2014 | -2.8 | +4.0 | -0.6 | +0.4 | +1.6 | +2.1 | -1.3 | +2.7 | -3.2 | +2.6 | +1.8 | +0.8 | +8.1 |
| 2015 | +2.4 | +0.4 | +0.2 | -0.8 | +0.5 | -1.5 | +1.1 | -3.9 | -1.0 | -0.1 | -0.2 | -0.4 | -3.5 |
| 2016 | -2.2 | -0.2 | -0.1 | +0.3 | -0.0 | +4.3 | +2.7 | -1.3 | +0.2 | -2.5 | +0.1 | +1.3 | +2.4 |
| 2017 | +2.1 | +2.1 | +0.8 | +1.1 | +1.6 | +0.3 | +2.5 | +0.6 | +2.1 | +2.0 | +1.8 | +1.2 | +19.8 |
| 2018 | +3.2 | -3.5 | -0.1 | +0.5 | +0.9 | -0.1 | +1.2 | +2.5 | -0.7 | -6.3 | +1.1 | -2.0 | -3.6 |
| 2019 | -0.3 | -0.4 | +2.2 | +0.3 | -1.1 | +1.6 | +0.7 | +3.7 | -0.5 | +1.1 | -0.1 | +2.1 | +9.7 |
| 2020 | +0.3 | -3.1 | +1.0 | +1.3 | +1.0 | +1.1 | +3.6 | +0.6 | -1.1 | -1.2 | +2.5 | +2.5 | +8.7 |
| 2021 | -0.2 | +1.6 | +1.2 | +3.4 | +1.0 | +0.4 | +0.4 | +1.7 | -3.3 | +5.4 | -2.8 | +4.4 | +13.6 |
| 2022 | -3.3 | +0.2 | +2.0 | -2.4 | +0.0 | -1.4 | -0.4 | -0.2 | -1.4 | +0.4 | +0.0 | +0.0 | -6.4 |
| 2023 | +0.0 | -1.1 | +1.5 | +0.1 | -1.3 | +2.9 | +3.2 | -2.9 | -4.0 | -1.6 | +2.9 | +3.4 | +2.7 |
| 2024 | -1.0 | +2.2 | +3.1 | -2.8 | +3.3 | +1.4 | +2.4 | +1.7 | +2.2 | -2.2 | +1.9 | -3.4 | +8.8 |
| 2025 | +2.5 | +0.4 | +0.3 | -0.3 | +1.0 | +2.2 | +0.2 | +2.0 | +3.9 | +2.3 | +0.6 | +0.0 | +16.0 |
| 2026 | +3.5 | +2.5 | -3.3 | +3.6 | +1.6 | -1.1 | +0.3 | +1.7 | -0.4 |  |  |  | +8.6 |

![equity curve](results/equity_curve.png)
<!-- results:end -->