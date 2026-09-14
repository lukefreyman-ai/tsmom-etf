import numpy as np
import pandas as pd
import pytest

import data_loader
import strategy
import settings


def _close(n=600, tickers=("A", "B", "C")):
    return data_loader.synthetic_prices(n_days=n, tickers=list(tickers), seed=1)["close"]


def test_momentum_signal_matches_hand_calculation():
    close = _close()
    mom = strategy.momentum_signal(close, lookback_months=12, skip_months=1)
    t = 400
    expected = close.iloc[t - 21]["A"] / close.iloc[t - 252]["A"] - 1
    assert mom.iloc[t]["A"] == pytest.approx(expected)
    assert mom.iloc[:252].isna().all().all()          # no signal without 12 months of history
    assert mom.iloc[252].notna().all()


def test_momentum_skips_last_month():
    """A huge rally in the last 21 days must not change the 12-1 signal."""
    close = _close()
    boosted = close.copy()
    boosted.iloc[-20:] *= 5.0
    a = strategy.momentum_signal(close).iloc[-1]
    b = strategy.momentum_signal(boosted).iloc[-1]
    pd.testing.assert_series_equal(a, b)


def test_sma_filter():
    idx = pd.bdate_range("2020-01-01", periods=300)
    up = pd.DataFrame({"X": np.linspace(100, 200, 300)}, index=idx)      # rising: above SMA once defined
    down = pd.DataFrame({"X": np.linspace(200, 100, 300)}, index=idx)
    assert strategy.sma_filter(up, 200).iloc[-1]["X"]
    assert not strategy.sma_filter(down, 200).iloc[-1]["X"]
    assert not strategy.sma_filter(up, 200).iloc[:199]["X"].any()        # undefined -> False, never True


def test_realized_vol_annualised():
    idx = pd.bdate_range("2020-01-01", periods=500)
    rng = np.random.default_rng(0)
    lr = rng.normal(0, 0.01, 500)
    close = pd.DataFrame({"X": 100 * np.exp(np.cumsum(lr))}, index=idx)
    v = strategy.realized_vol(close, window=60)
    assert v.iloc[:60].isna().all().all()
    assert v.iloc[-1]["X"] == pytest.approx(np.std(lr[-60:], ddof=1) * np.sqrt(252))


def test_per_asset_sizing_caps_and_scaling():   # v1 sizing, kept for the ablation
    idx = pd.bdate_range("2020-01-01", periods=3)
    cols = list("ABCDEFG")
    sig = pd.DataFrame(1.0, index=idx, columns=cols)
    vol = pd.DataFrame(0.10, index=idx, columns=cols)            # raw weight = 0.10/0.10 = 1.0 each
    w = strategy.size_positions_per_asset(sig, vol, vol_target=0.10, max_weight=0.20, max_gross=1.0)
    np.testing.assert_allclose(w.iloc[0].values, 1.0 / 7)       # 7 x 0.20 = 1.4 > 1.0 -> scaled to 1/7 each
    assert w.sum(axis=1).iloc[0] == pytest.approx(1.0)
    # high vol shrinks the position below the cap; zero signal -> zero weight
    vol.loc[:, "A"] = 1.0
    sig.loc[:, "B"] = 0.0
    w = strategy.size_positions_per_asset(sig, vol, vol_target=0.10, max_weight=0.20, max_gross=1.0)
    # raw: A=0.10, B=0, C..G=0.20 -> gross 1.10 -> everything scaled by 1/1.1
    assert w.iloc[0]["A"] == pytest.approx(0.10 / 1.1)
    assert w.iloc[0]["B"] == 0.0
    assert w.iloc[0]["C"] == pytest.approx(0.20 / 1.1)
    assert w.sum(axis=1).iloc[0] == pytest.approx(1.0)
    # missing vol -> weight 0, not NaN / inf
    vol.loc[:, "C"] = np.nan
    w = strategy.size_positions_per_asset(sig, vol)
    assert w.iloc[0]["C"] == 0.0 and np.isfinite(w.values).all()


def test_per_asset_scaling_uses_settings_target():
    idx = pd.bdate_range("2020-01-01", periods=2)
    sig = pd.DataFrame(1.0, index=idx, columns=["A"])
    vol = pd.DataFrame(0.80, index=idx, columns=["A"])
    w = strategy.size_positions_per_asset(sig, vol)
    assert w.iloc[0]["A"] == pytest.approx(settings.VOL_TARGET / 0.80)


def _portfolio_vol(close, w):
    lr = np.log(close / close.shift(1)).iloc[-60:]
    return (lr @ w).std(ddof=1) * np.sqrt(252)


def test_portfolio_sizing_single_asset_hits_target():
    """One asset on: gross = min(1, target / its vol), i.e. the portfolio vol equals the target unless capped."""
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(3)
    close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))),      # ~32% vol
                          "B": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))}, index=idx)
    sig = pd.DataFrame({"A": 1.0, "B": 0.0}, index=idx)
    vol = strategy.realized_vol(close, 60)
    w = strategy.size_positions_portfolio(sig, close, vol, vol_target=0.10, max_weight=1.0, max_gross=1.0)
    expected = min(1.0, 0.10 / vol.iloc[-1]["A"])
    assert w.iloc[-1]["A"] == pytest.approx(expected, rel=1e-9)
    assert w.iloc[-1]["B"] == 0.0
    assert _portfolio_vol(close, w.iloc[-1]) == pytest.approx(0.10, rel=1e-6)    # the point of the exercise
    assert (w.iloc[:60] == 0).all().all()                                          # no covariance window yet -> flat


def test_portfolio_sizing_diversification_raises_gross():
    """Two uncorrelated assets: the combined portfolio needs MORE gross than either alone to reach the target."""
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(4)
    close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))),
                          "B": 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))}, index=idx)
    vol = strategy.realized_vol(close, 60)
    one = strategy.size_positions_portfolio(pd.DataFrame({"A": 1.0, "B": 0.0}, index=idx), close, vol, 0.10, max_weight=1.0)
    both = strategy.size_positions_portfolio(pd.DataFrame({"A": 1.0, "B": 1.0}, index=idx), close, vol, 0.10, max_weight=1.0)
    assert both.iloc[-1].sum() > one.iloc[-1].sum()
    assert _portfolio_vol(close, both.iloc[-1]) == pytest.approx(0.10, rel=1e-6)
    # inverse-vol base: relative weights are proportional to 1/vol
    r = both.iloc[-1]["A"] / both.iloc[-1]["B"]
    assert r == pytest.approx(vol.iloc[-1]["B"] / vol.iloc[-1]["A"], rel=1e-9)


def test_portfolio_sizing_caps():
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(5)
    cols = list("ABC")
    close = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 400))) for c in cols}, index=idx)   # ~5% vol
    vol = strategy.realized_vol(close, 60)
    sig = pd.DataFrame(1.0, index=idx, columns=cols)
    w = strategy.size_positions_portfolio(sig, close, vol, vol_target=0.10, max_weight=0.20, max_gross=1.0)
    # low vol -> wants > 100% gross -> gross capped at 1.0 -> 1/3 each -> single-name cap 0.20 -> 0.6 gross
    np.testing.assert_allclose(w.iloc[-1].values, 0.20)
    w = strategy.size_positions_portfolio(sig, close, vol, vol_target=0.10, max_weight=1.0, max_gross=1.0)
    assert w.iloc[-1].sum() == pytest.approx(1.0)                                  # gross cap binds, weights ~1/3
    sig.loc[:, "C"] = 0.0
    w = strategy.size_positions_portfolio(sig, close, vol, vol_target=0.10, max_weight=1.0, max_gross=1.0)
    assert w.iloc[-1]["C"] == 0.0 and np.isfinite(w.values).all()


@pytest.mark.skipif(not (settings.DATA_DIR / "SPY.csv").exists(), reason="no committed cache")
def test_portfolio_sizing_ignores_nan_in_unheld_assets():
    """An asset with no price history yet (NaN returns) must not zero out the portfolio while it is unheld."""
    idx = pd.bdate_range("2020-01-01", periods=300)
    rng = np.random.default_rng(6)
    close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), "B": np.nan}, index=idx)
    vol = strategy.realized_vol(close, 60)
    w = strategy.size_positions_portfolio(pd.DataFrame({"A": 1.0, "B": 0.0}, index=idx), close, vol, 0.10, max_weight=1.0)
    assert w.iloc[-1]["A"] > 0 and w.iloc[-1]["B"] == 0.0


@pytest.mark.skipif(not (settings.DATA_DIR / "SPY.csv").exists(), reason="no committed cache")
def test_target_weights_dispatch_and_default_is_portfolio():
    close = data_loader.load_prices(end="2012-12-31")["close"]
    assert settings.SIZING == "portfolio"
    pd.testing.assert_frame_equal(strategy.target_weights(close), strategy.target_weights(close, sizing="portfolio"))
    v2, v1 = strategy.target_weights(close), strategy.target_weights(close, sizing="per_position")
    assert not v2.equals(v1)
    assert v2.sum(axis=1).max() <= 1.0 + 1e-9 and v2.max().max() <= 0.20 + 1e-9
    with pytest.raises(ValueError):
        strategy.target_weights(close, sizing="nope")


def test_no_lookahead_in_target_weights():
    """Altering every price AFTER t must leave the weights decided at or before t unchanged."""
    close = _close(n=700)
    t = 500
    base = strategy.target_weights(close)
    tampered = close.copy()
    tampered.iloc[t + 1:] = tampered.iloc[t + 1:] * np.linspace(3.0, 0.2, len(tampered) - t - 1)[:, None]
    tampered.iloc[t + 1:, 0] = 1.0                                # and a crash in one asset
    alt = strategy.target_weights(tampered)
    pd.testing.assert_frame_equal(base.iloc[: t + 1], alt.iloc[: t + 1])
    assert not base.iloc[t + 1:].equals(alt.iloc[t + 1:])        # sanity: the tampering did change the future
    # and the same for the v1 sizing used in the ablation
    b1, a1 = strategy.target_weights(close, sizing="per_position"), strategy.target_weights(tampered, sizing="per_position")
    pd.testing.assert_frame_equal(b1.iloc[: t + 1], a1.iloc[: t + 1])


def test_rebalance_dates_are_first_trading_day_of_month():
    idx = pd.bdate_range("2021-01-01", "2021-06-30")
    rb = strategy.rebalance_dates(idx)
    assert list(rb.strftime("%Y-%m-%d")) == ["2021-01-01", "2021-02-01", "2021-03-01", "2021-04-01", "2021-05-03", "2021-06-01"]
