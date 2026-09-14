import numpy as np
import pandas as pd
import pytest

import backtester
import data_loader
import strategy


def _prices(n=800):
    return data_loader.synthetic_prices(n_days=n, tickers=["A", "B", "C"], seed=2)


def test_fills_happen_at_next_open_after_signal():
    px = _prices()
    res = backtester.run_backtest(px, cost_per_side=0.0)
    assert len(res.trades) > 0
    tr = res.trades.iloc[0]
    d = tr["date"]
    assert d in set(strategy.rebalance_dates(px["close"].index))
    assert tr["price"] == pytest.approx(px["open"].loc[d, tr["ticker"]])
    # the target that produced the fill was decided at the prior close
    s = px["close"].index[px["close"].index.get_loc(d) - 1]
    assert s in res.target_weights.index


def test_no_lookahead_in_backtest_nav():
    """NAV through t is identical whether or not prices after t are tampered with."""
    px = _prices()
    t = 600
    base = backtester.run_backtest(px)
    tam = {f: v.copy() for f, v in px.items()}
    for f in tam:
        tam[f].iloc[t + 1:] *= 0.5
    alt = backtester.run_backtest(tam)
    pd.testing.assert_series_equal(base.nav.iloc[: t + 1], alt.nav.iloc[: t + 1])


def test_costs_reduce_nav_and_are_recorded():
    px = _prices()
    free = backtester.run_backtest(px, cost_per_side=0.0)
    paid = backtester.run_backtest(px, cost_per_side=0.001)
    assert paid.nav.iloc[-1] < free.nav.iloc[-1]
    assert paid.trades["cost"].sum() == pytest.approx(paid.trades["value"].abs().sum() * 0.001)
    assert free.trades["cost"].sum() == 0.0


def test_constant_weights_benchmark_holds_target():
    px = _prices()
    res = backtester.run_backtest(px, constant_weights={"A": 0.6, "B": 0.4}, cost_per_side=0.0)
    rb = strategy.rebalance_dates(px["close"].index)[1:]
    # right after each rebalance the weights are near target (drift only from open->close that day)
    w = res.weights.loc[rb]
    assert (w["A"] - 0.6).abs().max() < 0.03
    assert (w["C"] == 0).all()


def test_exposure_never_exceeds_caps():
    px = _prices()
    res = backtester.run_backtest(px)
    assert res.weights.sum(axis=1).max() <= 1.0 + 0.05      # mark-to-market drift allowed, no leverage
    assert (res.target_weights.max(axis=1) <= 0.20 + 1e-9).all()
    assert (res.target_weights.sum(axis=1) <= 1.0 + 1e-9).all()


def test_metrics_basic_sanity():
    idx = pd.bdate_range("2020-01-01", periods=504)
    nav = pd.Series(100 * (1.0004 ** np.arange(504)), index=idx)      # smooth 10%/yr
    res = backtester.BacktestResult(nav=nav, weights=pd.DataFrame(1.0, index=idx, columns=["A"]),
                                    trades=pd.DataFrame(columns=["date", "value", "cost"]), target_weights=pd.DataFrame())
    m = backtester.compute_metrics(res)
    years = (idx[-1] - idx[0]).days / 365.25
    assert m["cagr"] == pytest.approx((1.0004 ** 503) ** (1 / years) - 1, rel=1e-6)   # CAGR uses calendar time
    assert m["max_drawdown"] == 0.0
    assert m["time_in_market"] == 1.0
    dd = backtester.max_drawdown_duration_days(pd.Series([1, 2, 1, 1.5, 2, 3], index=pd.date_range("2020-01-01", periods=6)))
    assert dd == 2          # under water on day 2 and 3, back at the peak on day 4
