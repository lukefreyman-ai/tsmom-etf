"""All tunable parameters in one place. Every number here is quoted in the README.

Nothing else in the project hardcodes a lookback, cost, or limit; change it here and rerun
`make backtest` to regenerate results/ and the README tables.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

# ----------------------------------------------------------------------------- universe
UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
BENCHMARK_SPY = "SPY"
BENCHMARK_6040 = {"SPY": 0.60, "IEF": 0.40}   # rebalanced monthly, same costs as the strategy

# ----------------------------------------------------------------------------- data
DATA_START = "2005-01-01"        # DBC only lists from 2006-02; it enters the universe once it has enough history
TRADING_DAYS = 252
MONTH_DAYS = 21                  # trading days per "month" used by the momentum lookback

# ----------------------------------------------------------------------------- signal
MOM_LOOKBACK_MONTHS = 12         # 12-1 momentum: return over the last 12 months ...
MOM_SKIP_MONTHS = 1              # ... excluding the most recent month (short-term reversal)
SMA_WINDOW = 200                 # confirmation filter: price must be above its 200-day SMA
MIN_HISTORY_DAYS = MOM_LOOKBACK_MONTHS * MONTH_DAYS + 5   # bars required before an ETF can get a signal

# ----------------------------------------------------------------------------- sizing
SIZING = "portfolio"             # "portfolio": gross exposure scaled so trailing portfolio vol ~ VOL_TARGET (v2, current)
                                 # "per_position": each position scaled to VOL_TARGET stand-alone (v1, kept for the ablation)
VOL_TARGET = 0.10                # annualised vol target (portfolio-level under SIZING="portfolio")
VOL_WINDOW = 60                  # trailing window of daily log returns for the vol / covariance estimate
MAX_POSITION_WEIGHT = 0.20       # hard cap on any single ETF (applied after vol scaling; no redistribution)
MAX_GROSS_EXPOSURE = 1.00        # long-only, no leverage: sum of weights <= 100%

# ----------------------------------------------------------------------------- rebalance
REBALANCE = "monthly"            # first trading day of each month; signal from the prior close, fill at the open
REBALANCE_BAND = 0.02            # skip a trade when |target - current weight| < 2pp; full entries and exits always trade

# ----------------------------------------------------------------------------- costs (per side)
COMMISSION_BPS = 5.0             # 5 bps per side commission ...
SLIPPAGE_BPS = 5.0               # ... plus 5 bps per side slippage = 10 bps round-trip-per-side total
COST_PER_SIDE = (COMMISSION_BPS + SLIPPAGE_BPS) / 1e4

# ----------------------------------------------------------------------------- validation
IN_SAMPLE = ("2005-01-01", "2015-12-31")
OUT_OF_SAMPLE = ("2016-01-01", None)      # None = through the last cached bar
WALK_FORWARD_YEARS = 3
WALK_FORWARD_STEP_MONTHS = 6
RISK_FREE_RATE = 0.0             # Sharpe/Sortino use excess return over this (0 = raw; stated in README)
INITIAL_CAPITAL = 100_000.0

# sensitivity grid (README "Sensitivity" table)
SENS_LOOKBACKS = [6, 9, 12]
SENS_VOL_TARGETS = [0.08, 0.10, 0.12]

# ----------------------------------------------------------------------------- risk manager (live / paper)
# Circuit breakers. When tripped: cancel open orders, do NOT flatten, log, and refuse new orders until
# CIRCUIT_BREAKER_RESET below is flipped to True by a human (then set it back to False).
MAX_DAILY_DRAWDOWN = 0.03        # halt if today's portfolio value is down more than 3% from yesterday's close
MAX_PEAK_DRAWDOWN = 0.15         # halt if portfolio value is more than 15% below its high-water mark
CIRCUIT_BREAKER_RESET = False    # manual reset flag: set True once, run `python run.py status`, set back to False
# Pre-trade order checks (same limits as the backtest, enforced again on every live order)
LIVE_MAX_POSITION_WEIGHT = MAX_POSITION_WEIGHT
LIVE_MAX_GROSS_EXPOSURE = MAX_GROSS_EXPOSURE
MARKET_TZ = "America/New_York"
MARKET_OPEN = "09:30"
MARKET_CLOSE = "16:00"
# Market-on-open (opg) orders must reach Alpaca BEFORE 09:28 ET to join the opening auction. The pre-open window
# below is the only exception to "regular hours only": orders submitted in it are tagged opg and fill at the open.
# Set ALLOW_PREOPEN_MOO = False to forbid it (then run the executor after 09:30 and it uses plain market orders).
ALLOW_PREOPEN_MOO = True
MOO_WINDOW = ("07:00", "09:28")

# ----------------------------------------------------------------------------- execution (Alpaca PAPER only)
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
TRADE_JOURNAL = RESULTS_DIR / "trade_journal.json"
STATE_FILE = RESULTS_DIR / "live_state.json"     # high-water mark, last rebalance date, breaker status
