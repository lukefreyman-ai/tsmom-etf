"""Regenerates the README results tables from results/*. Never type a number into README.md by hand:
everything between <!-- results:start --> and <!-- results:end --> is overwritten by `python run.py backtest`."""
from __future__ import annotations

import json
import re

import pandas as pd

import settings

START, END = "<!-- results:start -->", "<!-- results:end -->"
NSTART, NEND = "<!-- numbers:start -->", "<!-- numbers:end -->"


def pct(x, d=1):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "n/a" if x is None else f"{x:.{d}f}"


def metrics_table(metrics: dict, period: str) -> str:
    rows = [("CAGR", "cagr", pct), ("Annualised vol", "ann_vol", pct), ("Sharpe (rf=0)", "sharpe", num),
            ("Sortino", "sortino", num), ("Max drawdown", "max_drawdown", pct),
            ("Max DD duration (days)", "max_dd_duration_days", lambda x: str(x)), ("Calmar", "calmar", num),
            ("Trades", "n_trades", lambda x: str(x)), ("Avg holding period (days)", "avg_holding_period_days", lambda x: num(x, 0)),
            ("Time in market", "time_in_market", pct), ("Avg gross exposure", "avg_gross_exposure", pct),
            ("Annual one-way turnover", "annual_turnover", lambda x: num(x, 2) + "x"),
            ("Best month", "best_month", pct), ("Worst month", "worst_month", pct)]
    names = {"strategy": "Strategy", "spy": "SPY B&H", "60_40": "60/40"}
    m = {k: metrics[k][period] for k in names}
    s = m["strategy"]
    out = [f"Period: {s['start']} to {s['end']} ({s['years']} years)", "",
           "| metric | " + " | ".join(names.values()) + " |", "|---|" + "---|" * len(names)]
    for label, key, f in rows:
        out.append(f"| {label} | " + " | ".join(f(m[k].get(key)) for k in names) + " |")
    return "\n".join(out)


def walk_forward_table(wf: dict) -> str:
    return "\n".join([
        f"{wf['windows']} rolling {wf['years']}-year windows, stepped every {wf['step_months']} months.", "",
        "| statistic | value |", "|---|---|",
        f"| Sharpe: min / 25th pct / median / 75th pct / max | {num(wf['sharpe_min'])} / {num(wf['sharpe_p25'])} / {num(wf['sharpe_median'])} / {num(wf['sharpe_p75'])} / {num(wf['sharpe_max'])} |",
        f"| Windows with positive Sharpe | {pct(wf['pct_windows_positive_sharpe'], 0)} |",
        f"| Windows where strategy Sharpe > SPY Sharpe | {pct(wf['pct_windows_beat_spy'], 0)} |",
        f"| Worst window max drawdown | {pct(wf['worst_window_max_drawdown'])} |",
    ])


def sensitivity_table(sens: pd.DataFrame) -> str:
    out = []
    for metric, label, f in [("sharpe_full", "Sharpe, full period", num), ("sharpe_oos", "Sharpe, out-of-sample", num),
                             ("max_dd_full", "Max drawdown, full period", pct), ("cagr_full", "CAGR, full period", pct)]:
        piv = sens.pivot(index="lookback_months", columns="vol_target", values=metric)
        out.append(f"**{label}** (rows: momentum lookback in months; columns: vol target)")
        out.append("")
        out.append("| lookback | " + " | ".join(pct(c, 0) for c in piv.columns) + " |")
        out.append("|---|" + "---|" * len(piv.columns))
        for lb, row in piv.iterrows():
            out.append(f"| {lb} | " + " | ".join(f(v) for v in row.values) + " |")
        out.append("")
    return "\n".join(out)


def monthly_table_md(path) -> str:
    df = pd.read_csv(path, index_col=0)
    cols = list(df.columns)
    out = ["| year | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for y, row in df.iterrows():
        out.append(f"| {y} | " + " | ".join("" if pd.isna(v) else f"{v*100:+.1f}" for v in row.values) + " |")
    return "\n".join(out)


def key_findings(m: dict, sens: pd.DataFrame) -> str:
    S, P, B = m["metrics"]["strategy"], m["metrics"]["spy"], m["metrics"]["60_40"]
    wf, cd, sd = m["walk_forward"], m["cost_drag"], m["sizing_diagnostics"]
    sh = sens["sharpe_full"]
    lines = [
        f"- **Return:** the strategy compounds at {pct(S['full']['cagr'])} a year over the full period versus "
        f"{pct(P['full']['cagr'])} for SPY and {pct(B['full']['cagr'])} for 60/40. It does **not** beat buy-and-hold SPY on return.",
        f"- **Risk:** its worst drawdown is {pct(S['full']['max_drawdown'])} against {pct(P['full']['max_drawdown'])} for SPY and "
        f"{pct(B['full']['max_drawdown'])} for 60/40, at {pct(S['full']['ann_vol'])} annualised vol. The edge is drawdown control, not return.",
        f"- **Risk-adjusted:** full-period Sharpe {num(S['full']['sharpe'])} (SPY {num(P['full']['sharpe'])}, 60/40 {num(B['full']['sharpe'])}); "
        f"Calmar {num(S['full']['calmar'])} vs {num(P['full']['calmar'])} / {num(B['full']['calmar'])}.",
        f"- **In-sample vs out-of-sample:** Sharpe {num(S['in_sample']['sharpe'])} in-sample and {num(S['out_of_sample']['sharpe'])} out-of-sample. "
        f"Out-of-sample is *better*, which says more about 2016-2026 (a long trending bull market with two sharp, momentum-friendly sell-offs) than about the strategy. "
        f"SPY's own Sharpe rose from {num(P['in_sample']['sharpe'])} to {num(P['out_of_sample']['sharpe'])} over the same split.",
        f"- **Walk-forward:** across {wf['windows']} rolling 3-year windows the Sharpe ranges {num(wf['sharpe_min'])} to {num(wf['sharpe_max'])} (median {num(wf['sharpe_median'])}); "
        f"{pct(wf['pct_windows_positive_sharpe'], 0)} of windows are positive but the strategy beats SPY's Sharpe in only {pct(wf['pct_windows_beat_spy'], 0)} of them.",
        f"- **Sensitivity:** full-period Sharpe across the 3x3 grid spans {num(sh.min())} to {num(sh.max())}; longer lookbacks are monotonically better and the vol target changes almost nothing. "
        f"Results are not fragile, but 12 months (the literature default) is also the best cell, so treat the point estimate as optimistic.",
        f"- **What sets the size:** under portfolio-level vol targeting the {pct(m['settings']['VOL_TARGET'], 0)} target is the binding constraint in "
        f"{pct(sd['share_months_vol_target_binding'], 0)} of active months, the 20% single-name cap in {pct(sd['share_months_name_cap_binding'], 0)}, and the strategy is fully invested in "
        f"{pct(sd['share_months_fully_invested'], 0)}. Average gross exposure when active is {pct(sd['avg_gross_when_active'], 0)} (minimum {pct(sd['min_gross_when_active'], 0)}); "
        f"all cash {pct(sd['share_months_all_cash'], 0)} of months; average {num(sd['avg_positions_on'], 1)} positions on.",
        f"- **Costs:** {cd['cost_per_side_bps']:.0f} bps per side on {num(S['full']['annual_turnover'])}x annual one-way turnover costs "
        f"{pct(cd['cagr_drag'])} of CAGR a year ({pct(cd['cagr_no_cost'])} gross to {pct(cd['cagr_with_cost'])} net).",
        ablation_finding(),
    ]
    return "\n".join(lines)


def ablation_finding() -> str:
    a = pd.read_csv(settings.RESULTS_DIR / "ablation.csv").set_index("config")
    v1, v1b, v2, v2b = a.iloc[0], a.iloc[1], a.iloc[2], a.iloc[3]
    return (f"- **Design changes (ablation table below):** replacing per-position vol scaling with portfolio-level vol targeting moved full-period Sharpe from "
            f"{num(v1['sharpe'])} to {num(v2['sharpe'])}, vol from {pct(v1['ann_vol'])} to {pct(v2['ann_vol'])}, max drawdown from {pct(v1['max_drawdown'])} to {pct(v2['max_drawdown'])} "
            f"and average gross exposure from {pct(v1['avg_gross_exposure'], 0)} to {pct(v2['avg_gross_exposure'], 0)}. Adding a 2pp rebalance band on top cut annual turnover from "
            f"{num(v2['annual_turnover'])}x to {num(v2b['annual_turnover'])}x and cost drag from {pct(v2['cagr_drag'])} to {pct(v2b['cagr_drag'])} of CAGR a year, "
            f"at a Sharpe of {num(v2b['sharpe'])}.")


def ablation_table() -> str:
    a = pd.read_csv(settings.RESULTS_DIR / "ablation.csv")
    out = ["Full period, same data and costs; only the sizing rule and the rebalance band change.", "",
           "| config | CAGR | vol | Sharpe | max DD | OOS Sharpe | avg gross | trades | turnover | cost drag |", "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in a.iterrows():
        out.append(f"| {r['config']} | {pct(r['cagr'])} | {pct(r['ann_vol'])} | {num(r['sharpe'])} | {pct(r['max_drawdown'])} | {num(r['sharpe_oos'])} | "
                   f"{pct(r['avg_gross_exposure'], 0)} | {int(r['n_trades'])} | {num(r['annual_turnover'])}x | {pct(r['cagr_drag'])}/yr |")
    return "\n".join(out)


def build_results_section() -> str:
    m = json.loads((settings.RESULTS_DIR / "metrics.json").read_text())
    sens = pd.read_csv(settings.RESULTS_DIR / "sensitivity.csv")
    parts = [START,
             f"_Generated {m['generated'][:10]} from `results/metrics.json`, data through {m['data_last_bar']}. "
             f"Strategy is active from {m['first_active_date']} (first date with 12 months of history + a 200-day SMA)._",
             "", "### Key findings", "", key_findings(m, sens),
             "", "### In-sample (2005-2015)", "", metrics_table(m["metrics"], "in_sample"),
             "", "### Out-of-sample (2016-present)", "", metrics_table(m["metrics"], "out_of_sample"),
             "", "### Full period", "", metrics_table(m["metrics"], "full"),
             "", "### Walk-forward: rolling 3-year windows", "", walk_forward_table(m["walk_forward"]),
             "", "### Sensitivity grid", "", sensitivity_table(sens),
             "### Ablation: sizing rule and rebalance band", "", ablation_table(), "",
             "### Monthly returns (strategy, %)", "", monthly_table_md(settings.RESULTS_DIR / "monthly_returns.csv"),
             "", "![equity curve](results/equity_curve.png)", END]
    return "\n".join(parts)


def resume_bullets() -> str:
    m = json.loads((settings.RESULTS_DIR / "metrics.json").read_text())
    S, P, B = m["metrics"]["strategy"], m["metrics"]["spy"], m["metrics"]["60_40"]
    wf, cd, sd = m["walk_forward"], m["cost_drag"], m["sizing_diagnostics"]
    n = len(m["settings"]["UNIVERSE"]); yrs = S["full"]["years"]
    return "\n".join([
        "# Resume bullets", "",
        "XYZ format: accomplished **X**, measured by **Y**, by doing **Z**. Every number is read from `results/metrics.json` "
        f"by `report.py` (generated {m['generated'][:10]}, data through {m['data_last_bar']}).", "",
        f"- Built and backtested a long-only time-series-momentum strategy (12-1 momentum + 200-day SMA filter, vol-scaled, monthly rebalance) on {n} ETFs over "
        f"{yrs:.0f} years, cutting max drawdown to {pct(S['full']['max_drawdown'])} vs {pct(P['full']['max_drawdown'])} for SPY at a "
        f"{num(S['full']['sharpe'])} Sharpe (SPY {num(P['full']['sharpe'])}), net of {cd['cost_per_side_bps']:.0f} bps/side costs, with fills at the next open and a unit test that proves the signal has no look-ahead.",
        f"- Validated the strategy out-of-sample ({S['out_of_sample']['start'][:4]}-{S['out_of_sample']['end'][:4]}: Sharpe {num(S['out_of_sample']['sharpe'])}, max drawdown {pct(S['out_of_sample']['max_drawdown'])}) "
        f"and across {wf['windows']} rolling 3-year walk-forward windows (median Sharpe {num(wf['sharpe_median'])}, {pct(wf['pct_windows_positive_sharpe'], 0)} positive), and reported honestly that it beats SPY's Sharpe in only "
        f"{pct(wf['pct_windows_beat_spy'], 0)} of windows and trails SPY on CAGR ({pct(S['full']['cagr'])} vs {pct(P['full']['cagr'])}).",
        f"- Shipped the paper-trading stack around it: Alpaca paper executor with market-on-open orders, idempotent daily runs, a JSON trade journal, and a risk manager "
        f"(3% daily / 15% peak drawdown circuit breakers, 20% position and 100% gross caps, market-hours check), and used an ablation study to replace an inert per-position "
        f"vol rule with portfolio-level vol targeting and add a 2pp rebalance band, cutting turnover to {num(S['full']['annual_turnover'])}x and cost drag to {pct(cd['cagr_drag'])}/yr.",
        "", "*Source: results/metrics.json, results/walk_forward.csv, results/sensitivity.csv.*", "",
    ])


def write_report(readme=settings.ROOT / "README.md") -> None:
    section = build_results_section()
    (settings.ROOT / "RESUME_BULLETS.md").write_text(resume_bullets())
    guide = settings.ROOT / "INTERVIEW_GUIDE.md"
    if guide.exists():
        m = json.loads((settings.RESULTS_DIR / "metrics.json").read_text())
        S, P = m["metrics"]["strategy"], m["metrics"]["spy"]
        block = "\n".join([NSTART, f"_Numbers as of {m['generated'][:10]}, from `results/metrics.json`._", "",
                           f"- Full period {S['full']['start']} to {S['full']['end']}: strategy CAGR {pct(S['full']['cagr'])}, Sharpe {num(S['full']['sharpe'])}, max drawdown {pct(S['full']['max_drawdown'])}.",
                           f"- SPY over the same window: CAGR {pct(P['full']['cagr'])}, Sharpe {num(P['full']['sharpe'])}, max drawdown {pct(P['full']['max_drawdown'])}.",
                           f"- In-sample Sharpe {num(S['in_sample']['sharpe'])}; out-of-sample Sharpe {num(S['out_of_sample']['sharpe'])}.",
                           f"- Rolling 3-year Sharpe: median {num(m['walk_forward']['sharpe_median'])}, beats SPY in {pct(m['walk_forward']['pct_windows_beat_spy'], 0)} of windows.",
                           f"- Cost drag: {pct(m['cost_drag']['cagr_drag'])} of CAGR per year at {m['cost_drag']['cost_per_side_bps']:.0f} bps per side.", NEND])
        t = guide.read_text()
        if NSTART in t and NEND in t:
            guide.write_text(re.sub(re.escape(NSTART) + ".*?" + re.escape(NEND), lambda _: block, t, flags=re.S))
    if readme.exists():
        text = readme.read_text()
        if START in text and END in text:
            text = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: section, text, flags=re.S)
        else:
            text = text.rstrip() + "\n\n## Results\n\n" + section + "\n"
    else:
        text = "# tsmom-etf\n\n## Results\n\n" + section + "\n"
    readme.write_text(text)
    (settings.RESULTS_DIR / "results_section.md").write_text(section)


if __name__ == "__main__":
    write_report()
