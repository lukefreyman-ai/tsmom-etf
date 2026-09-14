"""Time-series momentum (12-1) with a 200-day SMA filter and per-position volatility scaling.

Every function is a pure transformation of price history: the value at row t uses closes up to and
including t, never after. `target_weights(close)` returns the weights that would be *decided* at the
close of t; the backtester applies them at the open of t+1.

Reference: Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", J. Financial Economics 104(2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import settings


def momentum_signal(close: pd.DataFrame, lookback_months: int = settings.MOM_LOOKBACK_MONTHS,
                    skip_months: int = settings.MOM_SKIP_MONTHS,
                    month_days: int = settings.MONTH_DAYS) -> pd.DataFrame:
    """Total return from t-lookback to t-skip (e.g. 12-1: months -12 .. -1). NaN until enough history."""
    lb, sk = lookback_months * month_days, skip_months * month_days
    return close.shift(sk) / close.shift(lb) - 1.0


def sma_filter(close: pd.DataFrame, window: int = settings.SMA_WINDOW) -> pd.DataFrame:
    """True where close is above its trailing simple moving average (needs `window` bars)."""
    sma = close.rolling(window, min_periods=window).mean()
    return (close > sma) & sma.notna()


def realized_vol(close: pd.DataFrame, window: int = settings.VOL_WINDOW,
                 trading_days: int = settings.TRADING_DAYS) -> pd.DataFrame:
    """Annualised standard deviation of daily log returns over the trailing window."""
    lr = np.log(close / close.shift(1))
    return lr.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(trading_days)


def long_signal(close: pd.DataFrame, lookback_months: int = settings.MOM_LOOKBACK_MONTHS,
                skip_months: int = settings.MOM_SKIP_MONTHS, sma_window: int = settings.SMA_WINDOW) -> pd.DataFrame:
    """1 where 12-1 momentum > 0 AND price > SMA, else 0. 0 (not NaN) where history is insufficient."""
    mom = momentum_signal(close, lookback_months, skip_months)
    on = (mom > 0) & sma_filter(close, sma_window) & close.notna()
    return on.astype(float)


def size_positions(signal: pd.DataFrame, vol: pd.DataFrame, vol_target: float = settings.VOL_TARGET,
                   max_weight: float = settings.MAX_POSITION_WEIGHT,
                   max_gross: float = settings.MAX_GROSS_EXPOSURE) -> pd.DataFrame:
    """Per-position vol scaling: w_i = vol_target / vol_i for assets with signal on, then two caps.

    1. each w_i <= max_weight
    2. sum(w) <= max_gross: if exceeded, all weights are scaled down proportionally
    Assets with no vol estimate yet get weight 0.
    """
    raw = (vol_target / vol).where(signal > 0, 0.0)
    raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    capped = raw.clip(upper=max_weight)
    gross = capped.sum(axis=1)
    scale = (max_gross / gross).where(gross > max_gross, 1.0)
    return capped.mul(scale, axis=0)


def target_weights(close: pd.DataFrame, lookback_months: int = settings.MOM_LOOKBACK_MONTHS,
                   skip_months: int = settings.MOM_SKIP_MONTHS, sma_window: int = settings.SMA_WINDOW,
                   vol_window: int = settings.VOL_WINDOW, vol_target: float = settings.VOL_TARGET,
                   max_weight: float = settings.MAX_POSITION_WEIGHT,
                   max_gross: float = settings.MAX_GROSS_EXPOSURE) -> pd.DataFrame:
    """Weights decided at each close using only data up to that close."""
    sig = long_signal(close, lookback_months, skip_months, sma_window)
    vol = realized_vol(close, vol_window)
    return size_positions(sig, vol, vol_target, max_weight, max_gross)


def rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First trading day of each month in the index (the day the trades happen)."""
    s = pd.Series(index, index=index)
    firsts = s.groupby([index.year, index.month]).first()
    return pd.DatetimeIndex(firsts.values)
