"""Daily adjusted OHLCV from yfinance, cached as CSV in data/.

`load_prices()` returns a dict of wide DataFrames keyed by field
("open", "high", "low", "close", "volume"), each indexed by date with one column per ticker.
Prices are split- AND dividend-adjusted (yfinance auto_adjust=True), so close-to-close returns are
total returns and "open" is on the same adjusted basis as "close" (needed for fills at the next open).

The cache is committed to the repo so `make backtest` reproduces the README numbers from a clean
clone without touching the network. `--refresh` (or refresh=True) re-downloads everything.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import settings

FIELDS = ["open", "high", "low", "close", "volume"]
MANIFEST = settings.DATA_DIR / "manifest.json"


def _cache_path(ticker: str) -> Path:
    return settings.DATA_DIR / f"{ticker}.csv"


def _download_one(ticker: str, start: str) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so tests / backtests never need the network

    raw = yf.download(ticker, start=start, auto_adjust=True, progress=False, threads=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    if isinstance(raw.columns, pd.MultiIndex):          # yfinance >= 0.2.5 returns (field, ticker)
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[FIELDS].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["close"])
    return df.astype(float)


def _validate(ticker: str, df: pd.DataFrame) -> None:
    if df.index.has_duplicates:
        raise ValueError(f"{ticker}: duplicate dates in cache")
    if not df.index.is_monotonic_increasing:
        raise ValueError(f"{ticker}: dates not sorted")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{ticker}: non-positive prices")
    if (df["high"] < df["low"]).any():
        raise ValueError(f"{ticker}: high < low")
    # a 60%+ one-day move in a broad ETF is a data error, not a market event
    r = df["close"].pct_change().abs()
    if (r > 0.6).any():
        bad = df.index[r > 0.6][0].date()
        raise ValueError(f"{ticker}: implausible daily move on {bad}; refresh the cache")


def download_all(tickers=None, start: str | None = None) -> None:
    tickers = list(tickers or settings.UNIVERSE)
    start = start or settings.DATA_START
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"downloaded_at": datetime.now().isoformat(timespec="seconds"), "start": start, "tickers": {}}
    for t in tickers:
        df = _download_one(t, start)
        _validate(t, df)
        df.to_csv(_cache_path(t), float_format="%.6f")
        manifest["tickers"][t] = {"first": str(df.index[0].date()), "last": str(df.index[-1].date()), "rows": len(df)}
        print(f"  {t}: {len(df)} rows {df.index[0].date()} .. {df.index[-1].date()}")
    MANIFEST.write_text(json.dumps(manifest, indent=2))


def load_prices(tickers=None, refresh: bool = False, start: str | None = None,
                end: str | None = None) -> dict[str, pd.DataFrame]:
    """Return {field: DataFrame(date x ticker)}. Missing tickers are downloaded; refresh=True re-downloads all."""
    tickers = list(tickers or settings.UNIVERSE)
    missing = [t for t in tickers if not _cache_path(t).exists()]
    if refresh or missing:
        download_all(tickers if refresh else missing, start=start)
    frames = {}
    for t in tickers:
        df = pd.read_csv(_cache_path(t), index_col="date", parse_dates=True)
        _validate(t, df)
        frames[t] = df
    out = {}
    for f in FIELDS:
        wide = pd.concat({t: frames[t][f] for t in tickers}, axis=1).sort_index()
        wide.columns.name = "ticker"
        out[f] = wide
    idx = out["close"].index
    if start:
        idx = idx[idx >= pd.Timestamp(start)]
    if end:
        idx = idx[idx <= pd.Timestamp(end)]
    return {f: v.loc[idx] for f, v in out.items()}


def manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def synthetic_prices(n_days: int = 1500, tickers=None, seed: int = 0, start: str = "2010-01-01") -> dict[str, pd.DataFrame]:
    """Deterministic fake OHLCV for unit tests (geometric random walk with a drift per ticker)."""
    tickers = list(tickers or settings.UNIVERSE)
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days)
    out = {f: pd.DataFrame(index=idx, columns=tickers, dtype=float) for f in FIELDS}
    for i, t in enumerate(tickers):
        drift = 0.0002 * (i % 3)                      # some trend, some flat
        lr = rng.normal(drift, 0.01, n_days)
        close = 100.0 * np.exp(np.cumsum(lr))
        opn = close * np.exp(rng.normal(0, 0.002, n_days))
        out["close"][t] = close
        out["open"][t] = opn
        out["high"][t] = np.maximum(close, opn) * 1.003
        out["low"][t] = np.minimum(close, opn) * 0.997
        out["volume"][t] = 1e6
    for f in FIELDS:
        out[f].index.name = "date"
        out[f].columns.name = "ticker"
    return out


if __name__ == "__main__":
    import sys
    download_all() if "--refresh" in sys.argv else print(json.dumps(manifest(), indent=2))
