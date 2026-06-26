"""Keep the Binance **spot testnet** accumulator funded.

The `nautilus-accumulator` soak is a one-directional smart-DCA: it only ever BUYS
BTC, so it inevitably drains the testnet account's USDT and then every hourly order
rejects with `-2010 insufficient balance`. There is no testnet faucet REST endpoint,
so this job recycles a slice of the *already-accumulated* BTC back into USDT whenever
buying power runs low. Net effect on the soak: none — it just re-accumulates.

Idempotent: most runs are a no-op (USDT above the floor → exit 0, nothing traded).
Only when USDT < MIN_USDT does it market-sell enough BTC to reach TARGET_USDT,
never selling below MIN_BTC_KEEP so the accumulated position is preserved.

Env (sops `secrets.env` on the game box):
  BINANCE_TESTNET_KEY         API key (the same key nautilus-accumulator uses)
  BINANCE_TESTNET_SECRET_B64  base64 of the Ed25519 private-key PEM (multiline → b64)
Optional tuning:
  RECYCLER_MIN_USDT   (default 500)    top up when spot USDT falls below this
  RECYCLER_TARGET_USDT(default 12000)  USDT level to top up to (~250 hourly buys)
  RECYCLER_MIN_BTC_KEEP(default 0.2)   never sell BTC below this remaining balance
  RECYCLER_DRY_RUN    (default "")     "1" → log the intended sell, place no order
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime, timezone

import ccxt


def log(m: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}", flush=True)


def main() -> int:
    key = os.environ.get("BINANCE_TESTNET_KEY", "")
    sec_b64 = os.environ.get("BINANCE_TESTNET_SECRET_B64", "")
    if not key or not sec_b64:
        print("BINANCE_TESTNET_KEY and BINANCE_TESTNET_SECRET_B64 required", file=sys.stderr)
        return 2
    pem = base64.b64decode(sec_b64).decode()

    min_usdt = float(os.environ.get("RECYCLER_MIN_USDT", "500"))
    target_usdt = float(os.environ.get("RECYCLER_TARGET_USDT", "12000"))
    min_btc_keep = float(os.environ.get("RECYCLER_MIN_BTC_KEEP", "0.2"))
    dry_run = os.environ.get("RECYCLER_DRY_RUN", "") == "1"

    ex = ccxt.binance({"apiKey": key, "secret": pem, "options": {"defaultType": "spot"}})
    ex.set_sandbox_mode(True)  # HARD: testnet.binance.vision only
    if "testnet" not in str(ex.urls.get("api", {})):
        print("refusing to run: client is not in testnet/sandbox mode", file=sys.stderr)
        return 3

    bal = ex.fetch_balance()["total"]
    usdt, btc = float(bal.get("USDT", 0)), float(bal.get("BTC", 0))
    log(f"spot balance: USDT={usdt:.2f} BTC={btc:.6f} (floor={min_usdt}, target={target_usdt})")

    if usdt >= min_usdt:
        log("USDT above floor — no action.")
        return 0

    price = float(ex.fetch_ticker("BTC/USDT")["last"])
    need_usdt = target_usdt - usdt
    sell_btc = need_usdt / price
    # never sell below the keep-floor
    sellable = max(0.0, btc - min_btc_keep)
    sell_btc = min(sell_btc, sellable)
    sell_btc = float(ex.amount_to_precision("BTC/USDT", sell_btc))

    if sell_btc <= 0:
        log(f"cannot recycle: BTC={btc:.6f} at/below keep-floor {min_btc_keep} — manual top-up needed.")
        return 1

    if dry_run:
        log(f"DRY_RUN: would market-sell {sell_btc:.6f} BTC (~{sell_btc * price:.0f} USDT).")
        return 0

    o = ex.create_market_sell_order("BTC/USDT", sell_btc)
    log(f"recycled: sold {o.get('filled')} BTC @ {o.get('average')} → +{o.get('cost'):.2f} USDT")
    b1 = ex.fetch_balance()["total"]
    log(f"new spot balance: USDT={float(b1.get('USDT', 0)):.2f} BTC={float(b1.get('BTC', 0)):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
