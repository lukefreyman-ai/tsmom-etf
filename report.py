"""Regenerates the README results tables from results/*. Never type a number into README.md by hand:
everything between <!-- results:start --> and <!-- results:end --> is overwritten by `python run.py backtest`."""
from __future__ import annotations

import json
import re

import pandas as pd

import settings

START, END = "<!-- results:start -->", "<!-- results:end -->"


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


def build_results_section() -> str:
    m = json.loads((settings.RESULTS_DIR / "metrics.json").read_text())
    sens = pd.read_csv(settings.RESULTS_DIR / "sensitivity.csv")
    parts = [START,
             f"_Generated {m['generated'][:10]} from `results/metrics.json`, data through {m['data_last_bar']}. "
             f"Strategy is active from {m['first_active_date']} (first date with 12 months of history + a 200-day SMA)._",
             "", "### In-sample (2005-2015)", "", metrics_table(m["metrics"], "in_sample"),
             "", "### Out-of-sample (2016-present)", "", metrics_table(m["metrics"], "out_of_sample"),
             "", "### Full period", "", metrics_table(m["metrics"], "full"),
             "", "### Walk-forward: rolling 3-year windows", "", walk_forward_table(m["walk_forward"]),
             "", "### Sensitivity grid", "", sensitivity_table(sens),
             "### Monthly returns (strategy, %)", "", monthly_table_md(settings.RESULTS_DIR / "monthly_returns.csv"),
             "", "![equity curve](results/equity_curve.png)", END]
    return "\n".join(parts)


def write_report(readme=settings.ROOT / "README.md") -> None:
    section = build_results_section()
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
