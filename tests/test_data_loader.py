import numpy as np
import pandas as pd
import pytest

import data_loader
import settings


def test_synthetic_shape_and_fields():
    px = data_loader.synthetic_prices(n_days=300)
    assert set(px) == set(data_loader.FIELDS)
    for f in data_loader.FIELDS:
        assert list(px[f].columns) == settings.UNIVERSE
        assert len(px[f]) == 300
        assert px[f].index.is_monotonic_increasing
    assert (px["high"] >= px["low"]).all().all()


def test_validate_rejects_bad_data():
    df = data_loader.synthetic_prices(n_days=50, tickers=["SPY"])
    one = pd.DataFrame({f: df[f]["SPY"] for f in data_loader.FIELDS})
    data_loader._validate("SPY", one)                      # clean passes
    bad = one.copy(); bad.loc[bad.index[10], "close"] = -1
    with pytest.raises(ValueError):
        data_loader._validate("SPY", bad)
    bad = one.copy(); bad.loc[bad.index[10], "close"] *= 3
    with pytest.raises(ValueError, match="implausible"):
        data_loader._validate("SPY", bad)


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data_loader, "MANIFEST", tmp_path / "manifest.json")
    syn = data_loader.synthetic_prices(n_days=120, tickers=["SPY", "TLT"])
    for t in ["SPY", "TLT"]:
        pd.DataFrame({f: syn[f][t] for f in data_loader.FIELDS}).rename_axis("date").to_csv(tmp_path / f"{t}.csv")
    px = data_loader.load_prices(["SPY", "TLT"])
    assert list(px["close"].columns) == ["SPY", "TLT"]
    np.testing.assert_allclose(px["close"]["SPY"].values, syn["close"]["SPY"].values, rtol=1e-9)
    sub = data_loader.load_prices(["SPY", "TLT"], start=str(syn["close"].index[50].date()))
    assert sub["close"].index[0] == syn["close"].index[50]


@pytest.mark.skipif(not (settings.DATA_DIR / "SPY.csv").exists(), reason="no committed cache")
def test_committed_cache_is_sane():
    px = data_loader.load_prices()
    assert px["close"].index[0] <= pd.Timestamp("2005-01-05")
    assert px["close"].index[-1] >= pd.Timestamp("2026-01-01")
    assert px["close"]["SPY"].notna().all()
    # everything except DBC (listed 2006-02) has data from the start
    first = px["close"].apply(lambda s: s.first_valid_index())
    assert (first.drop("DBC") <= pd.Timestamp("2005-01-05")).all()
