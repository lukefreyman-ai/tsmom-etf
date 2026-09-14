from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import executor as ex
import risk_manager as rm
import settings

NY = ZoneInfo("America/New_York")
PREOPEN = datetime(2026, 9, 1, 8, 0, tzinfo=NY)     # Tue Sep 1 2026: first trading day of the month
SESSION = datetime(2026, 9, 1, 10, 0, tzinfo=NY)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TRADE_JOURNAL", tmp_path / "journal.json")
    monkeypatch.setattr(settings, "STATE_FILE", tmp_path / "state.json")
    weights = pd.Series({"SPY": 0.2, "TLT": 0.2, "GLD": 0.2, "QQQ": 0.0, "IEF": 0.0})
    prices = {"SPY": 500.0, "TLT": 90.0, "GLD": 250.0, "QQQ": 400.0, "IEF": 95.0}
    monkeypatch.setattr(ex, "latest_weights", lambda refresh: (weights, pd.Timestamp("2026-08-31"), prices))
    return weights, prices


def test_rebalance_day_detection():
    cal = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
    assert ex.is_rebalance_day(date(2026, 9, 1), cal)
    assert not ex.is_rebalance_day(date(2026, 9, 2), cal)
    assert not ex.is_rebalance_day(date(2026, 10, 1), cal)


def test_compute_target_orders_whole_shares_sells_first():
    w = pd.Series({"SPY": 0.2, "TLT": 0.2, "QQQ": 0.0})
    pos = {"QQQ": {"qty": 10, "price": 400.0}, "SPY": {"qty": 10, "price": 500.0}}
    orders = ex.compute_target_orders(w, 100_000, pos, {"SPY": 500.0, "TLT": 90.0, "QQQ": 400.0})
    by = {o.ticker: o for o in orders}
    assert orders[0].side == "sell" and orders[0].ticker == "QQQ" and by["QQQ"].qty == 10     # exit fully
    assert by["SPY"].side == "buy" and by["SPY"].qty == 30          # floor(20000/500)=40 target, hold 10
    assert by["TLT"].side == "buy" and by["TLT"].qty == 222         # floor(20000/90)=222
    assert all(float(o.qty).is_integer() for o in orders)
    # inside the 2pp rebalance band: no trade (holding 21.5% vs 20% target)
    tiny = ex.compute_target_orders(pd.Series({"SPY": 0.2}), 100_000, {"SPY": {"qty": 43, "price": 500.0}}, {"SPY": 500.0})
    assert tiny == []
    # outside it: trade back to target
    big = ex.compute_target_orders(pd.Series({"SPY": 0.2}), 100_000, {"SPY": {"qty": 45, "price": 500.0}}, {"SPY": 500.0})
    assert len(big) == 1 and big[0].side == "sell" and big[0].qty == 5
    # a 1% target from zero is a full entry: trades regardless of band
    entry = ex.compute_target_orders(pd.Series({"SPY": 0.01}), 100_000, {}, {"SPY": 500.0})
    assert len(entry) == 1 and entry[0].qty == 2


def test_dry_run_submits_nothing_and_journals(sandbox):
    b = ex.OfflineBroker()
    res = ex.run_rebalance(b, dry_run=True, now=PREOPEN)
    assert b.submitted == [] and res["submitted"] == []
    assert {d[0] for d in res["decisions"]} == {"SPY", "TLT", "GLD"} and all(d[1] for d in res["decisions"])
    events = [j["event"] for j in ex.read_journal()]
    assert events == ["signal", "dry_run"]


def test_trade_submits_moo_preopen_and_is_idempotent(sandbox):
    b = ex.OfflineBroker()
    res = ex.run_rebalance(b, dry_run=False, now=PREOPEN)
    assert len(b.submitted) == 3 and all(o["time_in_force"] == "opg" for o in b.submitted)
    assert {o["client_order_id"] for o in b.submitted} == {"tsmom-2026-09-01-SPY", "tsmom-2026-09-01-TLT", "tsmom-2026-09-01-GLD"}
    assert ex.load_state()["last_rebalance_submitted"] == "2026-09-01"
    # second run the same day: nothing new
    res2 = ex.run_rebalance(b, dry_run=False, now=SESSION)
    assert len(b.submitted) == 3 and res2["submitted"] == [] and "already submitted" in res2["skipped"]
    # even with the state file wiped, the broker rejects duplicate client ids -> journalled as rejections, no double trade
    st = ex.load_state(); st["last_rebalance_submitted"] = None; ex.save_state(st)
    ex.run_rebalance(b, dry_run=False, now=SESSION)
    assert len(b.submitted) == 3
    assert sum(1 for j in ex.read_journal() if j["event"] == "rejection" and "already exists" in j["rationale"]) == 3


def test_trade_in_session_uses_plain_market(sandbox):
    b = ex.OfflineBroker()
    ex.run_rebalance(b, dry_run=False, now=SESSION)
    assert all(o["time_in_force"] == "day" for o in b.submitted)


def test_not_rebalance_day_and_not_trading_day(sandbox):
    b = ex.OfflineBroker()
    r = ex.run_rebalance(b, dry_run=False, now=datetime(2026, 9, 2, 10, 0, tzinfo=NY))
    assert "not the first trading day" in r["skipped"] and b.submitted == []
    r = ex.run_rebalance(b, dry_run=False, now=datetime(2026, 9, 5, 10, 0, tzinfo=NY))      # Saturday
    assert "not a trading day" in r["skipped"]
    r = ex.run_rebalance(b, dry_run=False, force=True, now=datetime(2026, 9, 2, 10, 0, tzinfo=NY))
    assert len(b.submitted) == 3


def test_outside_hours_rejected_by_risk_manager(sandbox):
    b = ex.OfflineBroker()
    r = ex.run_rebalance(b, dry_run=False, now=datetime(2026, 9, 1, 18, 0, tzinfo=NY))
    assert b.submitted == [] and all(not d[1] for d in r["decisions"])
    assert sum(1 for j in ex.read_journal() if j["event"] == "rejection") == 3


def test_circuit_breaker_cancels_opens_holds_positions(sandbox):
    open_order = {"id": "x", "client_order_id": "tsmom-2026-08-03-SPY", "symbol": "SPY", "side": "buy", "qty": 5.0, "filled_qty": 0.0,
                  "filled_avg_price": None, "status": "accepted", "time_in_force": "opg", "submitted_at": "", "filled_at": None}
    pos = {"SPY": {"qty": 40, "price": 500.0}}
    b = ex.OfflineBroker(equity=80_000, positions=pos, orders=[open_order])
    st = ex.load_state(); st["breaker"]["high_water_mark"] = 100_000; ex.save_state(st)     # 20% below peak
    r = ex.run_rebalance(b, dry_run=False, now=PREOPEN)
    assert r["halted"] and b.cancelled == 1 and b.submitted == []
    assert b.positions()["SPY"]["qty"] == 40                                                  # not flattened
    assert ex.load_state()["breaker"]["halted"]
    events = [j["event"] for j in ex.read_journal()]
    assert events[:2] == ["circuit_breaker", "halt"]
    # still halted next run, no new breaker event, no orders
    r = ex.run_rebalance(b, dry_run=False, now=SESSION)
    assert r["halted"] and [j["event"] for j in ex.read_journal()].count("circuit_breaker") == 1
    # manual reset flag clears it via status
    monkey = pytest.MonkeyPatch(); monkey.setattr(settings, "CIRCUIT_BREAKER_RESET", True)
    ex.cmd_status(b)
    monkey.undo()
    assert not ex.load_state()["breaker"]["halted"]
    assert "breaker_reset" in [j["event"] for j in ex.read_journal()]


def test_daily_breaker_uses_broker_last_equity(sandbox):
    b = ex.OfflineBroker(equity=96_000)
    b.account = lambda: {"equity": 96_000.0, "cash": 96_000.0, "last_equity": 100_000.0, "portfolio_value": 96_000.0,
                         "account_number": "OFFLINE", "status": "offline"}
    r = ex.run_rebalance(b, dry_run=False, now=PREOPEN)
    assert r["halted"] and "daily" in ex.load_state()["breaker"]["reason"]


def test_reconcile_fills(sandbox):
    filled = {"id": "f1", "client_order_id": "tsmom-2026-09-01-SPY", "symbol": "SPY", "side": "buy", "qty": 40.0, "filled_qty": 40.0,
              "filled_avg_price": 501.2, "status": "filled", "time_in_force": "opg", "submitted_at": "", "filled_at": "2026-09-01T09:30"}
    foreign = {**filled, "id": "f2", "client_order_id": "manual-1"}
    b = ex.OfflineBroker(orders=[filled, foreign])
    new = ex.reconcile_fills(b)
    assert len(new) == 1 and new[0]["event"] == "fill" and new[0]["price"] == 501.2 and new[0]["qty"] == 40.0
    assert ex.reconcile_fills(b) == []            # idempotent


def test_paper_url_assertion():
    """The broker must refuse anything but the paper endpoint."""
    class FakeClient:
        _base_url = "https://api.alpaca.markets"
    import alpaca.trading.client as ac
    orig = ac.TradingClient
    ac.TradingClient = lambda *a, **k: FakeClient()
    try:
        with pytest.raises(SystemExit, match="paper"):
            ex.AlpacaBroker("k", "s")
    finally:
        ac.TradingClient = orig
    real = ex.AlpacaBroker("k", "s")              # constructing the real client needs no network
    assert real.paper


def test_journal_entry_shape(sandbox):
    e = ex.journal("order", "why", "SPY", "buy", 3, 500.0, 100_000, order_id="abc")
    for k in ["timestamp", "event", "ticker", "side", "qty", "price", "portfolio_value", "rationale"]:
        assert k in e
    assert ex.read_journal()[-1]["order_id"] == "abc"
