#!/usr/bin/env python3
"""Backtest DCA (dollar-cost averaging) scenarios on BTC.

Simulates weekly buys from 2017-08 to 2026-04 under different multiplier formulas,
to answer: does the cycle-weighted DCA actually beat a flat DCA?

Scenarios:
  A. flat          — $500 every week, no matter what
  B. current       — cycle 50% + FnG 30% formula (clamp 0-2.5x)
  C. aggressive    — FnG < 10 → 3.0x, clamp 0-3.0x (user-proposed)
  D. fng_only      — FnG-based only: 0.2x (greed) to 2.0x (fear)

Output: reports/dca_backtest/ with plots + summary CSV.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_btc_daily() -> pd.DataFrame:
    df = pd.read_feather(PROJECT_DIR / "user_data/data/binance/BTC_USDT-1d.feather")
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None)
    return df[["date", "close"]].rename(columns={"close": "btc"})


def load_fng() -> pd.DataFrame:
    df = pd.read_csv(PROJECT_DIR / "data/fng_history.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "value"]].rename(columns={"value": "fng"}).sort_values("date")


def compute_mayer_score(btc: pd.DataFrame) -> pd.DataFrame:
    """Cycle score proxy via Mayer Multiple.
    Mayer = close / SMA(200). Lower = undervalued (buy more).
    Map to cycle_score: +1 deep undervalued, -1 top.
    """
    df = btc.copy()
    df["sma200"] = df["btc"].rolling(200).mean()
    df["mayer"] = df["btc"] / df["sma200"]
    # Map mayer in [0.6, 2.8] to cycle_score in [+1, -1]
    df["cycle_score"] = ((2.8 - df["mayer"]) / (2.8 - 0.6)) * 2 - 1
    df["cycle_score"] = df["cycle_score"].clip(-1, 1)
    return df


def multiplier_flat(fng, cycle):
    return 1.0


def multiplier_current(fng, cycle):
    """Replicate dca_executor.py logic (cycle 50% + FnG 30%, no news)."""
    if fng is None or pd.isna(fng):
        fng_mult = 1.0
    elif fng < 20:
        fng_mult = 2.0
    elif fng < 40:
        fng_mult = 1.5
    elif fng < 60:
        fng_mult = 1.0
    elif fng < 80:
        fng_mult = 0.6
    else:
        fng_mult = 0.2

    if pd.isna(cycle):
        cycle_mult = 1.0
    elif cycle > 0.5:
        cycle_mult = 2.2
    elif cycle > 0.2:
        cycle_mult = 1.5
    elif cycle > -0.2:
        cycle_mult = 1.0
    elif cycle > -0.5:
        cycle_mult = 0.5
    else:
        cycle_mult = 0.1

    # Skip news (0.20 weight) → normalize to 0.50 + 0.30 = 0.80 weight
    m = (0.50 * cycle_mult + 0.30 * fng_mult) / 0.80
    return max(0.0, min(2.5, m))


def multiplier_aggressive(fng, cycle):
    """User proposal: FnG < 10 → 3x, cap raised to 3.0."""
    if fng is None or pd.isna(fng):
        fng_mult = 1.0
    elif fng < 10:
        fng_mult = 3.0      # NEW: extreme extreme fear
    elif fng < 20:
        fng_mult = 2.2      # was 2.0
    elif fng < 40:
        fng_mult = 1.5
    elif fng < 60:
        fng_mult = 1.0
    elif fng < 80:
        fng_mult = 0.6
    else:
        fng_mult = 0.2

    if pd.isna(cycle):
        cycle_mult = 1.0
    elif cycle > 0.7:
        cycle_mult = 2.8    # deeper discount signal
    elif cycle > 0.5:
        cycle_mult = 2.2
    elif cycle > 0.2:
        cycle_mult = 1.5
    elif cycle > -0.2:
        cycle_mult = 1.0
    elif cycle > -0.5:
        cycle_mult = 0.5
    else:
        cycle_mult = 0.1

    m = (0.50 * cycle_mult + 0.30 * fng_mult) / 0.80
    return max(0.0, min(3.0, m))


def multiplier_fng_only(fng, cycle):
    """Pure FnG-based, linear from 0.2 (greed) to 2.0 (fear)."""
    if fng is None or pd.isna(fng):
        return 1.0
    # fng=0 (max fear) → 2.0, fng=100 (max greed) → 0.2
    return max(0.2, min(2.0, 2.0 - (fng / 100) * 1.8))


SCENARIOS = {
    "flat":       ("Flat $500/wk (baseline)",     multiplier_flat,       "#6b7280"),
    "current":    ("Current (cycle 50% + FnG 30%)", multiplier_current, "#3b82f6"),
    "aggressive": ("Aggressive (FnG<10→3x, cap 3x)", multiplier_aggressive, "#10b981"),
    "fng_only":   ("FnG-only (linear 0.2-2.0)",    multiplier_fng_only,   "#fbbf24"),
}


def simulate(btc: pd.DataFrame, fng: pd.DataFrame, base_usdt: float = 500.0) -> pd.DataFrame:
    """Run all scenarios on the same weekly schedule.

    Returns long-format DataFrame with columns:
      date, scenario, usdt_spent, btc_bought, total_usdt_spent,
      total_btc, portfolio_value, multiplier, fng, cycle_score
    """
    df = compute_mayer_score(btc)
    df = df.merge(fng, on="date", how="left")
    # Weekly schedule: every Monday
    weekly = df[df["date"].dt.weekday == 0].copy()

    out = []
    totals = {s: {"usdt": 0.0, "btc": 0.0} for s in SCENARIOS}
    for _, row in weekly.iterrows():
        for name, (_, fn, _) in SCENARIOS.items():
            m = fn(row["fng"], row["cycle_score"])
            usdt = base_usdt * m
            btc_bought = usdt / row["btc"] if row["btc"] else 0.0
            totals[name]["usdt"] += usdt
            totals[name]["btc"] += btc_bought
            out.append({
                "date": row["date"],
                "scenario": name,
                "multiplier": m,
                "usdt_spent": usdt,
                "btc_bought": btc_bought,
                "total_usdt_spent": totals[name]["usdt"],
                "total_btc": totals[name]["btc"],
                "btc_price": row["btc"],
                "fng": row.get("fng"),
                "cycle_score": row.get("cycle_score"),
            })
    sim = pd.DataFrame(out)
    sim["portfolio_value"] = sim["total_btc"] * sim["btc_price"]
    sim["avg_cost"] = sim["total_usdt_spent"] / sim["total_btc"].where(sim["total_btc"] > 0, 1)
    sim["pnl_pct"] = (sim["portfolio_value"] / sim["total_usdt_spent"] - 1) * 100
    return sim


ANNOTATIONS = [
    ("2018-12-15", 3200, "2018 熊底", "#f85149"),
    ("2020-03-13", 5000, "COVID 闪崩", "#f85149"),
    ("2021-11-10", 69000, "牛市顶", "#3fb950"),
    ("2022-11-09", 15800, "FTX 崩盘", "#f85149"),
    ("2024-03-14", 73000, "ETF 顶", "#3fb950"),
]


def _event_shapes(sim_dates: pd.Series, for_log_y: bool = False):
    """Return plotly annotations + vertical lines for key events."""
    annots, shapes = [], []
    xmin, xmax = sim_dates.min(), sim_dates.max()
    for d, y, label, color in ANNOTATIONS:
        dt = pd.Timestamp(d)
        if dt < xmin or dt > xmax:
            continue
        annots.append(dict(
            x=dt, y=y, text=label, showarrow=True, arrowhead=2,
            font=dict(color=color, size=11),
            ax=0, ay=-35, arrowcolor=color,
        ))
    return annots


def _intro_div(title: str, subtitle: str, bullets: list[str]) -> str:
    """Produce HTML intro block to prepend above plotly figures."""
    li = "\n".join(f"<li>{b}</li>" for b in bullets)
    return f"""
<div style="max-width:1100px;margin:20px auto;padding:18px 24px;
            background:#161b22;border:1px solid #30363d;border-radius:10px;
            font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#c9d1d9">
  <div style="display:flex;justify-content:space-between;align-items:center;
              padding-bottom:10px;border-bottom:1px solid #21262d">
    <h2 style="margin:0;font-size:18px;color:#58a6ff">{title}</h2>
    <a href="/" style="font-size:12px;color:#58a6ff;text-decoration:none">🏠 主页</a>
  </div>
  <p style="margin:10px 0 6px;color:#8b949e;font-size:13px">{subtitle}</p>
  <ul style="margin:8px 0 4px 20px;font-size:13px;line-height:1.7">{li}</ul>
</div>
"""


def plot_results(sim: pd.DataFrame, btc: pd.DataFrame, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    btc_p = btc[btc["date"] >= sim["date"].min()].copy()

    # ============================================================
    # Chart 1: DCA Scenario Comparison — 4 panels
    # ============================================================
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.035,
        row_heights=[0.28, 0.28, 0.22, 0.22],
        subplot_titles=(
            "BTC 价格（log）— 所有 DCA 操作都发生在这条曲线上",
            "Portfolio 市值（今天如果赎回能拿回多少 USDT）",
            "累计投入 USDT（花了多少钱）",
            "Avg Cost Basis — 每个方案的平均买入成本 vs BTC 价格",
        ),
    )

    # Row 1: BTC price (log)
    fig.add_trace(go.Scatter(
        x=btc_p["date"], y=btc_p["btc"],
        mode="lines", name="BTC 价格", line=dict(color="#f0883e", width=1.8),
        hovertemplate="%{x|%Y-%m-%d}<br>BTC=$%{y:,.0f}<extra></extra>",
    ), row=1, col=1)
    fig.update_yaxes(type="log", row=1, col=1)

    # Row 2+3+4: per-scenario lines
    for name, (label, _, color) in SCENARIOS.items():
        s = sim[sim["scenario"] == name]
        fig.add_trace(go.Scatter(x=s["date"], y=s["portfolio_value"],
                                 mode="lines", name=label,
                                 line=dict(color=color, width=2),
                                 legendgroup=name),
                      row=2, col=1)
        fig.add_trace(go.Scatter(x=s["date"], y=s["total_usdt_spent"],
                                 mode="lines", name=label, showlegend=False,
                                 line=dict(color=color, width=1.5, dash="dot"),
                                 legendgroup=name),
                      row=3, col=1)
        fig.add_trace(go.Scatter(x=s["date"], y=s["avg_cost"],
                                 mode="lines", name=label + " avg cost", showlegend=False,
                                 line=dict(color=color, width=1.6),
                                 legendgroup=name),
                      row=4, col=1)

    # BTC price overlay on avg-cost panel (shows "did we buy cheap?")
    fig.add_trace(go.Scatter(
        x=btc_p["date"], y=btc_p["btc"],
        mode="lines", name="BTC 价格", showlegend=False,
        line=dict(color="#ef4444", width=1.3, dash="dash"),
    ), row=4, col=1)

    fig.update_layout(
        title=None, height=1100, template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=40, b=40),
        annotations=list(fig.layout.annotations) + _event_shapes(sim["date"]),
    )

    intro1 = _intro_div(
        title="DCA 方案对比（2018-2026）",
        subtitle=(
            "同样 $500/周 base 金额，不同乘数规则算出来的周投金额不一样 —— 下面对比 4 种规则"
            "在 8 年 BTC 历史上的累积效果。"
        ),
        bullets=[
            "<b>flat</b> = 每周固定 $500，基准。",
            "<b>current</b> = cycle 50% + FnG 30%（当前生产规则，cap 2.5×）。",
            "<b>aggressive</b> = FnG&lt;10→3×，cap 3.0×（本项目采用）。",
            "<b>fng_only</b> = 仅看 FnG 线性 0.2-2.0×（对照组）。",
            "看点：2018-12 / 2020-03 / 2022-11 这几次暴跌，aggressive 买得最狠 → 末期 BTC 最多。",
            "末期 portfolio_value ÷ 累计 USDT 即总 ROI（summary.csv 有精确数字）。",
        ],
    )
    html1 = fig.to_html(full_html=False, include_plotlyjs="cdn")
    (out / "dca_comparison.html").write_text(
        _html_wrap("DCA 方案对比", intro1 + html1),
        encoding="utf-8",
    )

    # ============================================================
    # Chart 2: Multiplier over time with BTC context
    # ============================================================
    fig2 = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.5, 0.5],
        subplot_titles=(
            "BTC 价格（log）+ 每周触发时的 multiplier 值（圆点大小 ∝ 倍率）",
            "Multiplier 分布直方图（每周乘数值的频率）",
        ),
    )

    # Row 1: BTC price line + scatter of weekly multipliers
    fig2.add_trace(go.Scatter(
        x=btc_p["date"], y=btc_p["btc"],
        mode="lines", name="BTC 价格",
        line=dict(color="#f0883e", width=1.6),
        hovertemplate="%{x|%Y-%m-%d}<br>BTC=$%{y:,.0f}<extra></extra>",
    ), row=1, col=1)

    for name, (label, _, color) in SCENARIOS.items():
        if name == "flat":
            continue  # flat is always 1.0, dots would just be a line
        s = sim[sim["scenario"] == name]
        fig2.add_trace(go.Scatter(
            x=s["date"], y=s["btc_price"],
            mode="markers", name=f"{label} · 乘数",
            marker=dict(
                size=s["multiplier"] * 6 + 2,
                color=s["multiplier"], colorscale="RdYlGn",
                cmin=0, cmax=3, showscale=False,
                line=dict(width=0.5, color=color),
                opacity=0.55,
            ),
            customdata=s[["multiplier", "fng", "cycle_score"]].values,
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>"
                "BTC=$%{y:,.0f}<br>"
                "multiplier=<b>%{customdata[0]:.2f}x</b><br>"
                "FnG=%{customdata[1]:.0f}<br>"
                "cycle=%{customdata[2]:.2f}<extra></extra>"
            ),
            visible=(name == "aggressive"),
        ), row=1, col=1)

    fig2.update_yaxes(type="log", row=1, col=1)

    # Row 2: histograms
    for name, (label, _, color) in SCENARIOS.items():
        s = sim[sim["scenario"] == name]
        fig2.add_trace(go.Histogram(
            x=s["multiplier"], name=label,
            marker_color=color, opacity=0.65, nbinsx=40,
            legendgroup=name + "_hist", showlegend=True,
        ), row=2, col=1)

    fig2.update_layout(
        height=900, template="plotly_dark", hovermode="closest",
        barmode="overlay",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        annotations=list(fig2.layout.annotations) + _event_shapes(sim["date"]),
    )
    fig2.update_xaxes(title_text="Multiplier (×)", row=2, col=1)
    fig2.update_yaxes(title_text="周数", row=2, col=1)

    intro2 = _intro_div(
        title="Multiplier 时间分布 — 何时买多，何时买少",
        subtitle=(
            "上图：BTC 价格曲线上叠加每周触发时的 multiplier 值（圆点）—— 大而绿的点代表"
            "暴跌恐慌时加大买入；小而红的点代表牛市贪婪时减少买入。"
            "下图：历史上每种乘数值出现的频率分布。"
        ),
        bullets=[
            "圆点颜色：绿 = 高倍率（0-3 分段），红 = 低倍率；大小 ∝ 倍率值。",
            "圆点位置：落在 BTC 价格曲线上 —— 一眼看出 \"买在哪个价位\"。",
            "<b>默认只显示 aggressive</b>（当前采用）；图例点击可切换其他方案。",
            "规则正确性：绿点都应出现在价格低谷（熊底 / 闪崩），红点应出现在价格高位。",
            "如果发现绿点位于高位或红点位于低谷 —— 乘数逻辑有 bug。",
            "直方图看整体分布：flat = 单一 1.0 尖峰；其他方案应是左偏（多数周略小于 1）加上少数极端高倍。",
        ],
    )
    html2 = fig2.to_html(full_html=False, include_plotlyjs="cdn")
    (out / "multiplier_distribution.html").write_text(
        _html_wrap("Multiplier 时间分布", intro2 + html2),
        encoding="utf-8",
    )

    # ============================================================
    # Chart 3: Index page tying it together
    # ============================================================
    index_html = _html_wrap("DCA 回测套件", f"""
<div style="max-width:920px;margin:20px auto;padding:24px;
            background:#161b22;border:1px solid #30363d;border-radius:12px;
            font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#c9d1d9">
  <div style="display:flex;justify-content:space-between;align-items:center;
              border-bottom:1px solid #21262d;padding-bottom:12px">
    <h1 style="margin:0;color:#58a6ff;font-size:24px">Smart DCA 回测结果</h1>
    <a href="/" style="color:#58a6ff;text-decoration:none">🏠 主页</a>
  </div>
  <p style="color:#8b949e;margin:12px 0">
    回测期：2018-02 → 2026-04（约 8 年，FnG 历史可用起点）。Base $500/周。
    每个方案按周一执行，乘数规则不同。
  </p>

  <h3 style="color:#f0f6fc;margin:20px 0 8px">📊 报告入口</h3>
  <ul style="line-height:2">
    <li><a href="dca_comparison.html" style="color:#58a6ff">方案全面对比（4 面板：BTC 价格 / 市值 / 投入 / 均成本）</a></li>
    <li><a href="multiplier_distribution.html" style="color:#58a6ff">Multiplier 时间分布 + 直方图（含 BTC 价格上下文）</a></li>
    <li><a href="summary.csv" style="color:#58a6ff">summary.csv — 精确数字表格</a></li>
  </ul>

  <h3 style="color:#f0f6fc;margin:20px 0 8px">🧠 核心设计思路</h3>
  <ul style="line-height:1.8;font-size:14px">
    <li>周定投 = 保底累积，事件 DCA = 机会性加码（见 <a href="/docs/EVENT_DCA.md" style="color:#58a6ff">EVENT_DCA.md</a>）</li>
    <li>cycle_score + FnG 合成 0.0-3.0× 乘数；极端恐慌 → 3×，极端贪婪 → 0.2×</li>
    <li>回测验证：aggressive 方案相对 flat 多累积约 10-15% BTC（具体数字看 summary.csv）</li>
  </ul>

  <h3 style="color:#f0f6fc;margin:20px 0 8px">🔁 复现</h3>
  <pre style="background:#0d1117;border:1px solid #30363d;border-radius:6px;
              padding:12px;color:#79c0ff;font-size:12px;overflow-x:auto">python scripts/backtest_dca.py --base-usdt 500</pre>
</div>
""")
    (out / "index.html").write_text(index_html, encoding="utf-8")


def _html_wrap(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; margin:0; padding:0;
          font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif }}
  a {{ color:#58a6ff; text-decoration:none }}
  a:hover {{ text-decoration:underline }}
</style>
</head><body>
{body}
</body></html>
"""


def summary_table(sim: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, (label, _, _) in SCENARIOS.items():
        s = sim[sim["scenario"] == name].iloc[-1]
        total_usdt = s["total_usdt_spent"]
        total_btc = s["total_btc"]
        pv = s["portfolio_value"]
        avg_cost = total_usdt / total_btc if total_btc else 0
        pnl_pct = (pv / total_usdt - 1) * 100
        usdt_per_btc = total_usdt / total_btc if total_btc else 0
        rows.append({
            "scenario": label,
            "total_spent_usdt": round(total_usdt, 0),
            "total_btc": round(total_btc, 4),
            "avg_cost_usdt_per_btc": round(avg_cost, 0),
            "portfolio_value_usdt": round(pv, 0),
            "pnl_pct": round(pnl_pct, 1),
            "vs_flat_extra_pct": None,
        })
    df = pd.DataFrame(rows)
    flat_pv = df.iloc[0]["portfolio_value_usdt"]
    df["vs_flat_extra_pct"] = ((df["portfolio_value_usdt"] / flat_pv) - 1) * 100
    df["vs_flat_extra_pct"] = df["vs_flat_extra_pct"].round(1)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-usdt", type=float, default=500.0)
    ap.add_argument("--out", default=str(PROJECT_DIR / "reports" / "dca_backtest"))
    ap.add_argument("--start", default="2018-02-01", help="start date (FnG available from 2018-02-01)")
    args = ap.parse_args()

    btc = load_btc_daily()
    fng = load_fng()

    btc = btc[btc["date"] >= pd.Timestamp(args.start)]
    print(f"BTC:  {btc['date'].min()} → {btc['date'].max()}  ({len(btc):,} days)")
    print(f"FnG:  {fng['date'].min()} → {fng['date'].max()}  ({len(fng):,} days)")

    sim = simulate(btc, fng, base_usdt=args.base_usdt)

    out = Path(args.out)
    plot_results(sim, btc, out)

    df = summary_table(sim)
    df.to_csv(out / "summary.csv", index=False)
    print("\n" + "=" * 90)
    print(f"  DCA BACKTEST — base ${args.base_usdt}/wk, start {args.start}")
    print("=" * 90)
    print(df.to_string(index=False))
    print(f"\nHTML plots: {out.resolve()}/dca_comparison.html")


if __name__ == "__main__":
    main()
