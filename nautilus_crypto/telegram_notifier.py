"""Telegram notifier — the single-stack alert sink for the Nautilus signal layer.

Plain helper (not an Actor), mirroring TradeLedger: actors/strategies call ``.send()``.
Reads ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID`` from env (sops-provided) — the same
vars the retired ``event_dca_bot`` / ``event_reactor`` daemons used. No-op (disabled) when
unset, so backtests and local runs never hit the network. All errors are swallowed +
logged — a Telegram hiccup must never break detection or trading.
"""

from __future__ import annotations

import os


class TelegramNotifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None, logger=None):
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self._log = logger

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat)

    def send(self, text: str, markdown: bool = True) -> bool:
        if not self.enabled:
            return False
        try:
            import requests  # lazy: backtests don't need it

            payload = {
                "chat_id": self._chat,
                "text": text,
                "disable_web_page_preview": True,
            }
            if markdown:
                payload["parse_mode"] = "Markdown"
            r = requests.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json=payload,
                timeout=10,
            )
            return r.status_code == 200
        except Exception as e:  # noqa: BLE001 — never let an alert break the engine
            if self._log:
                self._log.warning(f"telegram send failed: {e}")
            return False
