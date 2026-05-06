#!/usr/bin/env python3
"""
Patch existing reports/*/index.html files with narrative descriptions
for each chart. Preserves stats/summary cards by parsing the existing index.

Run after visualize_strategy.py to add guide narratives without re-running
full backtest regeneration.

Usage:
  python scripts/patch_report_indexes.py                    # patch all reports/*/
  python scripts/patch_report_indexes.py --only pyramid     # just one folder
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_DIR / "reports"

# Description for each numbered chart — stable across all report folders.
# Keys: filename (exact), Value: (emoji, title, zh_description, how_to_read)
CHART_META: dict[str, tuple[str, str, str, str]] = {
    "01_equity_curve.html": (
        "📈", "资金曲线",
        "从起始 $10,000 到最终市值的时间序列。曲线向上 = 累积盈利。",
        "看<b>斜率变化</b>（平缓 / 陡峭 / 下跌）对应市场 regime 切换；"
        "看末端 vs 起点得总 ROI。",
    ),
    "02_drawdown.html": (
        "📉", "回撤时间序列",
        "每一天账户距离历史峰值的百分比。红色区域 = 水下期间。",
        "看最深的那口井 = Max DD；看最宽的红色块 = 最长水下时间。"
        "Phase B 的目标就是压缩这张图的面积。",
    ),
    "03_per_pair.html": (
        "🎯", "每个 Pair 表现",
        "把总盈亏拆到每个交易对 —— 哪个 pair 扛大旗，哪个拖后腿。",
        "如果某个 pair 长期亏损 → 考虑从 whitelist 剔除"
        "（Phase A 就是这么砍掉 DOGE/XRP 的）。",
    ),
    "04_trade_distribution.html": (
        "📊", "交易分布",
        "4 张子图：利润直方图 / 持仓时长 / 利润×时长散点 / 20 笔滚动均值。",
        "看直方图的右尾 —— 趋势策略靠少数大赢家，右尾要够长。"
        "散点图左下密集 = 大部分小亏；右上稀疏点 = 少数大赢。",
    ),
    "05_monthly_heatmap.html": (
        "🗓️", "月度 P&L 热图",
        "每个月的盈亏颜色块。绿 = 赚，红 = 亏，颜色越深越极端。",
        "一眼看出 \"哪几个月吃肉，哪几个月吃土\"。"
        "熊市一大片红不是 bug，是策略特性；连续 3+ 个月亏才要警报。",
    ),
    "06_exit_reasons.html": (
        "🚪", "出场原因拆解",
        "按 exit_reason（trend_exit / stoploss / force_exit / roi）统计每类的盈亏贡献。",
        "健康的趋势策略：<code>trend_exit</code> 贡献 80%+ 盈利；"
        "<code>stoploss</code> 应该是小亏（保命用）而非主盈利方式。",
    ),
    "07_rolling_winrate.html": (
        "🎲", "滚动胜率",
        "10 / 30 / 60 笔滚动窗口的胜率曲线。",
        "趋势策略胜率长期在 30-40%（低胜率、高赔率）。"
        "如果某段时间滚动胜率跌到 < 20% 持续，edge 在衰退。",
    ),
    "08_freqtrade_profit_plot.html": (
        "💰", "Freqtrade 内置利润图",
        "freqtrade plot-profit 产出的官方图，含当前开仓标记。",
        "权威版的资金曲线；和 01_equity_curve 对比验证数据一致性。",
    ),
    "09_btc_candles_with_trades.html": (
        "🕯️", "BTC K 线 + 交易标注",
        "价格蜡烛上画出每笔进/出场点。绿▲ = 买，红▼ = 卖。",
        "逐笔看策略的<b>主观感受</b>：买在哪、卖在哪，是否\"有道理\"？"
        "如果很多交易看起来是买在顶 / 卖在底，规则可能有问题。",
    ),
}

# Per-report-folder context narrative prepended to index page
FOLDER_INTRO: dict[str, tuple[str, str]] = {
    "full_history_btceth": (
        "BTC+ETH 全历史回测（Phase A 前的 baseline）",
        "时间：2017-08 → 2026-04（8.7 年）。这是 Phase A 切到山寨前的旧默认配置，"
        "保留作为对比基准。"
        "新 A5 配置（ETH/BNB/SOL 山寨池）的报告见 <a href='/reports/hyperopted_full_history/'>hyperopted_full_history</a>。",
    ),
    "full_history_btceth_pyramid": (
        "BTC+ETH + Pyramid Winners（加仓机制验证）",
        "在 BTC+ETH 基础上开启 <code>position_adjustment_enable</code>，"
        "盈利达到触发点后加仓。相对单次入场，+41% 额外利润，DD 不涨。",
    ),
    "pyramid": (
        "Pyramid Winners 专题",
        "加仓逻辑的独立回测，验证「只加仓赢家，不 Martingale 亏单」的规则稳定性。",
    ),
    "hyperopted_full_history": (
        "4-Param Hyperopt 最优参数回测",
        "Optuna 100-epoch 跑出来的 pyramid 参数在全历史上的表现。"
        "参数稳定性 + 各 window 表现见 <a href='/docs/HYPEROPT_PYRAMID_TUNING.md'>HYPEROPT_PYRAMID_TUNING.md</a>。",
    ),
    "dca_backtest": (
        "Smart DCA 回测",
        "4 种乘数规则（flat / current / aggressive / fng_only）在 2018-2026 的 BTC 累积对比。",
    ),
}


def extract_stats(html: str) -> list[tuple[str, str]]:
    """Grab the stats cards from existing index.html."""
    pattern = r'<div class="card"><div class="label">([^<]+)</div><div class="value">([^<]+)</div></div>'
    return re.findall(pattern, html)


def build_new_index(folder: Path) -> str:
    folder_name = folder.name
    intro_title, intro_body = FOLDER_INTRO.get(
        folder_name,
        (f"{folder_name}", "（未配置本文件夹的介绍，见 patch_report_indexes.py）"),
    )

    # Try to preserve the stats cards from existing index.html
    existing_index = folder / "index.html"
    stats: list[tuple[str, str]] = []
    if existing_index.exists():
        stats = extract_stats(existing_index.read_text(encoding="utf-8"))

    # Build chart list with narrative
    chart_files = sorted(
        f.name for f in folder.glob("*.html")
        if f.name != "index.html"
    )
    chart_rows = []
    for fname in chart_files:
        meta = CHART_META.get(fname)
        if meta:
            emoji, title, desc, how = meta
            chart_rows.append(f"""
            <div class="chart-row">
              <div class="chart-meta">
                <div class="chart-title"><span class="emoji">{emoji}</span>
                  <a href="{fname}">{title}</a>
                  <span class="fname">{fname}</span></div>
                <div class="chart-desc">{desc}</div>
                <div class="chart-how"><b>怎么看：</b> {how}</div>
              </div>
            </div>""")
        else:
            # Unknown chart (e.g., multiplier_distribution.html which has its own intro)
            chart_rows.append(f"""
            <div class="chart-row">
              <div class="chart-meta">
                <div class="chart-title"><a href="{fname}">{fname}</a></div>
              </div>
            </div>""")
    charts_html = "\n".join(chart_rows)

    stats_cards = "".join(
        f'<div class="stat"><div class="label">{label}</div><div class="value">{val}</div></div>'
        for label, val in stats
    )

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{intro_title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; margin:0; padding:0; line-height:1.6; }}
  .topbar {{ background:#161b22; border-bottom:1px solid #30363d;
            padding:10px 24px; font-size:13px;
            display:flex; justify-content:space-between; align-items:center;
            position:sticky; top:0; z-index:10; }}
  .topbar a {{ color:#58a6ff; text-decoration:none; margin-right:16px; }}
  .topbar a:hover {{ text-decoration:underline; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 28px 24px 80px; }}
  h1 {{ color:#58a6ff; font-size:26px; margin:0 0 8px; }}
  .subtitle {{ color:#8b949e; font-size:14px; margin-bottom:22px; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
           gap:10px; margin:18px 0 28px; }}
  .stat {{ background:#161b22; border:1px solid #30363d; border-left:4px solid #58a6ff;
          padding:12px 14px; border-radius:6px; }}
  .stat .label {{ color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
  .stat .value {{ color:#f0f6fc; font-size:18px; font-weight:600; margin-top:4px; }}
  .chart-row {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
              padding:14px 18px; margin:10px 0; transition:border-color 0.15s; }}
  .chart-row:hover {{ border-color:#58a6ff; }}
  .chart-title {{ display:flex; align-items:center; gap:10px; }}
  .chart-title .emoji {{ font-size:18px; }}
  .chart-title a {{ color:#58a6ff; font-size:16px; font-weight:500; text-decoration:none; }}
  .chart-title a:hover {{ text-decoration:underline; }}
  .chart-title .fname {{ color:#6e7681; font-size:11px; font-family:ui-monospace,monospace;
                        margin-left:auto; }}
  .chart-desc {{ color:#c9d1d9; font-size:13px; margin-top:6px; }}
  .chart-how {{ color:#8b949e; font-size:12px; margin-top:6px; }}
  .chart-how b {{ color:#f0883e; }}
  code {{ background:#0d1117; color:#79c0ff; padding:1px 6px; border-radius:3px; font-size:0.9em; }}
  a {{ color:#58a6ff; }}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <a href="/">🏠 主页</a>
    <a href="/reports/">📈 所有报告</a>
  </div>
  <span style="color:#6e7681">reports/{folder_name}/</span>
</div>
<div class="container">
  <h1>{intro_title}</h1>
  <div class="subtitle">{intro_body}</div>

  {'<div class="stats">' + stats_cards + '</div>' if stats_cards else ''}

  <h2 style="color:#f0f6fc;font-size:18px;margin:28px 0 12px;
             border-bottom:1px solid #21262d;padding-bottom:8px">
    📊 图表导览（每张图都标注了怎么看）
  </h2>

  {charts_html}

  <p style="color:#6e7681;font-size:11px;margin-top:30px">
    图由 <code>scripts/visualize_strategy.py</code> 生成 ·
    索引页由 <code>scripts/patch_report_indexes.py</code> 重写 ·
    想重新生成：<code>python scripts/visualize_strategy.py --out {folder_name}</code>
  </p>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only patch this folder name")
    args = ap.parse_args()

    patched = 0
    # dca_backtest has a custom-made index from backtest_dca.py; don't overwrite
    SKIP = {"dca_backtest"}
    for folder in sorted(REPORTS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if args.only and folder.name != args.only:
            continue
        if folder.name in SKIP and not args.only:
            continue
        # Only patch folders with at least one .html besides index.html
        html_files = [f for f in folder.glob("*.html") if f.name != "index.html"]
        if not html_files:
            continue
        new_html = build_new_index(folder)
        (folder / "index.html").write_text(new_html, encoding="utf-8")
        print(f"  ✓ patched {folder.name}/index.html ({len(html_files)} charts)")
        patched += 1
    print(f"\nPatched {patched} index page(s).")


if __name__ == "__main__":
    main()
