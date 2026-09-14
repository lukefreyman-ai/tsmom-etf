from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import risk_manager as rm
import settings

NY = ZoneInfo("America/New_York")
OPEN = datetime(2026, 9, 14, 10, 0, tzinfo=NY)        # Monday 10:00 ET
NIGHT = datetime(2026, 9, 14, 20, 0, tzinfo=NY)
SAT = datetime(2026, 9, 12, 11, 0, tzinfo=NY)


def test_market_hours():
    assert rm.is_market_hours(OPEN)[0]
    assert not rm.is_market_hours(NIGHT)[0]
    assert not rm.is_market_hours(SAT)[0]
    assert rm.is_market_hours(datetime(2026, 9, 14, 9, 30, tzinfo=NY))[0]
    # pre-open market-on-open window: allowed only when the settings flag says so
    pre = datetime(2026, 9, 14, 8, 30, tzinfo=NY)
    assert rm.is_market_hours(pre, allow_preopen_moo=True) == (True, "pre-open MOO window")
    assert not rm.is_market_hours(pre, allow_preopen_moo=False)[0]
    assert not rm.is_market_hours(datetime(2026, 9, 14, 9, 29, tzinfo=NY), allow_preopen_moo=True)[0]   # after 09:28 cutoff
    assert not rm.is_market_hours(datetime(2026, 9, 14, 6, 59, tzinfo=NY), allow_preopen_moo=True)[0]
    assert not rm.is_market_hours(datetime(2026, 9, 14, 16, 0, tzinfo=NY))[0]
    # a naive-UTC-ish datetime in another zone is converted correctly (14:00 UTC = 10:00 ET in September)
    assert rm.is_market_hours(datetime(2026, 9, 14, 14, 0, tzinfo=ZoneInfo("UTC")))[0]


def test_order_rejected_outside_hours():
    d = rm.check_orders([rm.Order("SPY", "buy", 10, 100)], {}, {"SPY": 100}, 100_000, now=NIGHT)
    assert not d[0].accepted and "market hours" in d[0].reason
    d = rm.check_orders([rm.Order("SPY", "buy", 10, 100)], {}, {"SPY": 100}, 100_000, now=NIGHT, enforce_hours=False)
    assert d[0].accepted


def test_position_cap():
    pv, px = 100_000, {"SPY": 100.0}
    ok = rm.check_orders([rm.Order("SPY", "buy", 200, 100)], {}, px, pv, now=OPEN)[0]        # 20.0% exactly
    assert ok.accepted
    bad = rm.check_orders([rm.Order("SPY", "buy", 201, 100)], {}, px, pv, now=OPEN)[0]       # 20.1%
    assert not bad.accepted and "cap 20%" in bad.reason
    # existing position counts: holding 15% and buying 6% more is rejected
    bad = rm.check_orders([rm.Order("SPY", "buy", 60, 100)], {"SPY": 150}, px, pv, now=OPEN)[0]
    assert not bad.accepted


def test_gross_cap_and_sequencing():
    pv = 100_000
    px = {t: 100.0 for t in "ABCDEF"}
    pos = {t: 190.0 for t in "ABCDE"}            # 5 x 19% = 95% gross
    d = rm.check_orders([rm.Order("F", "buy", 60, 100)], pos, px, pv, now=OPEN)[0]           # -> 101%
    assert not d.accepted and "gross" in d.reason
    d = rm.check_orders([rm.Order("F", "buy", 50, 100)], pos, px, pv, now=OPEN)[0]           # -> 100%
    assert d.accepted
    # a rejected order must not change the simulated book for the next one
    ds = rm.check_orders([rm.Order("F", "buy", 60, 100), rm.Order("F", "buy", 50, 100)], pos, px, pv, now=OPEN)
    assert [x.accepted for x in ds] == [False, True]
    # sells first (evaluate() sorts): selling A frees room for buying F
    rep, _ = rm.evaluate([rm.Order("F", "buy", 200, 100), rm.Order("A", "sell", 190, 100)], pos, px, pv,
                         rm.BreakerState(high_water_mark=pv, last_close_value=pv), now=OPEN)
    assert all(d.accepted for d in rep.decisions), [d.reason for d in rep.decisions]


def test_no_shorts():
    d = rm.check_orders([rm.Order("SPY", "sell", 11, 100)], {"SPY": 10}, {"SPY": 100}, 100_000, now=OPEN)[0]
    assert not d.accepted and "short" in d.reason
    d = rm.check_orders([rm.Order("SPY", "sell", 10, 100)], {"SPY": 10}, {"SPY": 100}, 100_000, now=OPEN)[0]
    assert d.accepted


def test_daily_drawdown_breaker():
    st = rm.BreakerState(high_water_mark=100_000, last_close_value=100_000)
    st, ev = rm.check_circuit_breakers(97_100, st)          # -2.9%: fine
    assert not st.halted and ev == []
    st, ev = rm.check_circuit_breakers(96_900, st)          # -3.1%: halt
    assert st.halted and "daily" in st.reason and ev[0]["event"] == "circuit_breaker"
    assert "hold positions" in ev[0]["action"]               # do NOT flatten
    # once halted, nothing un-halts it except the manual flag
    st, ev = rm.check_circuit_breakers(120_000, st)
    assert st.halted and ev == []
    st, was = rm.reset_breaker(st, flag=False)
    assert st.halted and not was
    st, was = rm.reset_breaker(st, flag=True)
    assert not st.halted and was


def test_peak_drawdown_breaker_and_hwm():
    st = rm.BreakerState()
    st, _ = rm.check_circuit_breakers(100_000, st); st.last_close_value = 100_000
    st, _ = rm.check_circuit_breakers(110_000, st); st.last_close_value = 110_000
    assert st.high_water_mark == 110_000
    st, _ = rm.check_circuit_breakers(108_000, st); st.last_close_value = 108_000   # -1.8% peak, fine
    assert not st.halted
    # slow bleed: each day < 3% but cumulative > 15% from the 110k peak
    for v in [106_000, 104_000, 102_000, 100_000, 98_000, 96_000, 94_000, 93_000]:   # each step < 3%
        st, ev = rm.check_circuit_breakers(v, st); st.last_close_value = v
    assert st.halted and "peak" in st.reason


def test_evaluate_halt_rejects_everything():
    st = rm.BreakerState(high_water_mark=100_000, last_close_value=100_000)
    rep, st = rm.evaluate([rm.Order("SPY", "buy", 10, 100), rm.Order("TLT", "sell", 5, 100)],
                          {"TLT": 5}, {"SPY": 100, "TLT": 100}, 80_000, st, now=OPEN)
    assert rep.halt and st.halted
    assert all(not d.accepted for d in rep.decisions)
    assert rep.events[0]["event"] == "circuit_breaker"
    assert rep.accepted == []


def test_limits_come_from_settings():
    assert settings.MAX_DAILY_DRAWDOWN == 0.03 and settings.MAX_PEAK_DRAWDOWN == 0.15
    assert settings.LIVE_MAX_POSITION_WEIGHT == 0.20 and settings.LIVE_MAX_GROSS_EXPOSURE == 1.00
    assert settings.CIRCUIT_BREAKER_RESET is False, "reset flag must be committed as False"
