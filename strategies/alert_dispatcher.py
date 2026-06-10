"""User-facing Telegram alert dispatcher — the retention loop behind /start 订阅.

Two jobs, one loop:
  1. BIND: long-poll Telegram getUpdates for "/start <token>"; match the token to
     quant.telegram_links.link_token and bind that chat_id (web UI shows 已绑定).
     This process is the ONLY getUpdates consumer for @freemanXbtc_bot (the other
     services send only) — do not add a second poller.
  2. FAN OUT: watch for new signal events and push them to subscribed chats:
       'dca_events'    — new quant.event_dca_triggers rows (FLASH/FAST/SUSTAIN/CAPITUL)
       'equity_trades' — quant.nautilus_trades asset_class='equity' opens/closes

Messages are plain-Chinese (glossary tone from /start), always carry a
"不构成投资建议" line, and link back to the dashboard. Tool, not advice.

State (telegram offset + last-seen event timestamps) lives in
~/.config/quant/alert-dispatcher.json so restarts neither replay nor skip.

Env (via sops exec-env secrets.env + EnvironmentFile, mirroring quant-alerts):
  TELEGRAM_BOT_TOKEN   bot token (sops)
  TIMESCALE_URL        postgres DSN for the quant role
  DISPATCH_INTERVAL    seconds between fan-out scans (default 60)

Run: .venv-bots/bin/python strategies/alert_dispatcher.py
All errors are logged and swallowed — an outage must never crash the loop.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DSN = os.environ.get("TIMESCALE_URL", "")
INTERVAL = int(os.environ.get("DISPATCH_INTERVAL", "60"))
STATE_PATH = Path.home() / ".config" / "quant" / "alert-dispatcher.json"
DASH = "https://quant.panda.qzz.io"

KIND_ZH = {
    "FLASH": "闪崩",
    "FAST": "快速下跌",
    "SUSTAIN": "持续阴跌",
    "CAPITUL": "投降式抛售",
}

DISCLAIMER = "\n\n⚠️ 自动信号,不构成投资建议。"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"tg_offset": 0, "last_dca_ts": None, "last_eq_synced": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def tg(method: str, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params, timeout=35)
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError(f"telegram {method}: {d.get('description')}")
    return d["result"]


def send(chat_id: int, text: str) -> bool:
    try:
        tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
           disable_web_page_preview=True)
        return True
    except Exception as e:
        log(f"send to {chat_id} failed: {e!r}")
        return False


def db():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    return conn


# ---------- job 1: bind /start tokens ----------

def poll_bindings(conn, state: dict) -> None:
    """Short getUpdates poll; bind '/start <token>' messages to telegram_links rows."""
    try:
        updates = tg("getUpdates", offset=state["tg_offset"] + 1, timeout=20,
                     allowed_updates=["message"])
    except Exception as e:
        log(f"getUpdates failed: {e!r}")
        return
    for u in updates:
        state["tg_offset"] = max(state["tg_offset"], u["update_id"])
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = (msg.get("chat") or {}).get("id")
        if not chat_id or not text.startswith("/start"):
            continue
        parts = text.split(maxsplit=1)
        token = parts[1].strip() if len(parts) > 1 else ""
        if not token:
            send(chat_id, "你好!请从 quant.panda.qzz.io 的订阅页面点「绑定 Telegram」进入,"
                          "这样我才知道你是谁。")
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE quant.telegram_links
                          SET chat_id = %s, bound_at = now()
                        WHERE link_token = %s
                        RETURNING user_id, topics""",
                    (chat_id, token),
                )
                row = cur.fetchone()
        except Exception as e:
            log(f"bind update failed: {e!r}")
            continue
        if row:
            topics = row[1] or []
            topic_zh = "、".join(
                {"dca_events": "DCA 信号事件", "equity_trades": "美股模拟盘交易"}.get(t, t)
                for t in topics
            ) or "(暂未选择)"
            send(chat_id,
                 f"✅ 绑定成功!已订阅:{topic_zh}\n\n"
                 f"信号触发时会在这里通知你。看不懂信号?先读 {DASH}/start 的信号词典。"
                 f"{DISCLAIMER}")
            log(f"bound chat {chat_id} to user {row[0]}")
        else:
            send(chat_id, "这个绑定链接无效或已过期,请回到网站重新点「绑定 Telegram」。")


# ---------- job 2: fan out new events ----------

def subscribers(conn, topic: str) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chat_id FROM quant.telegram_links WHERE chat_id IS NOT NULL AND %s = ANY(topics)",
            (topic,),
        )
        return [r[0] for r in cur.fetchall()]


def fan_out_dca(conn, state: dict) -> None:
    last = state.get("last_dca_ts")
    with conn.cursor() as cur:
        if last:
            cur.execute(
                "SELECT ts, kind, price, severity, fng, amount_usdt, mode "
                "FROM quant.event_dca_triggers WHERE ts > %s ORDER BY ts", (last,))
        else:
            # First run: don't replay history — just set the high-water mark.
            cur.execute("SELECT max(ts) FROM quant.event_dca_triggers")
            mx = cur.fetchone()[0]
            state["last_dca_ts"] = mx.isoformat() if mx else datetime.now(timezone.utc).isoformat()
            return
        rows = cur.fetchall()
    if not rows:
        return
    chats = subscribers(conn, "dca_events")
    log(f"dca fan-out: {len(rows)} event(s) -> {len(chats)} subscriber(s)")
    for ts, kind, price, severity, fng, amount, mode in rows:
        kz = KIND_ZH.get(kind, kind)
        lines = [f"🔔 <b>DCA 信号:{kz} ({kind})</b>"]
        if price is not None:
            lines.append(f"BTC 价格:${price:,.0f}")
        if fng is not None:
            lines.append(f"恐惧贪婪指数:{fng}(越低越恐慌)")
        if amount is not None:
            lines.append(f"系统响应:计划买入 ${amount:,.0f}({mode or 'dry_run'})")
        lines.append(f"\n这是什么信号?👉 {DASH}/start")
        text = "\n".join(lines) + DISCLAIMER
        for chat in chats:
            send(chat, text)
        state["last_dca_ts"] = ts.isoformat()


def fan_out_equity(conn, state: dict) -> None:
    last = state.get("last_eq_synced")
    with conn.cursor() as cur:
        if last:
            cur.execute(
                "SELECT instrument, is_short, open_date, close_date, open_rate, close_rate, "
                "profit_pct, synced_at FROM quant.nautilus_trades "
                "WHERE asset_class='equity' AND synced_at > %s ORDER BY synced_at", (last,))
        else:
            cur.execute("SELECT max(synced_at) FROM quant.nautilus_trades WHERE asset_class='equity'")
            mx = cur.fetchone()[0]
            state["last_eq_synced"] = mx.isoformat() if mx else datetime.now(timezone.utc).isoformat()
            return
        rows = cur.fetchall()
    if not rows:
        return
    chats = subscribers(conn, "equity_trades")
    log(f"equity fan-out: {len(rows)} trade event(s) -> {len(chats)} subscriber(s)")
    for inst, is_short, od, cd, orate, crate, ppct, synced in rows:
        side = "做空" if is_short else "做多"
        if cd:  # closed round-trip
            ret = f"{ppct * 100:+.2f}%" if ppct is not None else "—"
            text = (f"📈 <b>美股模拟盘平仓:{inst}</b>\n"
                    f"{side} {orate} → {crate},收益 {ret}\n"
                    f"完整记录:{DASH}/nautilus")
        else:
            text = (f"📈 <b>美股模拟盘开仓:{inst}</b>\n"
                    f"{side} @ {orate}(IB 模拟盘,真实信号)\n"
                    f"实时持仓:{DASH}/nautilus")
        text += DISCLAIMER
        for chat in chats:
            send(chat, text)
        state["last_eq_synced"] = synced.isoformat()


def main() -> int:
    if not TOKEN or not DSN:
        print("TELEGRAM_BOT_TOKEN / TIMESCALE_URL required", file=sys.stderr)
        return 2
    state = load_state()
    log(f"alert dispatcher up (interval={INTERVAL}s, state={STATE_PATH})")
    conn = None
    last_fan = 0.0
    while True:
        try:
            if conn is None or conn.closed:
                conn = db()
            poll_bindings(conn, state)  # ~20s long-poll = the loop's natural tick
            if time.time() - last_fan >= INTERVAL:
                fan_out_dca(conn, state)
                fan_out_equity(conn, state)
                last_fan = time.time()
            save_state(state)
        except KeyboardInterrupt:
            save_state(state)
            return 0
        except Exception as e:
            log(f"loop error (continuing): {e!r}")
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
