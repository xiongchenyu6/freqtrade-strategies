#!/usr/bin/env python3
"""Generate interactive HTML visualizations for a freqtrade backtest.

Uses freqtrade.data.btanalysis to load the latest backtest results, then produces:

- 01_equity_curve.html       — cumulative equity over time
- 02_drawdown.html            — rolling drawdown percentage
- 03_per_pair.html            — profit distribution per pair
- 04_trade_distribution.html  — profit/duration histograms
- 05_monthly_heatmap.html     — calendar-style monthly P&L heatmap
- 06_exit_reasons.html        — breakdown of exit triggers
- 07_rolling_win_rate.html    — 30-day rolling win rate

Usage:
  scripts/visualize_strategy.py                  # auto-pick latest backtest
  scripts/visualize_strategy.py <result_zip>     # specific result
  scripts/visualize_strategy.py --out reports/my_run  # custom out dir
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_DIR = Path(__file__).resolve().parent.parent
FREQTRADE_DIR = Path(os.environ.get("FREQTRADE_DIR", PROJECT_DIR.parent / "freqtrade"))
sys.path.insert(0, str(FREQTRADE_DIR))

from freqtrade.data.btanalysis import load_backtest_data, load_backtest_stats  # noqa: E402


def latest_result(bt_dir: Path) -> Path:
    zips = sorted(bt_dir.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise SystemExit(f"No backtest-result-*.zip in {bt_dir}. Run freqtrade backtesting --export signals first.")
    return zips[0]


def build_equity_curve(trades: pd.DataFrame, starting_balance: float = 10000.0) -> pd.DataFrame:
    """Equity = cumulative sum of profit_abs, sampled daily."""
    t = trades.sort_values("close_date").copy()
    t["equity"] = starting_balance + t["profit_abs"].cumsum()
    t["peak"] = t["equity"].cummax()
    t["drawdown_pct"] = (t["equity"] - t["peak"]) / t["peak"] * 100
    return t


def plot_equity(trades: pd.DataFrame, out: Path):
    t = build_equity_curve(trades)
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        subplot_titles=("Equity Curve (USDT)", "Drawdown (%)"),
    )
    fig.add_trace(go.Scatter(x=t["close_date"], y=t["equity"],
                             mode="lines", line=dict(color="#10b981", width=2),
                             name="Equity", hovertemplate="%{x}<br>$%{y:,.0f}"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=t["close_date"], y=t["peak"],
                             mode="lines", line=dict(color="#6b7280", width=1, dash="dot"),
                             name="Peak", showlegend=True),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=t["close_date"], y=t["drawdown_pct"],
                             mode="lines", fill="tozeroy",
                             line=dict(color="#ef4444", width=1),
                             fillcolor="rgba(239,68,68,0.2)",
                             name="Drawdown %", hovertemplate="%{x}<br>%{y:.1f}%"),
                  row=2, col=1)
    fig.update_layout(
        title=f"Equity Curve — {trades['close_date'].min():%Y-%m-%d} → {trades['close_date'].max():%Y-%m-%d}  "
              f"({len(trades)} trades, final = ${t['equity'].iloc[-1]:,.0f})",
        height=700, template="plotly_dark", hovermode="x unified",
    )
    fig.write_html(out / "01_equity_curve.html")


def plot_drawdown_timeseries(trades: pd.DataFrame, out: Path):
    t = build_equity_curve(trades)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t["close_date"], y=t["drawdown_pct"],
        mode="lines", fill="tozeroy",
        line=dict(color="#ef4444", width=1),
        fillcolor="rgba(239,68,68,0.3)",
        hovertemplate="%{x}<br>DD: %{y:.1f}%",
    ))
    max_dd_idx = t["drawdown_pct"].idxmin()
    max_dd = t.loc[max_dd_idx]
    fig.add_annotation(
        x=max_dd["close_date"], y=max_dd["drawdown_pct"],
        text=f"Max DD: {max_dd['drawdown_pct']:.1f}%<br>{max_dd['close_date']:%Y-%m-%d}",
        showarrow=True, arrowcolor="#ef4444", font=dict(color="#ef4444"),
    )
    fig.update_layout(
        title=f"Rolling Drawdown — worst {max_dd['drawdown_pct']:.1f}% on {max_dd['close_date']:%Y-%m-%d}",
        xaxis_title="Date", yaxis_title="Drawdown (%)",
        height=500, template="plotly_dark",
    )
    fig.write_html(out / "02_drawdown.html")


def plot_per_pair(trades: pd.DataFrame, out: Path):
    by_pair = trades.groupby("pair").agg(
        trades=("pair", "size"),
        total_profit=("profit_abs", "sum"),
        avg_profit_pct=("profit_ratio", lambda x: x.mean() * 100),
        win_rate=("profit_abs", lambda x: (x > 0).mean() * 100),
    ).reset_index().sort_values("total_profit", ascending=False)

    fig = make_subplots(
        rows=1, cols=3, subplot_titles=("Total Profit (USDT)", "Win Rate (%)", "Trade Count"),
    )
    colors = ["#10b981" if v > 0 else "#ef4444" for v in by_pair["total_profit"]]
    fig.add_trace(go.Bar(x=by_pair["pair"], y=by_pair["total_profit"],
                         marker_color=colors, text=by_pair["total_profit"].round(0),
                         textposition="outside", showlegend=False),
                  row=1, col=1)
    fig.add_trace(go.Bar(x=by_pair["pair"], y=by_pair["win_rate"],
                         marker_color="#3b82f6", text=by_pair["win_rate"].round(1),
                         textposition="outside", showlegend=False),
                  row=1, col=2)
    fig.add_trace(go.Bar(x=by_pair["pair"], y=by_pair["trades"],
                         marker_color="#8b5cf6", text=by_pair["trades"],
                         textposition="outside", showlegend=False),
                  row=1, col=3)
    fig.update_layout(title="Per-Pair Breakdown", height=500, template="plotly_dark")
    fig.write_html(out / "03_per_pair.html")


def plot_trade_distribution(trades: pd.DataFrame, out: Path):
    t = trades.copy()
    t["profit_pct"] = t["profit_ratio"] * 100
    t["duration_h"] = (t["close_date"] - t["open_date"]).dt.total_seconds() / 3600
    t["outcome"] = t["profit_abs"].apply(lambda p: "Win" if p > 0 else "Loss")

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Profit Distribution (%)", "Trade Duration (hours)",
            "Profit vs Duration", "Rolling Avg Profit (20-trade)",
        ),
    )
    fig.add_trace(go.Histogram(x=t["profit_pct"], nbinsx=50,
                               marker_color="#3b82f6", showlegend=False), row=1, col=1)
    fig.add_vline(x=0, line_dash="dash", line_color="white", row=1, col=1)

    fig.add_trace(go.Histogram(x=t["duration_h"], nbinsx=50,
                               marker_color="#8b5cf6", showlegend=False), row=1, col=2)
    fig.add_trace(go.Scatter(x=t["duration_h"], y=t["profit_pct"],
                             mode="markers",
                             marker=dict(color=["#10b981" if p > 0 else "#ef4444" for p in t["profit_pct"]],
                                         size=5, opacity=0.6),
                             text=t["pair"], showlegend=False),
                  row=2, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="white", row=2, col=1)

    rolling = t.sort_values("close_date")["profit_pct"].rolling(20, min_periods=5).mean()
    fig.add_trace(go.Scatter(x=t.sort_values("close_date")["close_date"], y=rolling,
                             mode="lines", line=dict(color="#fbbf24", width=2),
                             showlegend=False),
                  row=2, col=2)
    fig.add_hline(y=0, line_dash="dash", line_color="white", row=2, col=2)

    fig.update_xaxes(title_text="Profit %", row=1, col=1)
    fig.update_xaxes(title_text="Hours", row=1, col=2)
    fig.update_xaxes(title_text="Duration (h)", row=2, col=1)
    fig.update_yaxes(title_text="Profit %", row=2, col=1)
    fig.update_yaxes(title_text="Rolling avg %", row=2, col=2)
    fig.update_layout(title="Trade Distributions", height=800, template="plotly_dark")
    fig.write_html(out / "04_trade_distribution.html")


def plot_monthly_heatmap(trades: pd.DataFrame, out: Path):
    t = trades.copy()
    t["year"] = t["close_date"].dt.year
    t["month"] = t["close_date"].dt.month
    pivot = t.groupby(["year", "month"])["profit_abs"].sum().reset_index()
    matrix = pivot.pivot(index="year", columns="month", values="profit_abs").fillna(0)

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    matrix.columns = [months[m - 1] for m in matrix.columns]

    fig = go.Figure(data=go.Heatmap(
        z=matrix.values, x=matrix.columns, y=matrix.index,
        colorscale="RdYlGn", zmid=0,
        text=matrix.round(0).values,
        texttemplate="%{text:.0f}",
        hovertemplate="%{y} %{x}: $%{z:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title="Monthly P&L Heatmap (USDT)",
        xaxis_title="Month", yaxis_title="Year",
        height=max(400, 60 * len(matrix)), template="plotly_dark",
    )
    fig.write_html(out / "05_monthly_heatmap.html")


def plot_exit_reasons(trades: pd.DataFrame, out: Path):
    col = "exit_reason" if "exit_reason" in trades.columns else "sell_reason"
    by_exit = trades.groupby(col).agg(
        count=(col, "size"),
        total_profit=("profit_abs", "sum"),
        avg_profit_pct=("profit_ratio", lambda x: x.mean() * 100),
        win_rate=("profit_abs", lambda x: (x > 0).mean() * 100),
    ).reset_index().sort_values("count", ascending=False)

    fig = make_subplots(rows=1, cols=2, subplot_titles=("Trades by Exit Reason", "Profit by Exit Reason"))
    fig.add_trace(go.Bar(x=by_exit[col], y=by_exit["count"],
                         marker_color="#8b5cf6", text=by_exit["count"],
                         textposition="outside", showlegend=False), row=1, col=1)
    colors = ["#10b981" if v > 0 else "#ef4444" for v in by_exit["total_profit"]]
    fig.add_trace(go.Bar(x=by_exit[col], y=by_exit["total_profit"],
                         marker_color=colors, text=by_exit["total_profit"].round(0),
                         textposition="outside", showlegend=False), row=1, col=2)
    fig.update_layout(title="Exit Reason Analysis", height=500, template="plotly_dark")
    fig.write_html(out / "06_exit_reasons.html")


def plot_rolling_winrate(trades: pd.DataFrame, out: Path):
    t = trades.sort_values("close_date").copy()
    t["is_win"] = (t["profit_abs"] > 0).astype(int)
    for w in (10, 30, 60):
        t[f"wr_{w}"] = t["is_win"].rolling(w, min_periods=3).mean() * 100

    fig = go.Figure()
    colors = {"wr_10": "#fbbf24", "wr_30": "#3b82f6", "wr_60": "#10b981"}
    for w in (10, 30, 60):
        fig.add_trace(go.Scatter(x=t["close_date"], y=t[f"wr_{w}"],
                                 mode="lines", name=f"{w}-trade window",
                                 line=dict(color=colors[f"wr_{w}"], width=2)))
    fig.add_hline(y=50, line_dash="dash", line_color="white",
                  annotation_text="50% (break-even)")
    fig.update_layout(
        title="Rolling Win Rate",
        xaxis_title="Date", yaxis_title="Win Rate %",
        height=500, template="plotly_dark", hovermode="x unified",
    )
    fig.write_html(out / "07_rolling_winrate.html")


def write_index(out: Path, stats_summary: dict):
    cards = "".join(
        f'<div class="card"><div class="label">{k}</div><div class="value">{v}</div></div>'
        for k, v in stats_summary.items()
    )
    links = "\n".join(
        f'<li><a href="{f.name}">{f.name}</a></li>'
        for f in sorted(out.glob("*.html")) if f.name != "index.html"
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Strategy Visualization</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background:#0f172a; color:#e2e8f0; max-width:960px; margin:2rem auto; padding:0 1rem; }}
  h1 {{ border-bottom: 2px solid #334155; padding-bottom: .5rem; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
  .card {{ background:#1e293b; border-left:4px solid #3b82f6; padding:1rem; border-radius:6px; }}
  .label {{ color:#94a3b8; font-size:.85rem; }}
  .value {{ font-size:1.4rem; font-weight:600; color:#f1f5f9; margin-top:.25rem; }}
  ul {{ line-height: 2; }}
  a {{ color:#60a5fa; text-decoration:none; }}
  a:hover {{ color:#93c5fd; text-decoration:underline; }}
</style>
</head><body>
<h1>📊 Strategy Visualization</h1>
<div class="grid">{cards}</div>
<h2>Charts</h2>
<ul>
{links}
</ul>
</body></html>"""
    (out / "index.html").write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("result", nargs="?", help="Path to backtest-result-*.zip (default: latest)")
    ap.add_argument("--bt-dir", default=str(PROJECT_DIR / "user_data" / "backtest_results"))
    ap.add_argument("--out", default=str(PROJECT_DIR / "reports" / "latest"))
    ap.add_argument("--starting-balance", type=float, default=10000.0)
    args = ap.parse_args()

    bt_dir = Path(args.bt_dir)
    result_zip = Path(args.result) if args.result else latest_result(bt_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading: {result_zip}")
    trades = load_backtest_data(str(result_zip))
    print(f"  {len(trades)} trades loaded")

    stats = load_backtest_stats(str(result_zip))
    strat_key = next(iter(stats.get("strategy", {})))
    s = stats["strategy"][strat_key]

    summary = {
        "Strategy": strat_key,
        "Trades": len(trades),
        "Win Rate": f"{(trades['profit_abs'] > 0).mean() * 100:.1f}%",
        "Total Profit": f"${trades['profit_abs'].sum():,.0f}",
        "Return": f"{trades['profit_abs'].sum() / args.starting_balance * 100:+.1f}%",
        "Avg Trade": f"{trades['profit_ratio'].mean() * 100:+.2f}%",
        "Max DD": f"{s.get('max_drawdown_abs', 0):,.0f} ({s.get('max_drawdown', 0) * 100:.1f}%)",
        "Period": f"{trades['close_date'].min():%Y-%m-%d}  →  {trades['close_date'].max():%Y-%m-%d}",
    }

    print("\nGenerating plots:")
    plot_equity(trades, out_dir);           print("  ✓ 01_equity_curve")
    plot_drawdown_timeseries(trades, out_dir); print("  ✓ 02_drawdown")
    plot_per_pair(trades, out_dir);         print("  ✓ 03_per_pair")
    plot_trade_distribution(trades, out_dir); print("  ✓ 04_trade_distribution")
    plot_monthly_heatmap(trades, out_dir);  print("  ✓ 05_monthly_heatmap")
    plot_exit_reasons(trades, out_dir);     print("  ✓ 06_exit_reasons")
    plot_rolling_winrate(trades, out_dir);  print("  ✓ 07_rolling_winrate")
    write_index(out_dir, summary);          print("  ✓ index.html")

    print(f"\nOpen: file://{out_dir.resolve()}/index.html")


if __name__ == "__main__":
    main()
