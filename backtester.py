"""Daily, share-based backtest engine with monthly rebalancing at the next open, plus metrics.

Timeline for one rebalance:
  signal date  s = last trading day of month M      -> weights decided from closes through s
  trade  date  d = first trading day of month M+1   -> fills at open[d], cost per side on traded value
Between rebalances, share counts are fixed; weights drift with prices. Cash earns 0.

Benchmarks (SPY buy-and-hold, 60/40 monthly) run through the same engine with constant target weights,
so they pay the same costs and are measured the same way.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import settings
import strategy


@dataclass
class BacktestResult:
    nav: pd.Series                       # daily portfolio value (close)
    weights: pd.DataFrame                # end-of-day weights (mark-to-market)
    trades: pd.DataFrame                 # one row per fill
    target_weights: pd.DataFrame         # decided weights at each rebalance signal date
    daily_returns: pd.Series = field(init=False)

    def __post_init__(self):
        self.daily_returns = self.nav.pct_change().fillna(0.0)


def run_backtest(prices: dict[str, pd.DataFrame], weights_fn=None, constant_weights: dict | None = None,
                 initial_capital: float = settings.INITIAL_CAPITAL, cost_per_side: float = settings.COST_PER_SIDE,
                 min_trade_weight: float = settings.MIN_TRADE_WEIGHT, start: str | None = None) -> BacktestResult:
    """weights_fn(close) -> DataFrame of decided weights (row t uses data <= t). Or constant_weights for benchmarks."""
    close, opn = prices["close"], prices["open"]
    tickers = list(close.columns)
    if constant_weights is not None:
        cw = pd.Series({t: constant_weights.get(t, 0.0) for t in tickers})
        decided = pd.DataFrame(np.tile(cw.values, (len(close), 1)), index=close.index, columns=tickers)
        decided = decided.where(close.notna(), 0.0)
    else:
        decided = (weights_fn or strategy.target_weights)(close)
    decided = decided.fillna(0.0)

    rebal = strategy.rebalance_dates(close.index)
    if start is not None:
        rebal = rebal[rebal >= pd.Timestamp(start)]
    pos = close.index.get_indexer(rebal)
    rebal = rebal[pos > 0]                                        # need a prior close for the signal
    rebal_set = set(rebal)

    shares = pd.Series(0.0, index=tickers)
    cash = float(initial_capital)
    nav, wts, trades, targets = [], [], [], {}
    idx = close.index
    for i, d in enumerate(idx):
        if d in rebal_set:
            s = idx[i - 1]
            w = decided.loc[s].copy()
            w[opn.loc[d].isna()] = 0.0                            # cannot trade what has no price today
            targets[s] = w
            px_open = opn.loc[d]
            nav_open = cash + float((shares * px_open.fillna(0.0)).sum())
            cur_w = (shares * px_open.fillna(0.0)) / nav_open
            for t in tickers:
                dw = w[t] - cur_w[t]
                if abs(dw) < min_trade_weight or np.isnan(px_open[t]):
                    continue
                target_shares = w[t] * nav_open / px_open[t]
                dq = target_shares - shares[t]
                value = dq * px_open[t]
                cost = abs(value) * cost_per_side
                cash -= value + cost
                shares[t] = target_shares if w[t] > 0 else 0.0
                trades.append({"date": d, "ticker": t, "side": "buy" if dq > 0 else "sell", "shares": dq,
                               "price": px_open[t], "value": value, "cost": cost,
                               "weight_before": cur_w[t], "weight_after": w[t]})
        px = close.loc[d].fillna(0.0)
        v = cash + float((shares * px).sum())
        nav.append(v)
        wts.append((shares * px) / v)
    nav = pd.Series(nav, index=idx, name="nav")
    wts = pd.DataFrame(wts, index=idx)
    tr = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["date", "ticker", "side", "shares", "price", "value", "cost", "weight_before", "weight_after"])
    tg = pd.DataFrame(targets).T if targets else pd.DataFrame(columns=tickers)
    return BacktestResult(nav=nav, weights=wts, trades=tr, target_weights=tg)


# ----------------------------------------------------------------------------- metrics

def _slice(s: pd.Series | pd.DataFrame, start=None, end=None):
    if start is not None:
        s = s[s.index >= pd.Timestamp(start)]
    if end is not None:
        s = s[s.index <= pd.Timestamp(end)]
    return s


def drawdown_series(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def max_drawdown_duration_days(nav: pd.Series) -> int:
    """Longest stretch (calendar days) between a peak and the recovery to that peak."""
    peak = nav.cummax()
    under = nav < peak
    longest, run_start = 0, None
    for d, u in under.items():
        if u and run_start is None:
            run_start = d
        elif not u and run_start is not None:
            longest = max(longest, (d - run_start).days); run_start = None
    if run_start is not None:
        longest = max(longest, (nav.index[-1] - run_start).days)
    return int(longest)


def compute_metrics(res: BacktestResult, start=None, end=None, rf: float = settings.RISK_FREE_RATE,
                    trading_days: int = settings.TRADING_DAYS) -> dict:
    nav = _slice(res.nav, start, end)
    if len(nav) < 2:
        return {}
    nav = nav / nav.iloc[0]
    r = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(trading_days)
    ex = r - rf / trading_days
    sharpe = ex.mean() / r.std(ddof=1) * np.sqrt(trading_days) if r.std() > 0 else np.nan
    down = ex[ex < 0]
    dd_dev = np.sqrt((down ** 2).sum() / len(ex)) * np.sqrt(trading_days) if len(ex) else np.nan
    sortino = ex.mean() * trading_days / dd_dev if dd_dev and dd_dev > 0 else np.nan
    dd = drawdown_series(nav)
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    w = _slice(res.weights, start, end)
    gross = w.sum(axis=1)
    tr = res.trades[(res.trades["date"] >= nav.index[0]) & (res.trades["date"] <= nav.index[-1])] if len(res.trades) else res.trades
    # turnover: one-way traded value / average NAV, annualised
    nav_raw = _slice(res.nav, start, end)
    turnover = (tr["value"].abs().sum() / 2 / nav_raw.mean() / years) if years > 0 and len(tr) else 0.0
    return {
        "start": str(nav.index[0].date()), "end": str(nav.index[-1].date()), "years": round(years, 2),
        "total_return": nav.iloc[-1] - 1, "cagr": cagr, "ann_vol": vol, "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": mdd, "max_dd_duration_days": max_drawdown_duration_days(nav), "calmar": calmar,
        "n_trades": int(len(tr)), "avg_holding_period_days": avg_holding_period_days(res, start, end),
        "time_in_market": float((gross > 0.001).mean()), "avg_gross_exposure": float(gross.mean()),
        "annual_turnover": float(turnover), "total_costs_pct_of_initial": float(tr["cost"].sum() / res.nav.iloc[0]) if len(tr) else 0.0,
        "best_month": monthly_returns(res, start, end).max(), "worst_month": monthly_returns(res, start, end).min(),
    }


def avg_holding_period_days(res: BacktestResult, start=None, end=None) -> float:
    """Average calendar days a ticker is held continuously (entry -> flat), over completed and open holds."""
    w = _slice(res.weights, start, end)
    held = w > 1e-6
    durations = []
    for t in held.columns:
        h = held[t]
        run_start = None
        for d, on in h.items():
            if on and run_start is None:
                run_start = d
            elif not on and run_start is not None:
                durations.append((d - run_start).days); run_start = None
        if run_start is not None:
            durations.append((h.index[-1] - run_start).days)
    return float(np.mean(durations)) if durations else 0.0


def monthly_returns(res: BacktestResult, start=None, end=None) -> pd.Series:
    nav = _slice(res.nav, start, end)
    m = nav.resample("ME").last()
    first = nav.iloc[0]
    return (m / m.shift(1).fillna(first) - 1.0).rename("monthly_return")


def monthly_table(res: BacktestResult, start=None, end=None) -> pd.DataFrame:
    m = monthly_returns(res, start, end)
    tbl = pd.DataFrame({"year": m.index.year, "month": m.index.month, "ret": m.values})
    piv = tbl.pivot(index="year", columns="month", values="ret")
    piv.columns = [pd.Timestamp(2000, c, 1).strftime("%b") for c in piv.columns]
    yearly = _slice(res.nav, start, end).resample("YE").last()
    yr = (yearly / yearly.shift(1).fillna(_slice(res.nav, start, end).iloc[0]) - 1.0)
    piv["Year"] = pd.Series(yr.values, index=yr.index.year)
    return piv


def rolling_sharpe(res: BacktestResult, years: int = settings.WALK_FORWARD_YEARS,
                   step_months: int = settings.WALK_FORWARD_STEP_MONTHS, start=None) -> pd.DataFrame:
    """Sharpe (and CAGR, max DD) in rolling `years`-year windows stepped every `step_months` months."""
    nav = _slice(res.nav, start)
    rows = []
    ws = nav.index[0]
    while True:
        we = ws + pd.DateOffset(years=years) - pd.Timedelta(days=1)
        if we > nav.index[-1]:
            break
        m = compute_metrics(res, ws, we)
        rows.append({"window_start": str(ws.date()), "window_end": str(we.date()), "sharpe": m["sharpe"],
                     "cagr": m["cagr"], "max_drawdown": m["max_drawdown"], "ann_vol": m["ann_vol"]})
        ws = ws + pd.DateOffset(months=step_months)
    return pd.DataFrame(rows)


def to_jsonable(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, float)):
            out[k] = None if np.isnan(v) else float(v)
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        else:
            out[k] = v
    return out
