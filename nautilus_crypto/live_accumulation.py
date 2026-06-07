"""Stage 4 (terminal state) — crypto LIVE execution on NautilusTrader.

Runs the SAME Accumulator strategy used in backtest under a live TradingNode against
Binance. This is the freqtrade-replacement for crypto live trading. Defaults to the
Binance **testnet** (no real money) so the execution path — connect, subscribe, order,
fill, reconcile — can be proven before touching mainnet.

Credentials via env (never commit): BINANCE_API_KEY, BINANCE_API_SECRET.
  BINANCE_TESTNET=1 (default) → testnet.binance.vision
  BINANCE_TESTNET=0          → live mainnet (only after long clean testnet/dry-run)

IMPORTANT — key type: Binance + Nautilus require an **Ed25519** API key for EXECUTION.
HMAC-SHA-256 / RSA keys authenticate and load the account but FAIL at the WebSocket
`session.logon` ("HMAC-SHA-256 API key is not supported") — they are deprecated for
trading. Generate an Ed25519 key; BINANCE_API_SECRET is the Ed25519 private key contents:
  export BINANCE_API_SECRET="$(cat binance_ed25519_private.pem)"
Nautilus auto-detects the key type from the secret format.

Get free testnet keys (choose Ed25519) at https://testnet.binance.vision.

Validate wiring without keys (constructs the node, does not connect):
  nautilus_crypto/.../python live_accumulation.py --check
Run against testnet (with keys exported):
  BINANCE_API_KEY=... BINANCE_API_SECRET=... python live_accumulation.py
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
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import BarType

sys.path.insert(0, str(Path(__file__).resolve().parent))
from accumulator import Accumulator, AccumulatorConfig  # noqa: E402

INSTRUMENT = "BTCUSDT.BINANCE"


def build_node() -> TradingNode:
    testnet = os.environ.get("BINANCE_TESTNET", "1") != "0"
    env = BinanceEnvironment.TESTNET if testnet else BinanceEnvironment.LIVE
    # Passed explicitly into the config so the user can use simple env names. A placeholder
    # lets build() validate the full wiring offline; run() (which connects) is gated on real
    # keys in main(), so the placeholder never reaches the network.
    api_key = os.environ.get("BINANCE_API_KEY") or "CHECK_ONLY_NO_CONNECT"
    # Ed25519 secret is a multi-line PEM that doesn't fit an env value, so support a
    # file path (BINANCE_API_SECRET_FILE) for deploy (sops writes the PEM to a file).
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_secret:
        secret_file = os.environ.get("BINANCE_API_SECRET_FILE")
        if secret_file and Path(secret_file).exists():
            api_secret = Path(secret_file).read_text().strip()
    api_secret = api_secret or "CHECK_ONLY_NO_CONNECT"

    provider = InstrumentProviderConfig(load_all=True)
    config = TradingNodeConfig(
        trader_id="ACCUMULATOR-001",
        logging=LoggingConfig(log_level="INFO"),
        data_clients={
            "BINANCE": BinanceDataClientConfig(
                api_key=api_key,
                api_secret=api_secret,
                account_type=BinanceAccountType.SPOT,
                environment=env,
                instrument_provider=provider,
            )
        },
        exec_clients={
            "BINANCE": BinanceExecClientConfig(
                api_key=api_key,
                api_secret=api_secret,
                account_type=BinanceAccountType.SPOT,
                environment=env,
                instrument_provider=provider,
            )
        },
    )

    node = TradingNode(config=config)
    node.add_data_client_factory("BINANCE", BinanceLiveDataClientFactory)
    node.add_exec_client_factory("BINANCE", BinanceLiveExecClientFactory)
    node.build()

    # BINANCE_BAR lets a testnet smoke run use a fast bar (e.g. 1-MINUTE-LAST-EXTERNAL) so
    # the order→fill→reconcile path fires within a minute instead of waiting for a daily close.
    bar_spec = os.environ.get("BINANCE_BAR", "1-DAY-LAST-EXTERNAL")
    instrument = os.environ.get("ACC_INSTRUMENT", INSTRUMENT)
    strategy = Accumulator(AccumulatorConfig(
        instrument_id=instrument,
        bar_type=BarType.from_str(f"{instrument}-{bar_spec}"),
        base_buy_usd=float(os.environ.get("ACC_BASE_BUY_USD", "100")),
        interval_bars=int(os.environ.get("ACC_INTERVAL_BARS", "1")),
        mode=os.environ.get("ACC_MODE", "smart"),
    ))
    node.trader.add_strategy(strategy)
    return node


def main() -> int:
    check_only = "--check" in sys.argv
    _secret_present = bool(
        os.environ.get("BINANCE_API_SECRET")
        or (os.environ.get("BINANCE_API_SECRET_FILE") and Path(os.environ["BINANCE_API_SECRET_FILE"]).exists())
    )
    has_keys = bool(os.environ.get("BINANCE_API_KEY")) and _secret_present

    node = build_node()  # constructing + build() validates the full live wiring offline
    print(f"TradingNode built OK (venue={BINANCE_VENUE}, "
          f"testnet={os.environ.get('BINANCE_TESTNET', '1') != '0'})")

    if check_only or not has_keys:
        if not has_keys:
            print("No BINANCE_API_KEY/SECRET in env → not connecting.")
            print("Get free testnet keys at https://testnet.binance.vision and re-run.")
        node.dispose()
        return 0

    try:
        node.run()
    finally:
        node.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
