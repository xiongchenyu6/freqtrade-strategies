#!/usr/bin/env python3
"""
Render walk_forward_history/*.json into a single comparison HTML page.

For each (strategy, timeframe), picks the latest run and plots profit per
regime window side-by-side. Useful for "does Phase B actually help during
the LUNA window?" visual comparisons.

Output: reports/walk_forward/index.html
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


PROJECT_DIR = Path(__file__).resolve().parent.parent
WF_DIR = PROJECT_DIR / "walk_forward_history"
OUT_DIR = PROJECT_DIR / "reports" / "walk_forward"

# Narrative per regime window — what was the market doing?
WINDOW_NARRATIVE = {
    "W1_2018_crash": (
        "2018 熊市",
        "BTC 从 $17K → $3K (−76%)。趋势跟随最难的环境 —— 下跌中间的反弹不断"
        "触发假信号。衡量「抗住熊市」的能力。",
    ),
    "W2_2019_accumulation": (
        "2019 底部盘整",
        "BTC $3K → $7K → $7K。低波动低趋势，趋势策略容易被来回打耳光。"
        "衡量「盘整市少交易」的能力。",
    ),
    "W3_2020_covid": (
        "2020 COVID + 恢复",
        "3 月闪崩 50% + V 型反弹后暴涨到年底 $29K。前 3 个月地狱，后 9 个月天堂。",
    ),
    "W4_2021_bull_top": (
        "2021 牛市顶",
        "$29K → $64K → 回撤到 $35K → 再冲 $69K。DeFi/NFT 季。SOL 单独"
        "涨了 100x —— Phase B 的 W4 表现特别亮眼的原因。",
    ),
    "W5_2022_luna_ftx": (
        "2022 LUNA + FTX 双崩",
        "$47K → $16K (−66%)。5 月 LUNA 归零 + 11 月 FTX 爆雷。"
        "长策略地狱。<b>Phase B 期货做空 alpha 在这里最值钱</b>：spot +misc −17% → futures L+S +48%。",
    ),
    "W6_2023_recovery": (
        "2023 复苏",
        "$16K → $42K。低波动 + 稳步上涨。趋势策略的友好环境。",
    ),
    "W7_2024_etf_bull": (
        "2024 ETF 牛市",
        "$42K → $73K → $96K。Jan 11 ETF 批准 + Trump 胜选 Nov。"
        "BTC 领涨，alts 相对落后 → spot BTC 池子比 alts 池子占便宜。",
    ),
    "W8_2025_present": (
        "2025-至今",
        "$96K → $108K → 回撤到 ~$80K。震荡向上。实盘 out-of-sample 窗口。",
    ),
}

STRATEGY_INTRO = {
    "HonestTrend15mDry": (
        "HonestTrend15mDry · spot long-only",
        "ETH/BNB/SOL 15m 趋势跟随 —— Phase A 主力。"
        "参数经 hyperopt 调优（见 HYPEROPT_PYRAMID_TUNING.md）。",
    ),
    "HonestTrend1mLive": (
        "HonestTrend1mLive · spot 1m long-only",
        "1m timeframe 版本。实盘候选，但 walk-forward 显示比 15m 弱（4/8 vs 5/8）"
        " —— 1m 噪音太多吃不到 alpha。",
    ),
    "HonestTrendFutures": (
        "HonestTrendFutures · futures long+short",
        "Phase B 期货对冲。Short 只在 FnG<70 触发，1x 杠杆。"
        "2018-2019 窗口无期货数据，跳过。",
    ),
}

STRATEGY_COLORS = {
    "HonestTrend15mDry":  "#3fb950",
    "HonestTrend1mLive":  "#f0883e",
    "HonestTrendFutures": "#58a6ff",
}


def latest_per_strategy() -> dict[str, dict]:
    """Group JSON files by (strategy, tf), keep most recent."""
    by_key: dict[tuple, tuple[Path, dict]] = {}
    for f in WF_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        key = (data["strategy"], data["timeframe"])
        prev = by_key.get(key)
        if prev is None or data["run_date"] > prev[1]["run_date"]:
            by_key[key] = (f, data)
    return {s: d for (s, _), (_, d) in by_key.items()}


def build_comparison_df(runs: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for strategy, data in runs.items():
        for r in data["results"]:
            rows.append({
                "strategy": strategy,
                "window": r["label"],
                "profit_pct": r.get("tot_profit_pct") if r.get("status") == "ok" else None,
                "trades": r.get("trades") if r.get("status") == "ok" else None,
                "status": r.get("status"),
            })
    return pd.DataFrame(rows)


def build_html(runs: dict[str, dict]) -> str:
    df = build_comparison_df(runs)
    windows = sorted(df["window"].unique())

    # ------- Chart 1: grouped bar, profit% per window per strategy -------
    fig1 = go.Figure()
    for strategy in runs:
        s = df[df["strategy"] == strategy].set_index("window").reindex(windows)
        fig1.add_trace(go.Bar(
            x=windows, y=s["profit_pct"],
            name=strategy,
            marker_color=STRATEGY_COLORS.get(strategy, "#888"),
            text=[f"{v:.1f}%" if pd.notna(v) else "n/a" for v in s["profit_pct"]],
            textposition="outside",
            customdata=s[["trades", "status"]].values,
            hovertemplate=(
                "<b>%{x}</b><br>"
                + strategy + "<br>"
                "Profit: %{y:.2f}%<br>"
                "Trades: %{customdata[0]}<br>"
                "Status: %{customdata[1]}<extra></extra>"
            ),
        ))
    fig1.add_hline(y=0, line_dash="dot", line_color="#8b949e")
    fig1.update_layout(
        title="每个 Regime 窗口的利润对比（%）",
        height=520, template="plotly_dark",
        barmode="group",
        xaxis_title=None, yaxis_title="Profit %",
        legend=dict(orientation="h", y=1.08),
        margin=dict(t=80, b=40),
    )
    chart1 = fig1.to_html(full_html=False, include_plotlyjs="cdn")

    # ------- Chart 2: cumulative profit line -------
    fig2 = go.Figure()
    for strategy in runs:
        s = df[df["strategy"] == strategy].set_index("window").reindex(windows).fillna(0)
        cum = s["profit_pct"].cumsum()
        fig2.add_trace(go.Scatter(
            x=windows, y=cum,
            mode="lines+markers", name=strategy,
            line=dict(color=STRATEGY_COLORS.get(strategy, "#888"), width=2.5),
            marker=dict(size=10),
            hovertemplate=(
                "<b>%{x}</b><br>"
                + strategy + "<br>"
                "Cum profit: %{y:.1f} ppt<extra></extra>"
            ),
        ))
    fig2.add_hline(y=0, line_dash="dot", line_color="#8b949e")
    fig2.update_layout(
        title="累计利润趋势（跨 8 窗口加总，独立本金场景）",
        height=420, template="plotly_dark",
        xaxis_title=None, yaxis_title="Cum Profit (ppt)",
        legend=dict(orientation="h", y=1.12),
        margin=dict(t=80, b=40),
    )
    chart2 = fig2.to_html(full_html=False, include_plotlyjs=False)

    # ------- Strategy intro cards -------
    strat_cards = ""
    for strategy, data in runs.items():
        title, desc = STRATEGY_INTRO.get(
            strategy, (strategy, "")
        )
        profitable = sum(1 for r in data["results"]
                         if r.get("status") == "ok" and (r.get("tot_profit_pct") or 0) > 0)
        ok = sum(1 for r in data["results"] if r.get("status") == "ok")
        color = STRATEGY_COLORS.get(strategy, "#888")
        strat_cards += f"""
        <div class="strat-card" style="border-left-color:{color}">
          <div class="strat-title">{title}</div>
          <div class="strat-desc">{desc}</div>
          <div class="strat-stat">
            Profitable windows: <b>{profitable}/{ok}</b>
            · Run: {data["run_date"][:10]}
          </div>
        </div>
        """

    # ------- Per-window narrative accordion -------
    window_cards = ""
    for w in windows:
        title, story = WINDOW_NARRATIVE.get(w, (w, ""))
        # Collect each strategy's result for this window
        rows = []
        for strategy in runs:
            match = next((r for r in runs[strategy]["results"] if r["label"] == w), None)
            color = STRATEGY_COLORS.get(strategy, "#888")
            if match and match.get("status") == "ok":
                p = match.get("tot_profit_pct", 0)
                t = match.get("trades", 0)
                sign_color = "#3fb950" if p > 0 else "#f85149"
                rows.append(
                    f'<tr><td style="color:{color}">{strategy}</td>'
                    f'<td style="color:{sign_color};text-align:right"><b>{p:+.2f}%</b></td>'
                    f'<td style="text-align:right;color:#8b949e">{t} trades</td></tr>'
                )
            else:
                rows.append(
                    f'<tr><td style="color:{color}">{strategy}</td>'
                    f'<td colspan="2" style="color:#6e7681;font-style:italic">n/a</td></tr>'
                )
        rows_html = "\n".join(rows)
        window_cards += f"""
        <div class="window-card">
          <div class="window-title"><span class="w-label">{w}</span> · {title}</div>
          <div class="window-story">{story}</div>
          <table class="window-table">{rows_html}</table>
        </div>
        """

    # ------- Full page -------
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Walk-Forward 8-Regime 对比</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; margin:0; padding:0;
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; line-height:1.6; }}
  .topbar {{ background:#161b22; border-bottom:1px solid #30363d;
            padding:10px 24px; font-size:13px;
            display:flex; justify-content:space-between; align-items:center;
            position:sticky; top:0; z-index:10; }}
  .topbar a {{ color:#58a6ff; text-decoration:none; margin-right:16px; }}
  .topbar a:hover {{ text-decoration:underline; }}
  .container {{ max-width:1200px; margin:0 auto; padding:24px 20px 60px; }}
  h1 {{ color:#58a6ff; font-size:26px; margin:0 0 6px; }}
  .subtitle {{ color:#8b949e; font-size:14px; margin-bottom:22px; }}

  .strat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
                gap:12px; margin:20px 0 30px; }}
  .strat-card {{ background:#161b22; border:1px solid #30363d; border-left:4px solid #3fb950;
                padding:12px 16px; border-radius:6px; }}
  .strat-title {{ color:#f0f6fc; font-size:14px; font-weight:600; }}
  .strat-desc {{ color:#8b949e; font-size:12px; margin:4px 0 8px; }}
  .strat-stat {{ color:#c9d1d9; font-size:12px; }}

  h2 {{ color:#f0f6fc; font-size:18px; margin:32px 0 10px;
       border-bottom:1px solid #21262d; padding-bottom:6px; }}

  .window-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr));
                 gap:12px; margin-top:16px; }}
  .window-card {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
                 padding:14px 18px; }}
  .window-title {{ color:#f0f6fc; font-size:14px; font-weight:600; margin-bottom:6px; }}
  .w-label {{ color:#58a6ff; font-family:ui-monospace,monospace; font-size:12px;
             background:#0d1117; padding:2px 6px; border-radius:3px; }}
  .window-story {{ color:#c9d1d9; font-size:12.5px; margin-bottom:10px; }}
  .window-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .window-table td {{ padding:4px 6px; border-top:1px dashed #30363d; }}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <a href="/">🏠 主页</a>
    <a href="/reports/">📈 所有报告</a>
    <a href="/docs/WALK_FORWARD_FULL_HISTORY.md">📘 方法论</a>
  </div>
  <span style="color:#6e7681">reports/walk_forward/</span>
</div>
<div class="container">
  <h1>Walk-Forward 8-Regime 对比</h1>
  <div class="subtitle">
    同一套策略在 2018-2026 的 8 个市场周期中分别跑回测，<b>每个窗口独立 $10K 起始本金</b>，
    用来看策略在不同 regime 的稳定性。<br>
    （"累计利润" 是加总假设各窗口独立，不是复合增长，主要用来 rank）
  </div>

  <h2>📊 参与对比的策略</h2>
  <div class="strat-grid">
    {strat_cards}
  </div>

  <h2>📈 每窗口利润对比</h2>
  {chart1}

  <h2>📈 累计利润趋势</h2>
  {chart2}

  <h2>📅 每个窗口的故事（市场当时发生了什么）</h2>
  <div class="window-grid">
    {window_cards}
  </div>

  <h2>🔁 如何重跑</h2>
  <pre style="background:#161b22; border:1px solid #30363d; border-radius:6px;
             padding:12px; color:#79c0ff; font-size:12px; overflow-x:auto">
python scripts/walk_forward_full_history.py \\
  --strategy HonestTrend15mDry \\
  --timeframe 15m \\
  --config configs/backtest/config_backtest_15m_alts_a5.json

# 生成后重新可视化：
python scripts/visualize_walk_forward.py</pre>

  <p style="color:#6e7681;font-size:11px;margin-top:24px">
    JSON 源：<code style="background:#161b22;color:#79c0ff;padding:2px 6px;border-radius:3px">walk_forward_history/*.json</code>
    · 此页由 <code style="background:#161b22;color:#79c0ff;padding:2px 6px;border-radius:3px">scripts/visualize_walk_forward.py</code> 生成
  </p>
</div>
</body>
</html>
"""


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = latest_per_strategy()
    if not runs:
        print("No walk-forward JSON found in walk_forward_history/")
        return
    html = build_html(runs)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    print(f"✓ {OUT_DIR}/index.html  ({len(runs)} strategies)")
    for strategy, data in runs.items():
        profitable = sum(1 for r in data["results"]
                         if r.get("status") == "ok" and (r.get("tot_profit_pct") or 0) > 0)
        ok = sum(1 for r in data["results"] if r.get("status") == "ok")
        print(f"  {strategy}: {profitable}/{ok} profitable windows")


if __name__ == "__main__":
    main()
