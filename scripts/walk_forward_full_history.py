#!/usr/bin/env python3
"""Full-history cross-regime walk-forward for HonestTrend.

Divides 2017-08 → present into regime-labeled windows covering every
distinct crypto market environment (2018 crash, 2019 accumulation,
2020 COVID, 2021 bull top, 2022 LUNA/FTX, 2023 recovery, 2024 ETF bull,
2025 current). Reports pass/fail per window + aggregate stats.

Usage: scripts/walk_forward_full_history.py
       scripts/walk_forward_full_history.py --timeframe 1h  # run on 1h instead
       scripts/walk_forward_full_history.py --strategy HonestTrend15mDry --timeframe 15m
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
FREQTRADE_DIR = Path(os.environ.get("FREQTRADE_DIR", PROJECT_DIR.parent / "freqtrade"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("walk_forward_full")

# Regime windows — each is fundamentally different market structure.
# Labels are YYYYMMDD as freqtrade expects.
REGIMES = [
    ("W1_2018_crash",       "20180101", "20181231"),
    ("W2_2019_accumulation","20190101", "20191231"),
    ("W3_2020_covid",       "20200101", "20201231"),
    ("W4_2021_bull_top",    "20210101", "20211231"),
    ("W5_2022_luna_ftx",    "20220101", "20221231"),
    ("W6_2023_recovery",    "20230101", "20231231"),
    ("W7_2024_etf_bull",    "20240101", "20241231"),
    ("W8_2025_present",     "20250101", "20260420"),
]


def run_backtest(strategy: str, config: Path, timeframe: str, tr: str) -> dict | None:
    """Run one freqtrade backtest and parse its summary row."""
    cmd = [
        sys.executable, "-m", "freqtrade", "backtesting",
        "--strategy", strategy,
        "--config", str(config),
        "--datadir", str(PROJECT_DIR / "user_data" / "data" / "binance"),
        "--strategy-path", str(PROJECT_DIR / "strategies"),
        "--timeframe", timeframe,
        "--timerange", tr,
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{FREQTRADE_DIR}{os.pathsep}{existing}" if existing else str(FREQTRADE_DIR)
    log.info(f"  running: {tr} ({timeframe})")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, env=env, cwd=str(FREQTRADE_DIR))
    except subprocess.TimeoutExpired:
        log.error(f"  timeout on {tr}")
        return None

    # Freqtrade uses rich table: ┃ strategy │ trades │ avg_profit │ tot_profit_USDT │ tot_profit_pct │ ...
    # Parse strategy summary row (single-strategy run has no TOTAL line).
    row_re = re.compile(
        r"[\u2503\u2502\|]\s*" + re.escape(strategy) +
        r"\s*[\u2503\u2502\|]\s*(-?\d+)\s*[\u2503\u2502\|]\s*(-?\d+\.\d+)\s*[\u2503\u2502\|]\s*"
        r"(-?\d+\.\d+)\s*[\u2503\u2502\|]\s*(-?\d+\.\d+)"
    )
    for line in out.stdout.splitlines():
        m = row_re.search(line)
        if m:
            trades, avgp_pct, tot_usdt, tot_pct = m.groups()
            return {
                "trades": int(trades),
                "avg_profit_pct": float(avgp_pct),
                "tot_profit_usdt": float(tot_usdt),
                "tot_profit_pct": float(tot_pct),
            }

    # Fallback: "Absolute profit" line
    for line in out.stdout.splitlines():
        m = re.search(r"Absolute profit\s*[\u2502\|]\s*(-?[\d.]+)\s*USDT", line)
        if m:
            return {
                "trades": 0,
                "avg_profit_pct": 0.0,
                "tot_profit_usdt": float(m.group(1)),
                "tot_profit_pct": 0.0,
            }

    log.warning(f"  could not parse result for {tr}")
    (PROJECT_DIR / "logs").mkdir(exist_ok=True)
    dump = PROJECT_DIR / "logs" / f"walkforward_debug_{tr.replace('-', '_')}.log"
    dump.write_text(out.stdout + "\n---STDERR---\n" + out.stderr)
    log.warning(f"  debug dumped to {dump}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="HonestTrend1mLive")
    ap.add_argument("--timeframe", default="1m")
    ap.add_argument("--config", default=None, help="path to backtest config json")
    args = ap.parse_args()

    if args.config:
        config = Path(args.config).resolve()
    else:
        candidates = [
            PROJECT_DIR / "configs" / "backtest" / f"config_backtest_{args.timeframe}.json",
            PROJECT_DIR / "configs" / "backtest" / "config_backtest_honest.json",
            PROJECT_DIR / "configs" / "backtest" / "config_backtest.json",
        ]
        config = next((c for c in candidates if c.exists()), None)
        if not config:
            log.error(f"No backtest config found for {args.timeframe}")
            return 1
        config = config.resolve()

    log.info(f"Strategy: {args.strategy}")
    log.info(f"Timeframe: {args.timeframe}")
    log.info(f"Config: {config}")

    results = []
    for label, start, end in REGIMES:
        log.info(f"{label}: {start} → {end}")
        r = run_backtest(args.strategy, config, args.timeframe, f"{start}-{end}")
        if r is None:
            results.append({"label": label, "start": start, "end": end, "status": "failed"})
        else:
            r.update({"label": label, "start": start, "end": end, "status": "ok"})
            results.append(r)
            log.info(f"  → trades={r['trades']} profit={r['tot_profit_pct']:+.2f}%")

    # Save JSON
    out_dir = PROJECT_DIR / "walk_forward_history"
    out_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_file = out_dir / f"full_history_{args.strategy}_{args.timeframe}_{today}.json"
    out_file.write_text(json.dumps({
        "strategy": args.strategy,
        "timeframe": args.timeframe,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }, indent=2))

    # Report
    ok = [r for r in results if r["status"] == "ok"]
    positive = sum(1 for r in ok if r.get("tot_profit_pct", 0) > 0)
    n = len(ok)

    print("\n" + "=" * 68)
    print(f"  FULL-HISTORY WALK-FORWARD — {args.strategy} ({args.timeframe})")
    print("=" * 68)
    print(f"{'Window':<24} {'Range':<20} {'Trades':>7} {'Profit %':>12}")
    print("-" * 68)
    for r in results:
        sym = "✓" if r.get("tot_profit_pct", 0) > 0 else ("✗" if r.get("status") == "ok" else "?")
        rng = f"{r['start']}→{r['end']}"
        trades = r.get("trades", 0)
        pct = r.get("tot_profit_pct", 0.0)
        print(f"{sym} {r['label']:<22} {rng:<20} {trades:>7} {pct:>+11.2f}%")
    print("-" * 68)
    print(f"Profitable windows: {positive}/{n}   (edge check: need ≥ {n//2 + 1}/{n})")
    print(f"JSON saved: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
