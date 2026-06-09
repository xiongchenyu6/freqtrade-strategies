"""Smoke test — prove that a PAPER order reaches IB and FILLS.

Submits ONE tiny market order (BUY 1 share of QQQ) to a logged-in IB Gateway/TWS in
PAPER mode, waits for the execution report, and prints the fill price + paper account.
This is the end-to-end proof that the IB execution path works before wiring the full
HonestTrendEquity live node (live_honest_equity.py).

Uses the raw `ibapi` (TWS API) that the Nautilus IB adapter wraps — the most direct,
dependency-light way to prove a fill. A full TradingNode would also work but adds an
event loop + reconciliation that is overkill for a single-order proof.

HARD GUARDRAIL: PAPER ONLY. This script asserts the connected account starts with "DU"
(IB paper accounts) and ABORTS without placing an order if it does not.

Env (mirrors download_ib.py / live_honest_equity.py):
  IB_HOST       (default 127.0.0.1)
  IB_PORT       (default 4002 = Gateway paper)
  IB_CLIENT_ID  (default 7 — dedicated; data download uses 5)
  IB_SYMBOL     (default QQQ)

Run:  nautilus_equity/.venv/bin/python nautilus_equity/test_ib_paper_order.py
"""

from __future__ import annotations

import os
import threading
import time

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper


class PaperOrderApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.next_order_id: int | None = None
        self.account: str | None = None
        self.contract_details_done = threading.Event()
        self.qualified: Contract | None = None
        self.fill_event = threading.Event()
        self.fill_price: float | None = None
        self.fill_qty: float | None = None
        self.fill_account: str | None = None
        self.last_error: str | None = None
        self._req_id_cd = 1001

    # ---- connection / bookkeeping ----
    def nextValidId(self, orderId: int) -> None:
        self.next_order_id = orderId

    def managedAccounts(self, accountsList: str) -> None:
        # Comma-separated list of accounts the login manages; take the first.
        self.account = accountsList.split(",")[0].strip()

    def error(self, reqId, errorTime, errorCode, errorString,
              advancedOrderRejectJson="") -> None:
        # ibapi 10.x added `errorTime` as the 2nd positional arg.
        # 2104/2106/2158/2107/2119 are benign "data farm connection is OK" notices.
        if errorCode in (2104, 2106, 2158, 2107, 2119):
            return
        msg = f"[error] reqId={reqId} code={errorCode} msg={errorString}"
        print(msg)
        if errorCode not in (2100,):
            self.last_error = msg

    # ---- contract qualification ----
    def contractDetails(self, reqId, contractDetails) -> None:
        # Use the fully-resolved contract (with conId) returned by IB.
        self.qualified = contractDetails.contract

    def contractDetailsEnd(self, reqId) -> None:
        self.contract_details_done.set()

    # ---- execution / fills ----
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld,
                    mktCapPrice) -> None:
        print(f"[orderStatus] id={orderId} status={status} filled={filled} "
              f"remaining={remaining} avgFillPrice={avgFillPrice}")
        if status == "Filled" and float(filled) > 0:
            self.fill_price = float(avgFillPrice)
            self.fill_qty = float(filled)
            self.fill_event.set()

    def execDetails(self, reqId, contract, execution) -> None:
        print(f"[execDetails] {execution.side} {execution.shares} {contract.symbol} "
              f"@ {execution.price} acct={execution.acctNumber} execId={execution.execId}")
        self.fill_price = float(execution.price)
        self.fill_qty = float(execution.shares)
        self.fill_account = execution.acctNumber
        self.fill_event.set()


def main() -> int:
    host = os.environ.get("IB_HOST", "127.0.0.1")
    port = int(os.environ.get("IB_PORT", "4002"))
    client_id = int(os.environ.get("IB_CLIENT_ID", "7"))
    symbol = os.environ.get("IB_SYMBOL", "QQQ")

    app = PaperOrderApp()
    print(f"connecting to {host}:{port} client_id={client_id} ...")
    app.connect(host, port, clientId=client_id)

    # ibapi runs its socket reader on a background thread.
    api_thread = threading.Thread(target=app.run, daemon=True)
    api_thread.start()

    # Wait for the full handshake: serverVersion (set on connectAck) + nextValidId +
    # managedAccounts (proof we are logged in). serverVersion must be set before any
    # request, else ibapi's protobuf path raises on None.
    deadline = time.time() + 30
    while (
        app.serverVersion() is None
        or app.next_order_id is None
        or app.account is None
    ) and time.time() < deadline:
        time.sleep(0.2)
    if app.next_order_id is None or app.serverVersion() is None:
        print("FAIL: handshake incomplete (no serverVersion/nextValidId) — not logged in.")
        app.disconnect()
        return 1
    print(f"connected. serverVersion={app.serverVersion()} account={app.account} "
          f"next_order_id={app.next_order_id}")

    # GUARDRAIL: paper accounts start with 'DU'. Refuse to trade a live account.
    if not app.account or not app.account.startswith("DU"):
        print(f"ABORT: account {app.account!r} is not a paper account (DU*). "
              "Refusing to place an order.")
        app.disconnect()
        return 2

    # Qualify the contract (SMART routed US equity).
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.primaryExchange = "NASDAQ"

    app.reqContractDetails(app._req_id_cd, contract)
    if not app.contract_details_done.wait(timeout=15):
        print("FAIL: contract details timed out.")
        app.disconnect()
        return 1
    use_contract = app.qualified or contract
    print(f"qualified contract: {use_contract.symbol} conId={use_contract.conId} "
          f"exch={use_contract.exchange} primary={use_contract.primaryExchange}")

    # Build a tiny market BUY for 1 share.
    order = Order()
    order.action = "BUY"
    order.orderType = "MKT"
    order.totalQuantity = 1
    order.tif = "DAY"  # ibapi 10.x leaves tif empty by default → IB rejects with 10052
    # Avoid attaching defaults that some IB builds reject on paper.
    order.eTradeOnly = False
    order.firmQuoteOnly = False
    order.transmit = True

    order_id = app.next_order_id
    print(f"placing PAPER order: BUY 1 {symbol} MKT (orderId={order_id}) ...")
    app.placeOrder(order_id, use_contract, order)

    filled = app.fill_event.wait(timeout=60)
    time.sleep(1)  # let execDetails/orderStatus both arrive

    print("=" * 56)
    if filled and app.fill_price:
        acct = app.fill_account or app.account
        print("RESULT: FILLED")
        print(f"  symbol      : {symbol}")
        print(f"  side/qty    : BUY {app.fill_qty}")
        print(f"  fill price  : {app.fill_price}")
        print(f"  account     : {acct}")
        rc = 0
    else:
        print("RESULT: NOT FILLED within timeout")
        if app.last_error:
            print(f"  last error  : {app.last_error}")
        rc = 1
    print("=" * 56)

    app.disconnect()
    time.sleep(0.5)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
