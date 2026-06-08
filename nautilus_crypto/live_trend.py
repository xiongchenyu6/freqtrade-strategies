"""Live crypto trend follower on NautilusTrader (Binance) — Donchian breakout, the
recent-regime-validated strategy (see ../STRATEGY_LEADERBOARD.md). One DonchianBreakout
instance per instrument; testnet by default.

Env: BINANCE_API_KEY, BINANCE_API_SECRET or BINANCE_API_SECRET_FILE (Ed25519 PEM),
     BINANCE_TESTNET=1 (default), BINANCE_BAR (default 1-HOUR-LAST-EXTERNAL),
     TREND_INSTRUMENTS (default "ETHUSDT.BINANCE,BTCUSDT.BINANCE,SOLUSDT.BINANCE"),
     TREND_RISK_FRAC (default 0.0667), TREND_ENTRY_LB (168), TREND_EXIT_LB (72).

Validate wiring offline:  python live_trend.py --check
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from nautilus_trader.adapters.binance import BINANCE_VENUE
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig
from nautilus_trader.adapters.binance.factories import (
    BinanceLiveDataClientFactory,
    BinanceLiveExecClientFactory,
)
from nautilus_trader.config import InstrumentProviderConfig, LoggingConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import BarType

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from donchian import DonchianBreakout, DonchianBreakoutConfig  # noqa: E402


def _secret() -> str:
    s = os.environ.get("BINANCE_API_SECRET")
    if not s:
        f = os.environ.get("BINANCE_API_SECRET_FILE")
        if f and Path(f).exists():
            s = Path(f).read_text().strip()
    return s or "CHECK_ONLY_NO_CONNECT"


def build_node() -> TradingNode:
    testnet = os.environ.get("BINANCE_TESTNET", "1") != "0"
    env = BinanceEnvironment.TESTNET if testnet else BinanceEnvironment.LIVE
    api_key = os.environ.get("BINANCE_API_KEY") or "CHECK_ONLY_NO_CONNECT"
    api_secret = _secret()
    provider = InstrumentProviderConfig(load_all=True)

    config = TradingNodeConfig(
        trader_id="TREND-001",
        logging=LoggingConfig(log_level="INFO"),
        data_clients={
            "BINANCE": BinanceDataClientConfig(
                api_key=api_key, api_secret=api_secret,
                account_type=BinanceAccountType.SPOT, environment=env,
                instrument_provider=provider,
            )
        },
        exec_clients={
            "BINANCE": BinanceExecClientConfig(
                api_key=api_key, api_secret=api_secret,
                account_type=BinanceAccountType.SPOT, environment=env,
                instrument_provider=provider,
            )
        },
    )
    node = TradingNode(config=config)
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()

    instruments = os.environ.get(
        "TREND_INSTRUMENTS", "ETHUSDT.BINANCE,BTCUSDT.BINANCE,SOLUSDT.BINANCE"
    ).split(",")
    bar_spec = os.environ.get("BINANCE_BAR", "1-HOUR-LAST-EXTERNAL")
    risk = float(os.environ.get("TREND_RISK_FRAC", "0.0667"))
    entry_lb = int(os.environ.get("TREND_ENTRY_LB", "168"))
    exit_lb = int(os.environ.get("TREND_EXIT_LB", "72"))

    for iid in (s.strip() for s in instruments if s.strip()):
        node.trader.add_strategy(DonchianBreakout(DonchianBreakoutConfig(
            instrument_id=iid,
            bar_type=BarType.from_str(f"{iid}-{bar_spec}"),
            entry_lb=entry_lb, exit_lb=exit_lb, risk_frac=risk,
            order_id_tag=iid.split(".")[0][:8],  # distinct per instance
        )))
    return node


def main() -> int:
    check_only = "--check" in sys.argv
    has_keys = bool(os.environ.get("BINANCE_API_KEY")) and (
        bool(os.environ.get("BINANCE_API_SECRET"))
        or (os.environ.get("BINANCE_API_SECRET_FILE") and Path(os.environ["BINANCE_API_SECRET_FILE"]).exists())
    )
    node = build_node()
    print(f"Trend (Donchian) TradingNode built OK (venue={BINANCE_VENUE}, "
          f"testnet={os.environ.get('BINANCE_TESTNET','1') != '0'})")
    if check_only or not has_keys:
        if not has_keys:
            print("No BINANCE creds in env → not connecting.")
        node.dispose()
        return 0
    try:
        node.run()
    finally:
        node.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
