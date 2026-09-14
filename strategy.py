"""Time-series momentum (12-1) with a 200-day SMA filter and portfolio-level volatility targeting.

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


def size_positions_portfolio(signal: pd.DataFrame, close: pd.DataFrame, vol: pd.DataFrame,
                             vol_target: float = settings.VOL_TARGET, vol_window: int = settings.VOL_WINDOW,
                             max_weight: float = settings.MAX_POSITION_WEIGHT,
                             max_gross: float = settings.MAX_GROSS_EXPOSURE,
                             trading_days: int = settings.TRADING_DAYS) -> pd.DataFrame:
    """Portfolio-level vol targeting (v2).

    1. base weights: inverse-vol among assets with signal on, normalised to sum to 1
    2. trailing portfolio vol of those base weights: std of (base . daily log returns) over the last `vol_window`
       days, annualised. This equals sqrt(b' Sigma b) with the sample covariance of the window.
    3. gross exposure G = min(max_gross, vol_target / portfolio_vol); weights = G x base
    4. single-name cap: w_i = min(w_i, max_weight), with no redistribution (gross can end below G)
    Row t uses only data through t.
    """
    lr = np.log(close / close.shift(1)).to_numpy()
    sig = (signal.to_numpy() > 0) & np.isfinite(vol.to_numpy())
    inv = np.where(sig, 1.0 / vol.to_numpy(), 0.0)
    inv = np.nan_to_num(inv, nan=0.0, posinf=0.0, neginf=0.0)
    ssum = inv.sum(axis=1, keepdims=True)
    base = np.divide(inv, ssum, out=np.zeros_like(inv), where=ssum > 0)
    n, k = base.shape
    out = np.zeros_like(base)
    for t in range(n):
        b = base[t]
        if not b.any() or t + 1 < vol_window:
            continue
        held = b > 0
        window = lr[t + 1 - vol_window: t + 1][:, held]           # rows t-59 .. t inclusive, held assets only
        if not np.isfinite(window).all():
            continue                                               # a held asset lacks 60 days of returns (cannot happen: vol needs 60)
        pr = window @ b[held]
        pvol = pr.std(ddof=1) * np.sqrt(trading_days)
        g = min(max_gross, vol_target / pvol) if pvol > 0 else max_gross
        out[t] = np.minimum(g * b, max_weight)
    return pd.DataFrame(out, index=signal.index, columns=signal.columns)


def size_positions_per_asset(signal: pd.DataFrame, vol: pd.DataFrame, vol_target: float = settings.VOL_TARGET,
                             max_weight: float = settings.MAX_POSITION_WEIGHT,
                             max_gross: float = settings.MAX_GROSS_EXPOSURE) -> pd.DataFrame:
    """v1 sizing, kept for the ablation table. Per-position vol scaling: w_i = vol_target / vol_i, then two caps.

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
                   max_gross: float = settings.MAX_GROSS_EXPOSURE, sizing: str | None = None) -> pd.DataFrame:
    """Weights decided at each close using only data up to that close."""
    sizing = sizing or settings.SIZING
    sig = long_signal(close, lookback_months, skip_months, sma_window)
    vol = realized_vol(close, vol_window)
    if sizing == "per_position":
        return size_positions_per_asset(sig, vol, vol_target, max_weight, max_gross)
    if sizing == "portfolio":
        return size_positions_portfolio(sig, close, vol, vol_target, vol_window, max_weight, max_gross)
    raise ValueError(f"unknown sizing {sizing!r}")


def rebalance_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """First trading day of each month in the index (the day the trades happen)."""
    s = pd.Series(index, index=index)
    firsts = s.groupby([index.year, index.month]).first()
    return pd.DatetimeIndex(firsts.values)
