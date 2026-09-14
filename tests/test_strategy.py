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


def test_size_positions_caps_and_scaling():
    idx = pd.bdate_range("2020-01-01", periods=3)
    cols = list("ABCDEFG")
    sig = pd.DataFrame(1.0, index=idx, columns=cols)
    vol = pd.DataFrame(0.10, index=idx, columns=cols)            # raw weight = 0.10/0.10 = 1.0 each
    w = strategy.size_positions(sig, vol, vol_target=0.10, max_weight=0.20, max_gross=1.0)
    np.testing.assert_allclose(w.iloc[0].values, 1.0 / 7)       # 7 x 0.20 = 1.4 > 1.0 -> scaled to 1/7 each
    assert w.sum(axis=1).iloc[0] == pytest.approx(1.0)
    # high vol shrinks the position below the cap; zero signal -> zero weight
    vol.loc[:, "A"] = 1.0
    sig.loc[:, "B"] = 0.0
    w = strategy.size_positions(sig, vol, vol_target=0.10, max_weight=0.20, max_gross=1.0)
    # raw: A=0.10, B=0, C..G=0.20 -> gross 1.10 -> everything scaled by 1/1.1
    assert w.iloc[0]["A"] == pytest.approx(0.10 / 1.1)
    assert w.iloc[0]["B"] == 0.0
    assert w.iloc[0]["C"] == pytest.approx(0.20 / 1.1)
    assert w.sum(axis=1).iloc[0] == pytest.approx(1.0)
    # missing vol -> weight 0, not NaN / inf
    vol.loc[:, "C"] = np.nan
    w = strategy.size_positions(sig, vol)
    assert w.iloc[0]["C"] == 0.0 and np.isfinite(w.values).all()


def test_vol_scaling_uses_settings_target():
    idx = pd.bdate_range("2020-01-01", periods=2)
    sig = pd.DataFrame(1.0, index=idx, columns=["A"])
    vol = pd.DataFrame(0.80, index=idx, columns=["A"])
    w = strategy.size_positions(sig, vol)
    assert w.iloc[0]["A"] == pytest.approx(settings.VOL_TARGET / 0.80)


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


def test_rebalance_dates_are_first_trading_day_of_month():
    idx = pd.bdate_range("2021-01-01", "2021-06-30")
    rb = strategy.rebalance_dates(idx)
    assert list(rb.strftime("%Y-%m-%d")) == ["2021-01-01", "2021-02-01", "2021-03-01", "2021-04-01", "2021-05-03", "2021-06-01"]
