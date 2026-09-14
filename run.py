#!/usr/bin/env python3
"""CLI:  python run.py backtest | dry-run | trade | status

backtest  full in-sample / out-of-sample / walk-forward / sensitivity run from the committed data cache;
          writes results/*.csv, results/metrics.json, results/equity_curve.png and regenerates README tables.
dry-run   compute today's target orders against the Alpaca PAPER account; print, submit nothing.
trade     same, but submit market-on-open orders (paper only; idempotent per day).
status    account, positions, circuit-breaker state, last journal entries.
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import partial

import numpy as np
import pandas as pd

import settings


def cmd_backtest(args):
    import backtester as bt
    import data_loader
    import strategy
    from report import write_report

    px = data_loader.load_prices(refresh=args.refresh)
    settings.RESULTS_DIR.mkdir(exist_ok=True)
    print(f"data: {px['close'].index[0].date()} .. {px['close'].index[-1].date()}  ({len(px['close'])} bars)")

    runs = {
        "strategy": bt.run_backtest(px),
        "spy": bt.run_backtest(px, constant_weights={settings.BENCHMARK_SPY: 1.0}),
        "60_40": bt.run_backtest(px, constant_weights=settings.BENCHMARK_6040),
    }
    # first date the strategy could actually hold something (needs 12 months of history + SMA)
    first_active = runs["strategy"].weights.sum(axis=1).gt(0).idxmax()
    periods = {
        "full": (str(first_active.date()), None),
        "in_sample": (str(max(first_active, pd.Timestamp(settings.IN_SAMPLE[0])).date()), settings.IN_SAMPLE[1]),
        "out_of_sample": settings.OUT_OF_SAMPLE,
    }
    metrics = {name: {p: bt.to_jsonable(bt.compute_metrics(r, *periods[p])) for p in periods} for name, r in runs.items()}
    # cost drag: same strategy with zero costs, full period
    free = bt.compute_metrics(bt.run_backtest(px, cost_per_side=0.0), *periods["full"])
    cost_drag = {"cagr_no_cost": free["cagr"], "cagr_with_cost": metrics["strategy"]["full"]["cagr"],
                 "cagr_drag": free["cagr"] - metrics["strategy"]["full"]["cagr"],
                 "sharpe_no_cost": free["sharpe"], "cost_per_side_bps": settings.COMMISSION_BPS + settings.SLIPPAGE_BPS}

    # ---- walk-forward: rolling 3-year Sharpe, strategy vs SPY, from the first active date
    wf = bt.rolling_sharpe(runs["strategy"], start=first_active)
    wf_spy = bt.rolling_sharpe(runs["spy"], start=first_active)
    wf["spy_sharpe"] = wf_spy["sharpe"].values
    wf["excess_sharpe"] = wf["sharpe"] - wf["spy_sharpe"]
    wf.to_csv(settings.RESULTS_DIR / "walk_forward.csv", index=False)
    wf_summary = {
        "windows": int(len(wf)), "years": settings.WALK_FORWARD_YEARS, "step_months": settings.WALK_FORWARD_STEP_MONTHS,
        "sharpe_min": float(wf["sharpe"].min()), "sharpe_p25": float(wf["sharpe"].quantile(0.25)),
        "sharpe_median": float(wf["sharpe"].median()), "sharpe_p75": float(wf["sharpe"].quantile(0.75)),
        "sharpe_max": float(wf["sharpe"].max()), "pct_windows_positive_sharpe": float((wf["sharpe"] > 0).mean()),
        "pct_windows_beat_spy": float((wf["excess_sharpe"] > 0).mean()),
        "worst_window_max_drawdown": float(wf["max_drawdown"].min()),
    }

    # ---- sensitivity grid: lookback x vol target, full period and out-of-sample
    rows = []
    for lb in settings.SENS_LOOKBACKS:
        for vt in settings.SENS_VOL_TARGETS:
            fn = partial(strategy.target_weights, lookback_months=lb, vol_target=vt)
            r = bt.run_backtest(px, weights_fn=fn)
            mf = bt.compute_metrics(r, *periods["full"]); mo = bt.compute_metrics(r, *periods["out_of_sample"])
            rows.append({"lookback_months": lb, "vol_target": vt, "sharpe_full": mf["sharpe"], "cagr_full": mf["cagr"],
                         "max_dd_full": mf["max_drawdown"], "sharpe_oos": mo["sharpe"], "cagr_oos": mo["cagr"],
                         "max_dd_oos": mo["max_drawdown"], "avg_gross_exposure": mf["avg_gross_exposure"]})
    sens = pd.DataFrame(rows)
    sens.to_csv(settings.RESULTS_DIR / "sensitivity.csv", index=False)

    # ---- ablation: v1 per-position sizing vs v2 portfolio vol targeting, with and without the 2pp band
    abl = []
    for label, sizing, band in [("v1 per-position vol, 0.5% dust filter (original)", "per_position", 0.005),
                                ("v1 per-position vol + 2pp band", "per_position", settings.REBALANCE_BAND),
                                ("v2 portfolio vol, 0.5% dust filter", "portfolio", 0.005),
                                ("v2 portfolio vol + 2pp band (current)", "portfolio", settings.REBALANCE_BAND)]:
        fn = partial(strategy.target_weights, sizing=sizing)
        r = bt.run_backtest(px, weights_fn=fn, rebalance_band=band)
        r0 = bt.run_backtest(px, weights_fn=fn, rebalance_band=band, cost_per_side=0.0)
        mf, m0, mo = bt.compute_metrics(r, *periods["full"]), bt.compute_metrics(r0, *periods["full"]), bt.compute_metrics(r, *periods["out_of_sample"])
        abl.append({"config": label, "sizing": sizing, "band": band, "cagr": mf["cagr"], "ann_vol": mf["ann_vol"], "sharpe": mf["sharpe"],
                    "max_drawdown": mf["max_drawdown"], "calmar": mf["calmar"], "sharpe_oos": mo["sharpe"], "avg_gross_exposure": mf["avg_gross_exposure"],
                    "n_trades": mf["n_trades"], "annual_turnover": mf["annual_turnover"], "cagr_drag": m0["cagr"] - mf["cagr"], "cagr_no_cost": m0["cagr"]})
    ablation = pd.DataFrame(abl)
    ablation.to_csv(settings.RESULTS_DIR / "ablation.csv", index=False)

    # ---- files
    nav = pd.DataFrame({k: v.nav for k, v in runs.items()})
    nav.to_csv(settings.RESULTS_DIR / "nav.csv", float_format="%.4f")
    runs["strategy"].trades.to_csv(settings.RESULTS_DIR / "trades.csv", index=False, float_format="%.6f")
    runs["strategy"].target_weights.to_csv(settings.RESULTS_DIR / "target_weights.csv", float_format="%.4f")
    bt.monthly_table(runs["strategy"], periods["full"][0]).to_csv(settings.RESULTS_DIR / "monthly_returns.csv", float_format="%.4f")
    (settings.RESULTS_DIR / "metrics.json").write_text(json.dumps({
        "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
        "data_last_bar": str(px["close"].index[-1].date()), "first_active_date": str(first_active.date()),
        "periods": periods, "settings": {k: getattr(settings, k) for k in [
            "UNIVERSE", "MOM_LOOKBACK_MONTHS", "MOM_SKIP_MONTHS", "SMA_WINDOW", "VOL_TARGET", "VOL_WINDOW",
            "MAX_POSITION_WEIGHT", "MAX_GROSS_EXPOSURE", "SIZING", "REBALANCE_BAND", "COMMISSION_BPS", "SLIPPAGE_BPS", "RISK_FREE_RATE",
            "INITIAL_CAPITAL", "WALK_FORWARD_YEARS", "WALK_FORWARD_STEP_MONTHS"]},
        "metrics": metrics, "walk_forward": wf_summary, "cost_drag": bt.to_jsonable(cost_drag),
        "sizing_diagnostics": sizing_diagnostics(px, runs["strategy"]),
    }, indent=2))
    plot_equity(runs, first_active)
    write_report()
    print_summary(metrics, wf_summary, sens)
    print("\n== ablation:")
    print(ablation[["config", "cagr", "ann_vol", "sharpe", "max_drawdown", "avg_gross_exposure", "n_trades", "annual_turnover", "cagr_drag"]].round(4).to_string(index=False))


def sizing_diagnostics(px, res):
    """What sets the size under portfolio vol targeting: the vol target, the gross cap, or the single-name cap."""
    import strategy
    tw = res.target_weights
    on = tw > 0
    active = tw[on.any(axis=1)]
    gross = active.sum(axis=1)
    # gross before the single-name cap would be min(1, target/vol); after the cap it can only be lower.
    # A month is "vol-target bound" when gross < 100% and no position sits at the 20% cap (so the cap did not cut it).
    at_cap = (active >= settings.MAX_POSITION_WEIGHT - 1e-9).any(axis=1)
    vol_bound = (gross < 0.999) & ~at_cap
    cap_bound = at_cap
    full = gross >= 0.999
    return {"position_months_on": int(on.sum().sum()), "months_active": int(len(active)),
            "share_months_vol_target_binding": float(vol_bound.mean()),
            "share_months_name_cap_binding": float(cap_bound.mean()),
            "share_months_fully_invested": float(full.mean()),
            "share_months_all_cash": float((tw.sum(axis=1) < 0.001).mean()),
            "avg_gross_when_active": float(gross.mean()),
            "min_gross_when_active": float(gross.min()),
            "avg_positions_on": float(on.sum(axis=1).mean())}


def plot_equity(runs, start):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import backtester as bt
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.2]})
    labels = {"strategy": "TSMOM 12-1 + 200SMA, vol-scaled", "spy": "SPY buy & hold", "60_40": "60/40 SPY/IEF"}
    for k, r in runs.items():
        nav = r.nav[r.nav.index >= start]; nav = nav / nav.iloc[0]
        a1.plot(nav, label=labels[k], lw=1.6 if k == "strategy" else 1.0)
        a2.plot(bt.drawdown_series(nav) * 100, lw=0.9)
    a1.set_yscale("log"); a1.set_ylabel("growth of $1 (log)"); a1.legend(loc="upper left"); a1.grid(alpha=0.3)
    a1.axvline(pd.Timestamp(settings.OUT_OF_SAMPLE[0]), color="k", ls="--", lw=0.8)
    a1.text(pd.Timestamp(settings.OUT_OF_SAMPLE[0]), a1.get_ylim()[0] * 1.05, " out-of-sample ->", fontsize=8)
    a2.set_ylabel("drawdown %"); a2.grid(alpha=0.3)
    fig.suptitle("Time-series momentum on 10 ETFs vs benchmarks (net of 10 bps/side)")
    fig.tight_layout(); fig.savefig(settings.RESULTS_DIR / "equity_curve.png", dpi=130); plt.close(fig)


def print_summary(metrics, wf, sens):
    cols = ["cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar", "time_in_market", "annual_turnover"]
    for p in ["in_sample", "out_of_sample", "full"]:
        print(f"\n== {p}")
        df = pd.DataFrame({n: {c: metrics[n][p].get(c) for c in cols} for n in metrics}).T
        print(df.round(3).to_string())
    print("\n== walk-forward rolling Sharpe:", {k: round(v, 3) if isinstance(v, float) else v for k, v in wf.items()})
    print("\n== sensitivity (sharpe_full):")
    print(sens.pivot(index="lookback_months", columns="vol_target", values="sharpe_full").round(3).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backtest"); p.add_argument("--refresh", action="store_true", help="re-download prices first")
    p = sub.add_parser("dry-run"); p.add_argument("--force", action="store_true", help="compute even if today is not a rebalance day")
    p.add_argument("--refresh", action="store_true", help="re-download prices first (trade always does)")
    p = sub.add_parser("trade"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--force", action="store_true")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "backtest":
        cmd_backtest(a)
    else:
        import executor
        executor.main(a)


if __name__ == "__main__":
    main()
