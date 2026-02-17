# notifications.py — Optimus Alert System
# Version: v2.001
#
# Sends alerts via Telegram and/or email for trades, circuit breakers,
# and daily summaries. Wrapped in exception handlers — never crashes the algo.

import config as cfg


class NotificationManager:
    """Sends trade alerts and status notifications.

    All notification methods are wrapped in try/except to ensure
    a notification failure never crashes the algorithm.

    Channels:
        - Telegram (via bot API)
        - Email (via QuantConnect notification API)
        - Algorithm log (always)
    """

    VERSION = "v2.001"

    def __init__(self, algorithm):
        self.algo = algorithm

    def notify_trade_opened(self, spread_log, conviction_log):
        """Alert on new trade entry."""
        message = f"{spread_log}\n{conviction_log}"
        self._send(f"TRADE OPENED", message)

    def notify_trade_closed(self, trade_log):
        """Alert on trade exit."""
        self._send("TRADE CLOSED", trade_log)

    def notify_circuit_breaker(self, detail):
        """Alert on circuit breaker activation."""
        self._send("CIRCUIT BREAKER", detail, urgent=True)

    def notify_regime_shift(self, old_regime, new_regime):
        """Alert on regime change."""
        self._send("REGIME SHIFT",
                   f"Regime changed from {old_regime} to {new_regime}")

    def notify_daily_summary(self, summary):
        """Send daily dashboard summary."""
        self._send("DAILY SUMMARY", summary)

    def notify_risk_veto(self, detail):
        """Alert when risk manager vetoes a trade."""
        self._send("RISK VETO", detail)

    def notify_error(self, detail):
        """Alert on unexpected errors."""
        self._send("ERROR", detail, urgent=True)

    def _send(self, subject, body, urgent=False):
        """Send notification via all enabled channels.

        Never raises exceptions — all errors are caught and logged.
        """
        full_subject = f"[{cfg.STRATEGY_NAME} {cfg.STRATEGY_VERSION}] {subject}"

        # Always log
        self.algo.log(f"[NOTIFY] {subject}")

        # Telegram
        if cfg.TELEGRAM_ENABLED:
            self._send_telegram(full_subject, body, urgent)

        # Email
        if cfg.EMAIL_ENABLED:
            self._send_email(full_subject, body, urgent)

    def _send_telegram(self, subject, body, urgent=False):
        """Send via Telegram bot API."""
        try:
            prefix = "!!! " if urgent else ""
            message = f"{prefix}{subject}\n\n{body}"
            # QuantConnect notification API
            self.algo.notify.telegram(
                cfg.TELEGRAM_CHAT_ID,
                message,
                cfg.TELEGRAM_BOT_TOKEN)
        except Exception as e:
            self.algo.log(f"[NOTIFY] Telegram failed: {e}")

    def _send_email(self, subject, body, urgent=False):
        """Send via QuantConnect email notification."""
        try:
            self.algo.notify.email(
                cfg.EMAIL_RECIPIENT,
                subject,
                body)
        except Exception as e:
            self.algo.log(f"[NOTIFY] Email failed: {e}")
