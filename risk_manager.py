# risk_manager.py — Optimus v2.0-MVP
# Portfolio risk management with absolute veto power
# No trade bypasses risk checks

MODULE_VERSION = "1.0"


class RiskState:
    NORMAL = "NORMAL"
    DAY_HALT = "DAY_HALT"
    WEEK_HALT = "WEEK_HALT"
    MONTH_HALT = "MONTH_HALT"
    CORR_ALERT = "CORR_ALERT"


class RiskManager:
    """Portfolio-level risk management with veto power.

    Risk rules (HLD Section 13):
    - Margin cap: block entries above 45% utilisation
    - Daily loss > 3%: halt for remainder of day
    - Weekly loss > 5%: halt for remainder of week
    - Monthly DD > 8%: halt for remainder of month, close positions > 21 DTE
    - Per-underlying loss > 5% equity: close worst position on that underlying
    - Correlation alert: 3+ underlyings in simultaneous loss

    State machine:
    NORMAL -> DAY_HALT -> NORMAL (next trading day)
    NORMAL -> WEEK_HALT -> NORMAL (next trading week)
    NORMAL -> MONTH_HALT -> NORMAL (next month)
    """

    def __init__(self, global_config):
        self.config = global_config
        self.state = RiskState.NORMAL
        self.margin_cap = global_config["margin_cap"]
        self.daily_halt_pct = global_config["daily_loss_halt_pct"]
        self.weekly_halt_pct = global_config["weekly_loss_halt_pct"]
        self.monthly_halt_pct = global_config["monthly_dd_halt_pct"]

        # Tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.monthly_pnl = 0.0
        self._last_day = None
        self._last_week = None
        self._last_month = None
        self._halt_reason = None

    def update_pnl(self, current_time, realised_pnl_today, unrealised_pnl_change):
        """Update P&L tracking and evaluate risk state transitions.

        Called on each management scan with today's P&L changes.
        """
        total_change = realised_pnl_today + unrealised_pnl_change

        # Reset periods
        current_day = current_time.date()
        if self._last_day is not None and current_day != self._last_day:
            # New day — reset daily, check if halt should clear
            self.daily_pnl = 0.0
            if self.state == RiskState.DAY_HALT:
                self.state = RiskState.NORMAL
                self._halt_reason = None

        current_week = current_time.isocalendar()[1]
        if self._last_week is not None and current_week != self._last_week:
            self.weekly_pnl = 0.0
            if self.state == RiskState.WEEK_HALT:
                self.state = RiskState.NORMAL
                self._halt_reason = None

        current_month = current_time.month
        if self._last_month is not None and current_month != self._last_month:
            self.monthly_pnl = 0.0
            if self.state == RiskState.MONTH_HALT:
                self.state = RiskState.NORMAL
                self._halt_reason = None

        self.daily_pnl += total_change
        self.weekly_pnl += total_change
        self.monthly_pnl += total_change

        self._last_day = current_day
        self._last_week = current_week
        self._last_month = current_month

    def evaluate_risk_state(self, equity):
        """Check P&L against halt thresholds. Called after update_pnl."""
        if equity <= 0:
            return

        # Monthly halt takes priority (most severe)
        if self.monthly_pnl < -(equity * self.monthly_halt_pct):
            self.state = RiskState.MONTH_HALT
            self._halt_reason = (f"Monthly DD {self.monthly_pnl / equity:.1%} "
                                 f"exceeds -{self.monthly_halt_pct:.0%}")
            return

        # Weekly halt
        if self.weekly_pnl < -(equity * self.weekly_halt_pct):
            self.state = RiskState.WEEK_HALT
            self._halt_reason = (f"Weekly loss {self.weekly_pnl / equity:.1%} "
                                 f"exceeds -{self.weekly_halt_pct:.0%}")
            return

        # Daily halt
        if self.daily_pnl < -(equity * self.daily_halt_pct):
            self.state = RiskState.DAY_HALT
            self._halt_reason = (f"Daily loss {self.daily_pnl / equity:.1%} "
                                 f"exceeds -{self.daily_halt_pct:.0%}")
            return

    def can_enter_new_trade(self, margin_used_pct):
        """Veto check: can we open a new position?

        Returns (allowed, reason_if_blocked)
        """
        # Risk state check
        if self.state != RiskState.NORMAL:
            return False, f"risk state: {self.state} ({self._halt_reason})"

        # Margin cap check
        if margin_used_pct >= self.margin_cap:
            return False, f"margin {margin_used_pct:.1%} >= cap {self.margin_cap:.0%}"

        return True, None

    def should_tighten_targets(self):
        """In WEEK_HALT, tighten profit targets to 40% on existing positions."""
        return self.state == RiskState.WEEK_HALT

    def should_force_close_above_dte(self):
        """In MONTH_HALT, close any position with DTE > 21."""
        return self.state == RiskState.MONTH_HALT

    def check_per_underlying_limit(self, underlying, unrealised_loss, equity):
        """Check if a single underlying's losses exceed 5% of equity.

        Returns True if limit breached (should close worst position).
        """
        if equity <= 0:
            return False
        return unrealised_loss < -(equity * 0.05)

    def check_catastrophic_stop(self, price_change_atr_multiple, threshold=None):
        """Check if underlying moved > 3x ATR in a single session.

        Returns True if catastrophic stop should trigger.
        """
        if threshold is None:
            threshold = self.config["catastrophic_atr_multiple"]
        return abs(price_change_atr_multiple) > threshold

    @property
    def status_summary(self):
        return {
            "state": self.state,
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "monthly_pnl": self.monthly_pnl,
            "halt_reason": self._halt_reason,
        }
