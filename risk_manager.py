"""Pre-trade risk checks and circuit breakers for live/paper execution.

Pure logic, no broker calls: the executor feeds it account state and proposed orders and gets back
accept / reject decisions plus events to journal. All limits come from settings.py.

Circuit breakers (checked before any order is considered):
  * daily drawdown:  today's portfolio value < (1 - MAX_DAILY_DRAWDOWN) x yesterday's close value
  * peak drawdown:   today's portfolio value < (1 - MAX_PEAK_DRAWDOWN)  x high-water mark
When tripped the manager returns halt=True. The executor must then cancel open orders, NOT flatten,
journal the event, and refuse new orders. The halt persists in live_state.json until a human sets
settings.CIRCUIT_BREAKER_RESET = True and runs `python run.py status` (which clears it and reminds you
to set the flag back to False).

Per-order checks (each proposed order is simulated on top of the current book, in sequence):
  * resulting single-position weight <= LIVE_MAX_POSITION_WEIGHT
  * resulting gross exposure         <= LIVE_MAX_GROSS_EXPOSURE
  * no short positions (long-only strategy)
  * submission time inside regular market hours (America/New_York, 09:30-16:00, Mon-Fri)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

import settings


@dataclass
class Order:
    ticker: str
    side: str            # "buy" | "sell"
    qty: float
    ref_price: float     # price used to estimate the order's notional
    rationale: str = ""

    @property
    def signed_qty(self) -> float:
        return self.qty if self.side == "buy" else -self.qty

    @property
    def notional(self) -> float:
        return self.qty * self.ref_price


@dataclass
class RiskDecision:
    order: Order
    accepted: bool
    reason: str


@dataclass
class BreakerState:
    halted: bool = False
    reason: str = ""
    tripped_at: str = ""
    high_water_mark: float = 0.0
    last_close_value: float = 0.0


@dataclass
class RiskReport:
    halt: bool
    halt_reason: str
    decisions: list[RiskDecision] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    @property
    def accepted(self) -> list[Order]:
        return [d.order for d in self.decisions if d.accepted]

    @property
    def rejected(self) -> list[RiskDecision]:
        return [d for d in self.decisions if not d.accepted]


def is_market_hours(now: datetime | None = None) -> tuple[bool, str]:
    tz = ZoneInfo(settings.MARKET_TZ)
    now = (now or datetime.now(tz)).astimezone(tz)
    if now.weekday() >= 5:
        return False, f"weekend ({now:%a})"
    o = time.fromisoformat(settings.MARKET_OPEN)
    c = time.fromisoformat(settings.MARKET_CLOSE)
    if not (o <= now.time() < c):
        return False, f"outside {settings.MARKET_OPEN}-{settings.MARKET_CLOSE} {settings.MARKET_TZ} ({now:%H:%M})"
    return True, "regular hours"


def check_circuit_breakers(portfolio_value: float, state: BreakerState,
                           max_daily_dd: float = settings.MAX_DAILY_DRAWDOWN,
                           max_peak_dd: float = settings.MAX_PEAK_DRAWDOWN,
                           now: datetime | None = None) -> tuple[BreakerState, list[dict]]:
    """Update HWM, evaluate both breakers, return the new state and any events. Idempotent once halted."""
    events = []
    ts = (now or datetime.now(ZoneInfo(settings.MARKET_TZ))).isoformat(timespec="seconds")
    if state.halted:
        return state, events
    state.high_water_mark = max(state.high_water_mark, portfolio_value)
    if state.last_close_value > 0:
        daily = portfolio_value / state.last_close_value - 1.0
        if daily < -max_daily_dd:
            state.halted, state.reason, state.tripped_at = True, f"daily drawdown {daily:.2%} < -{max_daily_dd:.0%}", ts
    if not state.halted and state.high_water_mark > 0:
        peak = portfolio_value / state.high_water_mark - 1.0
        if peak < -max_peak_dd:
            state.halted, state.reason, state.tripped_at = True, f"drawdown from peak {peak:.2%} < -{max_peak_dd:.0%}", ts
    if state.halted:
        events.append({"event": "circuit_breaker", "reason": state.reason, "portfolio_value": portfolio_value,
                       "high_water_mark": state.high_water_mark, "last_close_value": state.last_close_value,
                       "action": "cancel open orders, hold positions, require manual reset"})
    return state, events


def reset_breaker(state: BreakerState, flag: bool = settings.CIRCUIT_BREAKER_RESET) -> tuple[BreakerState, bool]:
    """Clear a halt only if the manual flag in settings.py is True. Returns (state, was_reset)."""
    if state.halted and flag:
        state.halted, state.reason, state.tripped_at = False, "", ""
        return state, True
    return state, False


def check_orders(orders: list[Order], positions: dict[str, float], prices: dict[str, float],
                 portfolio_value: float, max_weight: float = settings.LIVE_MAX_POSITION_WEIGHT,
                 max_gross: float = settings.LIVE_MAX_GROSS_EXPOSURE, now: datetime | None = None,
                 enforce_hours: bool = True) -> list[RiskDecision]:
    """Simulate each order onto the book in order. Rejected orders do not change the simulated book."""
    book = {t: float(q) for t, q in positions.items()}
    out = []
    ok_hours, why_hours = is_market_hours(now)
    for o in orders:
        if o.side not in ("buy", "sell") or o.qty <= 0:
            out.append(RiskDecision(o, False, f"malformed order: side={o.side} qty={o.qty}")); continue
        if enforce_hours and not ok_hours:
            out.append(RiskDecision(o, False, f"outside regular market hours: {why_hours}")); continue
        if portfolio_value <= 0:
            out.append(RiskDecision(o, False, "portfolio value is not positive")); continue
        new_qty = book.get(o.ticker, 0.0) + o.signed_qty
        if new_qty < -1e-9:
            out.append(RiskDecision(o, False, f"would create a short position in {o.ticker} ({new_qty:.4f} shares)")); continue
        px = dict(prices); px.setdefault(o.ticker, o.ref_price)
        weight = new_qty * px[o.ticker] / portfolio_value
        if weight > max_weight + 1e-9:
            out.append(RiskDecision(o, False, f"{o.ticker} weight {weight:.1%} would exceed cap {max_weight:.0%}")); continue
        sim = dict(book); sim[o.ticker] = new_qty
        gross = sum(abs(q) * px.get(t, 0.0) for t, q in sim.items()) / portfolio_value
        if gross > max_gross + 1e-9:
            out.append(RiskDecision(o, False, f"gross exposure {gross:.1%} would exceed cap {max_gross:.0%}")); continue
        book[o.ticker] = new_qty
        out.append(RiskDecision(o, True, "ok"))
    return out


def evaluate(orders: list[Order], positions: dict[str, float], prices: dict[str, float], portfolio_value: float,
             state: BreakerState, now: datetime | None = None, enforce_hours: bool = True) -> tuple[RiskReport, BreakerState]:
    """Full pre-trade pipeline: breakers first (halt = every order rejected), then per-order checks."""
    state, events = check_circuit_breakers(portfolio_value, state, now=now)
    if state.halted:
        decisions = [RiskDecision(o, False, f"circuit breaker halted: {state.reason}") for o in orders]
        return RiskReport(True, state.reason, decisions, events), state
    # sells first so that freed capital is available for buys in the simulated book
    ordered = sorted(orders, key=lambda o: 0 if o.side == "sell" else 1)
    decisions = check_orders(ordered, positions, prices, portfolio_value, now=now, enforce_hours=enforce_hours)
    return RiskReport(False, "", decisions, events), state
