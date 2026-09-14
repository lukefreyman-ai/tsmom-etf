"""Alpaca PAPER execution of the monthly rebalance. Never touches the live endpoint.

    python run.py dry-run            compute + print target orders and risk decisions, submit nothing
    python run.py trade              submit (rebalance day only; --force overrides the calendar check)
    python run.py status             account, positions, breaker state, reconcile fills into the journal

Flow on a run: paper-URL assertion -> account/positions -> circuit breakers -> (halt: cancel opens, journal, stop)
-> rebalance-day check -> refresh prices, target weights from the previous close -> diff vs positions in whole
shares -> risk manager -> submit MOO (opg) in the pre-open window, plain market during the session -> journal.
Idempotent per day: client_order_id = tsmom-YYYY-MM-DD-TICKER and live_state.json records the last submission date.
"""
from __future__ import annotations

import json
import math
import sys
import uuid
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

import risk_manager as rm
import settings
import strategy

TZ = ZoneInfo(settings.MARKET_TZ)
ORDER_PREFIX = "tsmom"


# ----------------------------------------------------------------------------- journal & state

def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def journal(event: str, rationale: str, ticker: str = "", side: str = "", qty: float | None = None,
            price: float | None = None, portfolio_value: float | None = None, **extra) -> dict:
    """Append one entry to results/trade_journal.json (a JSON array). Returns the entry."""
    entry = {"timestamp": now_iso(), "event": event, "ticker": ticker, "side": side, "qty": qty, "price": price,
             "portfolio_value": portfolio_value, "rationale": rationale, **extra}
    path = settings.TRADE_JOURNAL
    path.parent.mkdir(parents=True, exist_ok=True)
    items = json.loads(path.read_text()) if path.exists() else []
    items.append(entry)
    path.write_text(json.dumps(items, indent=1, default=str))
    return entry


def read_journal() -> list[dict]:
    return json.loads(settings.TRADE_JOURNAL.read_text()) if settings.TRADE_JOURNAL.exists() else []


def load_state() -> dict:
    if settings.STATE_FILE.exists():
        return json.loads(settings.STATE_FILE.read_text())
    return {"breaker": asdict(rm.BreakerState()), "last_rebalance_submitted": None, "last_close_date": None}


def save_state(state: dict) -> None:
    settings.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.STATE_FILE.write_text(json.dumps(state, indent=1, default=str))


# ----------------------------------------------------------------------------- brokers

class AlpacaBroker:
    """Thin wrapper over alpaca-py TradingClient, paper only."""

    def __init__(self, key: str, secret: str):
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(key, secret, paper=True, url_override=settings.ALPACA_PAPER_URL)
        base = str(getattr(self.client, "_base_url", ""))
        base_str = getattr(getattr(self.client, "_base_url", None), "value", base)
        if not str(base_str).startswith("https://paper-api.alpaca.markets"):
            raise SystemExit(f"REFUSING TO RUN: Alpaca base URL is {base_str!r}, not the paper endpoint")
        self.paper = True

    def account(self) -> dict:
        a = self.client.get_account()
        return {"equity": float(a.equity), "cash": float(a.cash), "last_equity": float(a.last_equity),
                "portfolio_value": float(a.portfolio_value), "account_number": a.account_number, "status": str(a.status)}

    def positions(self) -> dict[str, dict]:
        return {p.symbol: {"qty": float(p.qty), "price": float(p.current_price), "market_value": float(p.market_value)}
                for p in self.client.get_all_positions()}

    def open_orders(self) -> list[dict]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        return [self._order_dict(o) for o in self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))]

    def all_orders(self, limit: int = 500) -> list[dict]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        return [self._order_dict(o) for o in self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit))]

    def cancel_all(self) -> int:
        return len(self.client.cancel_orders())

    def calendar(self, start: date, end: date) -> list[date]:
        from alpaca.trading.requests import GetCalendarRequest
        return [c.date for c in self.client.get_calendar(GetCalendarRequest(start=start, end=end))]

    def submit_market(self, ticker: str, side: str, qty: int, client_order_id: str, on_open: bool) -> dict:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        req = MarketOrderRequest(symbol=ticker, qty=qty, side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                                 time_in_force=TimeInForce.OPG if on_open else TimeInForce.DAY, client_order_id=client_order_id)
        return self._order_dict(self.client.submit_order(req))

    @staticmethod
    def _order_dict(o) -> dict:
        return {"id": str(o.id), "client_order_id": o.client_order_id, "symbol": o.symbol, "side": str(o.side.value if hasattr(o.side, 'value') else o.side),
                "qty": float(o.qty) if o.qty else None, "filled_qty": float(o.filled_qty or 0),
                "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                "status": str(o.status.value if hasattr(o.status, 'value') else o.status),
                "time_in_force": str(o.time_in_force.value if hasattr(o.time_in_force, 'value') else o.time_in_force),
                "submitted_at": str(o.submitted_at), "filled_at": str(o.filled_at) if o.filled_at else None}


class OfflineBroker:
    """No credentials: a hypothetical all-cash paper account so dry-run can be exercised offline."""
    paper = True

    def __init__(self, equity: float = 100_000.0, positions: dict | None = None, orders: list | None = None):
        self._equity, self._positions, self._orders = equity, dict(positions or {}), list(orders or [])
        self.submitted: list[dict] = []
        self.cancelled = 0

    def account(self) -> dict:
        mv = sum(p["qty"] * p["price"] for p in self._positions.values())
        return {"equity": self._equity, "cash": self._equity - mv, "last_equity": self._equity,
                "portfolio_value": self._equity, "account_number": "OFFLINE", "status": "offline"}

    def positions(self) -> dict[str, dict]:
        return {t: {**p, "market_value": p["qty"] * p["price"]} for t, p in self._positions.items()}

    def open_orders(self) -> list[dict]:
        return [o for o in self._orders if o["status"] in ("new", "accepted", "pending_new")]

    def all_orders(self, limit: int = 500) -> list[dict]:
        return list(self._orders)

    def cancel_all(self) -> int:
        n = len(self.open_orders())
        for o in self._orders:
            if o["status"] in ("new", "accepted", "pending_new"):
                o["status"] = "canceled"
        self.cancelled += n
        return n

    def calendar(self, start: date, end: date) -> list[date]:
        return [d.date() for d in pd.bdate_range(start, end)]

    def submit_market(self, ticker, side, qty, client_order_id, on_open) -> dict:
        if any(o["client_order_id"] == client_order_id for o in self._orders):
            raise RuntimeError(f"client_order_id {client_order_id} already exists")   # Alpaca does the same
        o = {"id": str(uuid.uuid4()), "client_order_id": client_order_id, "symbol": ticker, "side": side, "qty": float(qty),
             "filled_qty": 0.0, "filled_avg_price": None, "status": "accepted", "time_in_force": "opg" if on_open else "day",
             "submitted_at": now_iso(), "filled_at": None}
        self._orders.append(o); self.submitted.append(o)
        return o


def make_broker() -> AlpacaBroker | OfflineBroker:
    try:
        from dotenv import load_dotenv
        load_dotenv(settings.ROOT / ".env")
    except ImportError:
        pass
    import os
    key, secret = os.environ.get("ALPACA_KEY_ID", ""), os.environ.get("ALPACA_SECRET_KEY", "")
    if key and secret:
        return AlpacaBroker(key, secret)
    print("!! no ALPACA_KEY_ID / ALPACA_SECRET_KEY in the environment: using an OFFLINE $100,000 all-cash account")
    return OfflineBroker()


# ----------------------------------------------------------------------------- core logic (pure, tested)

def is_rebalance_day(today: date, trading_days: list[date]) -> bool:
    month = [d for d in trading_days if d.year == today.year and d.month == today.month]
    return bool(month) and month[0] == today


def compute_target_orders(weights: pd.Series, equity: float, positions: dict[str, dict], prices: dict[str, float],
                          min_trade_weight: float = settings.MIN_TRADE_WEIGHT) -> list[rm.Order]:
    """Whole-share orders that move the book from `positions` to `weights` x equity. Sells first."""
    orders = []
    tickers = sorted(set(weights.index) | set(positions))
    for t in tickers:
        w = float(weights.get(t, 0.0))
        px = prices.get(t) or positions.get(t, {}).get("price")
        if not px or px <= 0:
            continue
        cur = float(positions.get(t, {}).get("qty", 0.0))
        cur_w = cur * px / equity
        if abs(w - cur_w) < min_trade_weight and not (w == 0 and cur > 0):
            continue                                   # drift under 0.5% of NAV: not worth a trade
        target = math.floor(w * equity / px) if w > 0 else 0
        delta = target - cur
        if delta == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        why = (f"12-1 momentum & 200-SMA on: target {w:.1%}" if w > 0 else "signal off: exit to cash") \
            + f"; {cur:g} -> {target:g} sh @ ~{px:.2f}"
        orders.append(rm.Order(t, side, abs(int(delta)) if delta == int(delta) else abs(delta), px, why))
    return sorted(orders, key=lambda o: 0 if o.side == "sell" else 1)


def latest_weights(refresh: bool) -> tuple[pd.Series, pd.Timestamp, dict[str, float]]:
    import data_loader
    px = data_loader.load_prices(refresh=refresh)
    close = px["close"]
    w = strategy.target_weights(close).iloc[-1]
    return w.fillna(0.0), close.index[-1], close.iloc[-1].dropna().to_dict()


# ----------------------------------------------------------------------------- commands

def run_rebalance(broker, dry_run: bool, force: bool = False, refresh: bool | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    today = now.date()
    state = load_state()
    acct = broker.account()
    equity = acct["equity"]
    pos = broker.positions()
    prices_live = {t: p["price"] for t, p in pos.items()}
    print(f"account {acct['account_number']}  equity ${equity:,.2f}  cash ${acct['cash']:,.2f}  positions: "
          + (", ".join(f"{t} {p['qty']:g}" for t, p in pos.items()) or "none"))

    # 1. circuit breakers (using the broker's previous-close equity for the daily check)
    bs = rm.BreakerState(**state["breaker"])
    bs.last_close_value = acct.get("last_equity") or bs.last_close_value
    bs, events = rm.check_circuit_breakers(equity, bs, now=now)
    state["breaker"] = asdict(bs)
    for ev in events:
        journal("circuit_breaker", ev["reason"], portfolio_value=equity, action=ev["action"], high_water_mark=ev["high_water_mark"])
    if bs.halted:
        n = 0 if dry_run else broker.cancel_all()
        journal("halt", f"halted since {bs.tripped_at}: {bs.reason}. {'would cancel' if dry_run else 'cancelled'} {n} open orders; positions held; "
                        "set settings.CIRCUIT_BREAKER_RESET=True and run `python run.py status` to resume", portfolio_value=equity)
        save_state(state)
        print(f"!! CIRCUIT BREAKER HALTED: {bs.reason}. No orders. Positions held.")
        return {"halted": True, "orders": [], "submitted": []}

    # 2. rebalance day?
    cal = broker.calendar(today.replace(day=1), today)
    if today not in cal:
        msg = f"{today} is not a trading day"
        journal("info", msg, portfolio_value=equity); print(msg); save_state(state)
        return {"halted": False, "orders": [], "submitted": [], "skipped": msg}
    if not is_rebalance_day(today, cal) and not force:
        msg = f"{today} is not the first trading day of the month (that was {cal[0]}); nothing to do (--force to override)"
        journal("info", msg, portfolio_value=equity); print(msg); save_state(state)
        return {"halted": False, "orders": [], "submitted": [], "skipped": msg}
    if state.get("last_rebalance_submitted") == str(today) and not dry_run:
        msg = f"rebalance for {today} already submitted (live_state.json); refusing to double-trade"
        journal("info", msg, portfolio_value=equity); print(msg)
        return {"halted": False, "orders": [], "submitted": [], "skipped": msg}

    # 3. signal from the previous close
    weights, asof, last_close = latest_weights(refresh=(not dry_run) if refresh is None else refresh)
    prev_td = cal[-2] if len(cal) >= 2 and cal[-1] == today else None
    stale = prev_td is not None and asof.date() < prev_td
    if stale:
        print(f"!! WARNING: cached prices end {asof.date()} but the previous trading day was {prev_td}; run with --refresh")
    on = weights[weights > 0]
    journal("signal", f"targets as of close {asof.date()}: " + (", ".join(f"{t} {w:.1%}" for t, w in on.items()) or "all cash")
            + (" [STALE DATA]" if stale else ""), portfolio_value=equity, weights={t: round(float(w), 4) for t, w in weights.items()})
    prices = {**last_close, **prices_live}

    # 4. orders -> risk manager
    orders = compute_target_orders(weights, equity, pos, prices)
    report, bs = rm.evaluate(orders, {t: p["qty"] for t, p in pos.items()}, prices, equity, bs, now=now)
    state["breaker"] = asdict(bs)
    for d in report.rejected:
        journal("rejection", d.reason, d.order.ticker, d.order.side, d.order.qty, d.order.ref_price, equity)
    hours_ok, hours_why = rm.is_market_hours(now)
    on_open = hours_why == "pre-open MOO window"

    print(f"\n{'DRY RUN: ' if dry_run else ''}target orders for {today} (signal as of {asof.date()}, {hours_why}):")
    if not orders:
        print("  none: book already matches targets")
    for d in report.decisions:
        o = d.order
        print(f"  {'OK    ' if d.accepted else 'REJECT'} {o.side:4} {o.qty:>6g} {o.ticker:4} ~${o.notional:>10,.2f}  {o.rationale}"
              + ("" if d.accepted else f"   <- {d.reason}"))
    submitted = []
    if dry_run:
        journal("dry_run", f"{len(report.accepted)} orders would be submitted ({'opg' if on_open else 'market'}); {len(report.rejected)} rejected",
                portfolio_value=equity)
    else:
        for o in report.accepted:
            coid = f"{ORDER_PREFIX}-{today}-{o.ticker}"
            try:
                res = broker.submit_market(o.ticker, o.side, int(o.qty), coid, on_open)
                submitted.append(res)
                journal("order", o.rationale + f" | {res['time_in_force']} {res['status']}", o.ticker, o.side, o.qty, o.ref_price, equity,
                        order_id=res["id"], client_order_id=coid)
            except Exception as e:  # noqa: BLE001
                journal("rejection", f"broker rejected: {e}", o.ticker, o.side, o.qty, o.ref_price, equity, client_order_id=coid)
                print(f"  !! broker rejected {o.side} {o.qty} {o.ticker}: {e}")
        if report.accepted:
            state["last_rebalance_submitted"] = str(today)
        print(f"\nsubmitted {len(submitted)} of {len(report.accepted)} accepted orders")
    save_state(state)
    return {"halted": False, "orders": [asdict(o) for o in orders], "decisions": [(d.order.ticker, d.accepted, d.reason) for d in report.decisions],
            "submitted": submitted}


def reconcile_fills(broker) -> list[dict]:
    """Journal a `fill` for every filled tsmom-* order not already journalled as filled."""
    seen = {j.get("order_id") for j in read_journal() if j["event"] == "fill"}
    new = []
    for o in broker.all_orders():
        if not (o["client_order_id"] or "").startswith(ORDER_PREFIX) or o["id"] in seen:
            continue
        if o["status"] == "filled" and o["filled_qty"]:
            new.append(journal("fill", f"filled {o['time_in_force']} order {o['client_order_id']}", o["symbol"], o["side"],
                               o["filled_qty"], o["filled_avg_price"], None, order_id=o["id"], filled_at=o["filled_at"]))
        elif o["status"] in ("canceled", "expired", "rejected") and o["id"] not in {j.get("order_id") for j in read_journal() if j["event"] == "order_closed"}:
            new.append(journal("order_closed", f"order {o['client_order_id']} ended {o['status']} (filled {o['filled_qty']:g} of {o['qty']:g})",
                               o["symbol"], o["side"], o["qty"], o["filled_avg_price"], None, order_id=o["id"]))
    return new


def cmd_status(broker) -> None:
    state = load_state()
    bs = rm.BreakerState(**state["breaker"])
    bs, was_reset = rm.reset_breaker(bs)
    if was_reset:
        journal("breaker_reset", "manual reset via settings.CIRCUIT_BREAKER_RESET=True")
        print("circuit breaker RESET. Now set settings.CIRCUIT_BREAKER_RESET back to False.")
    elif bs.halted:
        print(f"!! HALTED since {bs.tripped_at}: {bs.reason}  (set settings.CIRCUIT_BREAKER_RESET=True and rerun status)")
    elif settings.CIRCUIT_BREAKER_RESET:
        print("note: CIRCUIT_BREAKER_RESET is True but nothing is halted; set it back to False.")
    state["breaker"] = asdict(bs)
    acct = broker.account(); pos = broker.positions()
    print(f"account {acct['account_number']} ({acct['status']})  equity ${acct['equity']:,.2f}  cash ${acct['cash']:,.2f}  "
          f"prev close ${acct['last_equity']:,.2f}  HWM ${bs.high_water_mark:,.2f}")
    for t, p in sorted(pos.items()):
        print(f"  {t:4} {p['qty']:>8g} sh  ${p['market_value']:>12,.2f}  {p['market_value'] / acct['equity']:.1%}")
    print(f"gross exposure {sum(p['market_value'] for p in pos.values()) / acct['equity']:.1%}   last rebalance submitted: {state.get('last_rebalance_submitted')}")
    opens = broker.open_orders()
    print(f"open orders: {len(opens)}" + "".join(f"\n  {o['side']} {o['qty']:g} {o['symbol']} {o['time_in_force']} {o['status']}" for o in opens))
    new = reconcile_fills(broker)
    print(f"reconciled {len(new)} new fill/close events into the journal")
    save_state(state)
    for j in read_journal()[-8:]:
        print(f"  {j['timestamp']} {j['event']:15} {j.get('ticker',''):4} {j.get('side','') or '':4} {j.get('qty') or '':>6} {j['rationale'][:90]}")


def main(args) -> None:
    broker = make_broker()
    if args.cmd == "status":
        cmd_status(broker)
    elif args.cmd == "dry-run":
        run_rebalance(broker, dry_run=True, force=args.force, refresh=getattr(args, "refresh", False))
    elif args.cmd == "trade":
        if args.dry_run:
            run_rebalance(broker, dry_run=True, force=args.force)
        else:
            if isinstance(broker, OfflineBroker):
                sys.exit("trade requires Alpaca paper credentials")
            run_rebalance(broker, dry_run=False, force=args.force)
