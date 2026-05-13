"""
Telegram Alert System

1. KOL real-time alerts — when Trump/Musk/BlackRock moves, get notified fast
2. Sentiment shift alerts — when combined_score changes significantly
3. Bot health watchdog — alert if freqtrade process dies

Run every 30 min via systemd timer (separate from the 4-hour pipeline).
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("alerts")

# Load from env or SOPS
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PROJECT_DIR = Path(__file__).parent.parent

# State file to track what we've already alerted on
STATE_FILE = PROJECT_DIR / "sentiment_data" / "alert_state.json"


def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        # Try loading from SOPS
        _load_telegram_from_sops()

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def _load_telegram_from_sops():
    """Try to load Telegram credentials from SOPS."""
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    try:
        result = subprocess.run(
            ["sops", "decrypt", str(PROJECT_DIR / "secrets.yaml")],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            import yaml
            secrets = yaml.safe_load(result.stdout)
            TELEGRAM_TOKEN = secrets.get("telegram", {}).get("bot_token", "")
            TELEGRAM_CHAT_ID = secrets.get("telegram", {}).get("chat_id", "")
    except Exception:
        pass


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_kol_hashes": [], "last_combined_score": 0.0, "last_check": ""}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# --------------------------------------------------------------------------
# Alert 1: KOL Events
# --------------------------------------------------------------------------
def check_kol_alerts():
    """Check for new high-impact KOL events and alert."""
    from kol_tracker import KOLTracker

    state = load_state()
    seen = set(state.get("last_kol_hashes", []))

    tracker = KOLTracker()
    result = tracker.run()

    new_alerts = []
    new_hashes = []

    for m in result.get("kol_mentions", []):
        # Only alert on significant mentions
        if abs(m.get("score", 0)) < 0.3:
            continue

        # Deduplicate by title hash
        import hashlib
        h = hashlib.sha256(m["title"].lower().strip().encode()).hexdigest()[:16]
        new_hashes.append(h)

        if h in seen:
            continue

        icon = "🟢" if m["score"] > 0 else "🔴"
        title = m["title"][:140]
        # Escape Markdown special chars in title (underscores, asterisks, brackets)
        for ch in ("_", "*", "[", "]", "`"):
            title = title.replace(ch, f"\\{ch}")
        link = m.get("link", "").strip()
        if link:
            # Markdown inline link: [title](url) — user can tap to verify original
            title_line = f"[{title}]({link})"
        else:
            title_line = title
        new_alerts.append(
            f"{icon} *{m['kol'].upper()}* ({m['score']:+.2f})\n{title_line}"
        )

    if new_alerts:
        header = f"*KOL Alert* ({len(new_alerts)} new events)\n{'─' * 30}\n"
        message = header + "\n\n".join(new_alerts[:5])  # max 5 per alert
        send_telegram(message)
        logger.info(f"Sent {len(new_alerts)} KOL alerts")

    # Update state
    state["last_kol_hashes"] = new_hashes[-50:]  # keep last 50
    save_state(state)

    return len(new_alerts)


# --------------------------------------------------------------------------
# Alert 2: Sentiment Shift
# --------------------------------------------------------------------------
def check_sentiment_shift():
    """Alert when combined_score changes significantly."""
    state = load_state()
    last_score = state.get("last_combined_score", 0.0)

    # Read latest
    sentiment_file = PROJECT_DIR / "sentiment_data" / "latest_sentiment.json"
    try:
        with open(sentiment_file) as f:
            data = json.loads(f.read())
        current_score = data.get("combined_score", 0.0)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    delta = current_score - last_score

    # Alert on significant shifts (> 0.2 change)
    if abs(delta) > 0.2:
        direction = "📈 BULLISH" if delta > 0 else "📉 BEARISH"
        message = (
            f"*Sentiment Shift* {direction}\n"
            f"{'─' * 30}\n"
            f"Score: {last_score:+.2f} → *{current_score:+.2f}* ({delta:+.2f})\n"
            f"FnG: {data.get('fng_value', '?')} ({data.get('fng_classification', '?')})\n"
            f"KOL: {data.get('kol_score', 0):+.2f} ({data.get('kol_mentions', 0)} mentions)\n"
            f"Signal: *{data.get('signal', '?').upper()}*"
        )
        send_telegram(message)
        logger.info(f"Sentiment shift alert: {last_score:+.2f} → {current_score:+.2f}")

    # Also alert on regime change
    if current_score > 0.3 and last_score <= 0.3:
        send_telegram("*Regime Change*: → BULLISH 🟢\nSentiment crossed above +0.3 threshold")
    elif current_score < -0.3 and last_score >= -0.3:
        send_telegram("*Regime Change*: → BEARISH 🔴\nSentiment crossed below -0.3 threshold")

    state["last_combined_score"] = current_score
    save_state(state)


# --------------------------------------------------------------------------
# Alert 3: Bot Health (auto-restart + cooldown)
# --------------------------------------------------------------------------
#
# Old behavior: every 30 min, fire the same "Bot Down" alert. Useless after
# the first one. New behavior:
#  - On detection of a missing process, try to relaunch the bot exactly once,
#    then re-pgrep ~3s later to confirm it took.
#  - Only re-alert if (a) this is the first time we've seen it down since the
#    last healthy check, OR (b) at least HEALTH_RE_ALERT_HOURS have elapsed
#    since the last alert.
#  - Alerts now include what the restart attempt did so the user knows whether
#    to manually intervene.
HEALTH_RE_ALERT_HOURS = 6


def _restart_freqtrade() -> tuple[bool, str]:
    """Best-effort relaunch of `freqtrade trade`. Returns (started, detail).

    The command and config are configurable via env so this stays generic:
      - FREQTRADE_TRADE_CMD   full shell command; takes priority if set
      - FREQTRADE_TRADE_CONFIG  config path; default = configs/config_dryrun_honest15m.json
      - FREQTRADE_TRADE_USERDIR userdir; default = user_data
      - FREQTRADE_PYTHON       python interpreter; default = python (whatever's on PATH)

    NixOS user services need `/run/current-system/sw/bin` in PATH or `nohup`,
    `python`, etc. won't resolve — we explicitly extend PATH for that reason.
    """
    cmd = os.environ.get("FREQTRADE_TRADE_CMD", "")
    if not cmd:
        py = os.environ.get("FREQTRADE_PYTHON", "python")
        cfg = os.environ.get(
            "FREQTRADE_TRADE_CONFIG", "configs/config_dryrun_honest15m.json"
        )
        userdir = os.environ.get("FREQTRADE_TRADE_USERDIR", "user_data")
        log_path = PROJECT_DIR / "user_data" / "logs" / "freqtrade-autorestart.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            f"nohup {py} -m freqtrade trade -c {cfg} --userdir {userdir} "
            f">> {log_path} 2>&1 &"
        )

    env = os.environ.copy()
    extra_path = "/run/current-system/sw/bin"
    if extra_path not in env.get("PATH", "").split(":"):
        env["PATH"] = extra_path + ":" + env.get("PATH", "")

    try:
        subprocess.Popen(
            ["bash", "-lc", cmd],
            cwd=str(PROJECT_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return False, f"launch failed: {e}"

    # Give it a moment to fork past the bash wrapper, then check.
    time.sleep(3)
    probe = subprocess.run(
        ["pgrep", "-f", "freqtrade trade"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        return True, f"restarted (PID={probe.stdout.strip()})"
    return False, "still not running after launch"


def check_bot_health() -> bool:
    """Detect missing freqtrade trade process, try to auto-restart, alert with cooldown."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "freqtrade trade"], capture_output=True, text=True
        )
    except Exception as e:
        logger.warning(f"Health check failed: {e}")
        return False

    state = load_state()
    now = time.time()

    if result.returncode == 0:
        logger.info(f"Bot healthy, PID={result.stdout.strip()}")
        # Clear the down-state so the next outage alerts immediately.
        if state.get("bot_down_since") or state.get("last_health_alert_ts"):
            state["bot_down_since"] = 0
            state["last_health_alert_ts"] = 0
            save_state(state)
        return True

    # --- bot is down ---
    if not state.get("bot_down_since"):
        state["bot_down_since"] = now

    started, detail = _restart_freqtrade()
    if started:
        # Restart worked — tell the user once and clear cooldown.
        send_telegram(
            "*Bot Recovered* ✅\n"
            "Freqtrade was down; auto-restart succeeded.\n"
            f"`{detail}`"
        )
        state["bot_down_since"] = 0
        state["last_health_alert_ts"] = 0
        save_state(state)
        logger.info(f"Bot auto-restarted: {detail}")
        return True

    # Restart failed — apply cooldown so we don't spam.
    last_alert = state.get("last_health_alert_ts", 0)
    cooldown_s = HEALTH_RE_ALERT_HOURS * 3600
    if last_alert and (now - last_alert) < cooldown_s:
        next_in_min = int((cooldown_s - (now - last_alert)) / 60)
        logger.info(
            f"Bot DOWN, restart failed ({detail}); suppressed (next alert in ~{next_in_min}m)"
        )
        return False

    down_for_min = int((now - state["bot_down_since"]) / 60)
    send_telegram(
        "*Bot Down* ⚠️\n"
        "Freqtrade is not running and auto-restart failed.\n"
        f"Down for: {down_for_min}m\n"
        f"Attempt: `{detail}`\n"
        "Investigate logs at `user_data/logs/freqtrade-autorestart.log`."
    )
    state["last_health_alert_ts"] = now
    save_state(state)
    logger.warning(f"Bot DOWN — alert sent (restart failed: {detail})")
    return False


# --------------------------------------------------------------------------
# Helper: per-strategy Kelly verdict
# --------------------------------------------------------------------------
# The Kelly sizer (strategies/kelly_sizer.py) lazy-loads per-strategy stats
# during bot_loop_start; once that's done they live only in the bot process
# memory. This helper recomputes the same stats on demand so the daily
# Telegram report and the --kelly CLI can both surface them.
_KELLY_TRACKED_STRATEGIES = [
    "HonestTrend15mDry",
    "HonestTrend15mProtections",
    "HonestTrend1mLive",
    "HonestTrend1mMTF",
    "HonestTrendFutures",
]


def kelly_status_dict() -> dict:
    """Return Kelly status for tracked strategies as a serialisable dict.

    Shape (one entry per strategy):
      {
        "generated_at": "2026-05-13T09:30:00Z",
        "min_trades_for_kelly": 30,
        "wilson_z": 1.96,
        "strategies": [
          {"name": "...", "status": "ok|negative_edge|insufficient_n|no_data",
           "win_rate": 0.33, "payoff_ratio": 2.18, "n_trades": 570,
           "f_half_point": 0.0125, "f_half_shrunk": 0.0, "verdict": "<text>"}
        ]
      }

    This is the machine-readable counterpart of format_kelly_report() — same
    underlying data, useful for dashboards, monitoring, or piping to jq.
    """
    sys.path.insert(0, str(PROJECT_DIR / "strategies"))
    try:
        from kelly_sizer import (
            MIN_TRADES_FOR_KELLY,
            WILSON_Z,
            latest_strategy_stats,
        )
    except Exception as e:
        logger.debug(f"Kelly status skipped (import failed): {e}")
        return {"error": f"import failed: {e}", "strategies": []}

    strategies = []
    for name in _KELLY_TRACKED_STRATEGIES:
        entry: dict = {"name": name}
        try:
            stats = latest_strategy_stats(name)
        except Exception as e:
            stats = None
            entry["error"] = str(e)
        if stats is None:
            entry["status"] = "no_data"
            entry["verdict"] = "no recent backtest"
            strategies.append(entry)
            continue
        f_half_point = stats.half_kelly_clamped(use_lower_bound=False)
        f_half_shrunk = stats.half_kelly_clamped(use_lower_bound=True)
        entry.update(
            win_rate=round(stats.win_rate, 4),
            payoff_ratio=round(stats.payoff_ratio, 4),
            n_trades=stats.n_trades,
            f_half_point=round(f_half_point, 6),
            f_half_shrunk=round(f_half_shrunk, 6),
        )
        if stats.profit_total_pct is not None:
            entry["profit_total_pct"] = round(stats.profit_total_pct, 2)
        if stats.backtest_start:
            entry["backtest_start"] = stats.backtest_start
        if stats.backtest_end:
            entry["backtest_end"] = stats.backtest_end
        if stats.n_trades < MIN_TRADES_FOR_KELLY:
            entry["status"] = "insufficient_n"
            entry["verdict"] = f"n={stats.n_trades} below {MIN_TRADES_FOR_KELLY} → fallback"
        elif f_half_shrunk == 0:
            entry["status"] = "negative_edge"
            entry["verdict"] = (
                f"negative edge after Wilson shrinkage "
                f"(point f½={f_half_point * 100:.2f}%)"
            )
        else:
            entry["status"] = "ok"
            entry["verdict"] = (
                f"size {f_half_shrunk * 100:.2f}% per trade "
                f"(point f½ {f_half_point * 100:.2f}%)"
            )
        strategies.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "min_trades_for_kelly": MIN_TRADES_FOR_KELLY,
        "wilson_z": WILSON_Z,
        "strategies": strategies,
    }


def _format_kelly_entry(e: dict) -> str:
    name = e["name"]
    status = e.get("status")
    if status == "no_data":
        return f"  {name}: _no recent backtest_"
    if status == "insufficient_n":
        return f"  {name}: n={e['n_trades']} — _below {e.get('_min_trades', '?')}, fallback_"
    if status == "negative_edge":
        return (
            f"  {name}: ⛔ negative edge after shrinkage "
            f"(point f½={e['f_half_point'] * 100:.2f}% → 0 after Wilson; "
            f"p={e['win_rate']:.2f} b={e['payoff_ratio']:.2f} n={e['n_trades']})"
        )
    if status == "ok":
        return (
            f"  {name}: ✅ {e['f_half_shrunk'] * 100:.2f}% per trade "
            f"(point f½ would be {e['f_half_point'] * 100:.2f}%; "
            f"p={e['win_rate']:.2f} b={e['payoff_ratio']:.2f} n={e['n_trades']})"
        )
    return f"  {name}: {e.get('verdict', '?')}"


def format_kelly_report() -> str:
    """Return a Markdown block summarising Kelly stats for tracked strategies.

    Empty string if no strategies have a recent backtest — keeps the daily
    report short when there's nothing useful to say.
    """
    payload = kelly_status_dict()
    strategies = payload.get("strategies", [])
    if not strategies:
        return ""
    min_n = payload.get("min_trades_for_kelly")
    rows = []
    for e in strategies:
        if "_min_trades" not in e and min_n is not None:
            e["_min_trades"] = min_n
        rows.append(_format_kelly_entry(e))
    return "\n*Kelly Sizing:*\n" + "\n".join(rows)


def write_kelly_status_json(target: Path) -> Path:
    """Compute Kelly status and write it as JSON to ``target``.

    Used by the daily report path so external consumers (dashboard, monitoring,
    jq pipelines) get a fresh snapshot once a day without having to invoke
    the Python directly.
    """
    payload = kelly_status_dict()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))
    return target


# --------------------------------------------------------------------------
# Alert 4: Daily Report
# --------------------------------------------------------------------------
def send_daily_report():
    """
    Send daily summary: portfolio status, sentiment, KOL activity.
    Call once per day (e.g., via --daily flag or at 00:00 UTC).
    """
    state = load_state()
    last_report = state.get("last_daily_report", "")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if last_report == today:
        logger.info("Daily report already sent today")
        return

    # Gather sentiment data
    sentiment_file = PROJECT_DIR / "sentiment_data" / "latest_sentiment.json"
    try:
        with open(sentiment_file) as f:
            s = json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}

    fng = s.get("fng_value", "?")
    fng_class = s.get("fng_classification", "?")
    score = s.get("combined_score", 0)
    kol = s.get("kol_score", 0)
    kol_n = s.get("kol_mentions", 0)
    btc = s.get("btc_price", 0)

    # Get Supabase history
    history_str = ""
    try:
        import os
        su = os.environ.get("SUPABASE_URL", "")
        sk = os.environ.get("SUPABASE_KEY", "")
        if su and sk:
            resp = requests.get(
                f"{su}/rest/v1/sentiment_snapshots",
                headers={"apikey": sk, "Authorization": f"Bearer {sk}"},
                params={"select": "combined_score,signal", "order": "timestamp.desc", "limit": "6"},
                timeout=10,
            )
            if resp.status_code == 200:
                hist = resp.json()
                trend = " → ".join(f"{h['combined_score']:+.2f}" for h in reversed(hist))
                history_str = f"\nTrend (24h): {trend}"
    except Exception:
        pass

    # Get bot status via freqtrade API
    bot_status = ""
    try:
        ft_user = os.environ.get("FREQTRADE_API_USER", "freqtrader")
        ft_pass = os.environ.get("FREQTRADE_API_PASSWORD", "")
        r = requests.get("http://127.0.0.1:8080/api/v1/profit", timeout=5,
                        auth=(ft_user, ft_pass))
        if r.status_code == 200:
            p = r.json()
            bot_status = (
                f"\n*Bot P&L:*\n"
                f"  Trades: {p.get('trade_count', 0)}\n"
                f"  Profit: {p.get('profit_all_coin', 0):.2f} USDT ({p.get('profit_all_percent', 0):.1f}%)\n"
                f"  Open: {p.get('open_trade_count', 0)} positions"
            )
    except Exception:
        bot_status = "\n_Bot API unavailable_"

    # Build the message line-by-line. Previous version chained f-strings inside
    # parentheses with a `... if btc else ""` ternary on one of them — that
    # binds the conditional at the PYTHON expression level (not string level),
    # which silently collapsed the *entire* message to "" whenever btc was 0.
    parts = [
        f"*Daily Report* 📊 {today}",
        "─" * 30,
        "*Market:*",
    ]
    if btc:
        parts.append(f"  BTC: ${btc:,.0f}")
    parts.extend([
        f"  Fear & Greed: {fng} ({fng_class})",
        f"  Sentiment: {score:+.2f}",
        f"  KOL Activity: {kol:+.2f} ({kol_n} mentions)",
    ])
    message = "\n".join(parts) + history_str + bot_status + format_kelly_report()

    # Snapshot the structured Kelly status alongside the Telegram send so a
    # dashboard / monitoring consumer can read the same numbers without
    # re-running the Python.
    try:
        write_kelly_status_json(PROJECT_DIR / "sentiment_data" / "kelly_status.json")
    except Exception as e:
        logger.warning(f"Kelly status write failed: {e}")

    send_telegram(message)
    logger.info("Daily report sent")

    state["last_daily_report"] = today
    save_state(state)


# --------------------------------------------------------------------------
# Alert 5: DCA Triggers
# --------------------------------------------------------------------------
_DCA_KIND_EMOJI = {
    "FLASH": "⚡",
    "FAST": "🏃",
    "SUSTAIN": "💪",
    "CAPITUL": "💀",
}


def check_dca_triggers() -> int:
    """
    Query quant.event_dca_triggers for rows newer than last seen id, send a
    Telegram message for each one, and persist the high-water mark.

    :return: Number of new trigger messages sent.
    """
    if psycopg2 is None:
        logger.warning("psycopg2 not installed — skipping DCA trigger check")
        return 0

    timescale_url = os.environ.get("TIMESCALE_URL", "")
    if not timescale_url:
        logger.info("TIMESCALE_URL not set — skipping DCA trigger check")
        return 0

    state = load_state()
    last_id: int = state.get("last_trigger_id", 0)

    try:
        conn = psycopg2.connect(timescale_url)
    except Exception as e:
        logger.warning(f"DB connect failed: {e}")
        return 0

    rows = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ts, kind, price, severity, fng, amount_usdt, mode"
                " FROM quant.event_dca_triggers"
                " WHERE id > %s ORDER BY id ASC LIMIT 10",
                (last_id,),
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"DB query failed: {e}")
        return 0
    finally:
        conn.close()

    sent = 0
    max_id = last_id

    for row in rows:
        row_id, ts, kind, price, severity, fng, amount_usdt, mode = row
        emoji = _DCA_KIND_EMOJI.get(str(kind).upper(), "📌")
        message = (
            f"*DCA Trigger* {emoji} {kind}\n"
            f"─────────────────────\n"
            f"Time: {ts}\n"
            f"BTC: ${float(price):,.0f}\n"
            f"Severity: {severity}/5  FnG: {fng}\n"
            f"Amount: ${amount_usdt} USDT  Mode: {mode}"
        )
        if send_telegram(message):
            sent += 1
        max_id = max(max_id, row_id)

    if max_id > last_id:
        state["last_trigger_id"] = max_id
        save_state(state)

    logger.info(f"DCA triggers: {sent} new sent (last_id={max_id})")
    return sent


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--kol", action="store_true", help="Check KOL alerts only")
    parser.add_argument("--sentiment", action="store_true", help="Check sentiment shift only")
    parser.add_argument("--health", action="store_true", help="Check bot health only")
    parser.add_argument("--daily", action="store_true", help="Send daily report")
    parser.add_argument("--dca", action="store_true", help="Check DCA triggers")
    parser.add_argument("--kelly", action="store_true",
                        help="Print Kelly verdict per strategy (does not send Telegram)")
    parser.add_argument("--json", action="store_true",
                        help="With --kelly, emit machine-readable JSON instead of Markdown")
    parser.add_argument("--write-kelly-status",
                        metavar="PATH",
                        help="Compute Kelly status and write JSON to PATH, then exit")
    parser.add_argument("--all", action="store_true", help="Run all checks (default)")
    args = parser.parse_args()

    if args.write_kelly_status:
        out = write_kelly_status_json(Path(args.write_kelly_status))
        print(f"wrote {out}")
        sys.exit(0)

    if args.kelly:
        if args.json:
            print(json.dumps(kelly_status_dict(), indent=2))
        else:
            print(format_kelly_report() or "(no Kelly data)")
        sys.exit(0)

    run_all = args.all or not (args.kol or args.sentiment or args.health or args.daily or args.dca)

    if args.dca or run_all:
        n = check_dca_triggers()
        print(f"DCA triggers: {n} new")

    if args.kol or run_all:
        n = check_kol_alerts()
        print(f"KOL alerts: {n} new")

    if args.sentiment or run_all:
        check_sentiment_shift()
        print("Sentiment shift: checked")

    if args.health or run_all:
        ok = check_bot_health()
        print(f"Bot health: {'OK' if ok else 'DOWN'}")

    if args.daily:
        send_daily_report()
        print("Daily report: sent")
