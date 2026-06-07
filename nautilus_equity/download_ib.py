"""Stage 1 — download adjusted US-equity bars from Interactive Brokers into a
ParquetDataCatalog, so the backtest engine can replay real data.

Prerequisites:
  - IB Gateway or TWS running locally and logged in (paper account is fine).
  - API enabled in TWS/Gateway: Settings → API → Enable ActiveX and Socket Clients.
  - Default ports: TWS paper 7497, TWS live 7496, Gateway paper 4002, Gateway live 4001.

IB historical STK bars are split/dividend back-adjusted by default (whatToShow=TRADES,
useRTH controls regular-hours-only) — this is what keeps the backtest honest across
corporate actions (Stage 3 validates with the NVDA 2024 10:1 split).

Run:  nautilus_equity/.venv/bin/python nautilus_equity/download_ib.py
Env:  IB_HOST (default 127.0.0.1), IB_PORT (default 7497), IB_CLIENT_ID (default 5)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
from pathlib import Path

from nautilus_trader.adapters.interactive_brokers.common import IBContract
from nautilus_trader.adapters.interactive_brokers.historical.client import (
    HistoricInteractiveBrokersClient,
)
from nautilus_trader.persistence.catalog import ParquetDataCatalog

# Stage 1 starter pool: two semiconductors + a benchmark ETF. Keep it small until
# the engine→DB→dashboard link is proven; widen the universe later.
TICKERS = [
    ("NVDA", "NASDAQ"),
    ("AMD", "NASDAQ"),
    ("QQQ", "NASDAQ"),  # benchmark / correlation reference
]

CATALOG_PATH = Path(__file__).resolve().parent / "catalog"
BAR_SPECS = ["1-DAY-LAST", "1-HOUR-LAST"]


async def download() -> None:
    host = os.environ.get("IB_HOST", "127.0.0.1")
    port = int(os.environ.get("IB_PORT", "7497"))
    client_id = int(os.environ.get("IB_CLIENT_ID", "5"))

    client = HistoricInteractiveBrokersClient(host=host, port=port, client_id=client_id)
    await client.connect()
    await asyncio.sleep(2)  # let the connection settle

    contracts = [
        IBContract(secType="STK", symbol=sym, exchange="SMART", primaryExchange=prim)
        for sym, prim in TICKERS
    ]

    instruments = await client.request_instruments(contracts=contracts)

    end = dt.datetime.now()
    start = end - dt.timedelta(days=365 * 3)  # 3 years of history
    bars = await client.request_bars(
        bar_specifications=BAR_SPECS,
        start_date_time=start,
        end_date_time=end,
        tz_name="America/New_York",
        contracts=contracts,
        use_rth=True,  # regular trading hours only — cleanest for daily trend logic
    )

    catalog = ParquetDataCatalog(str(CATALOG_PATH))
    catalog.write_data(instruments)
    catalog.write_data(bars)

    print(f"catalog        : {CATALOG_PATH}")
    print(f"instruments    : {len(instruments)}")
    print(f"bars           : {len(bars)}")
    for inst in instruments:
        print(f"  - {inst.id}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(download())
