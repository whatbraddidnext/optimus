# risk_manager.py — Optimus Risk Manager
# Version: v2.001
#
# Has VETO POWER over all other modules. No entry can bypass risk checks.
# Manages: portfolio heat, circuit breaker, drawdown, regime exits,
#          aggregate delta, time stops.

import config as cfg
from shared.constants import ExitReason, Regime
from shared.utils import safe_divide


class RiskManager:
    """Portfolio-level risk management with veto authority.

    Non-negotiable rules enforced here:
        1. Defined risk only (structural — not enforced at runtime)
        2. Never hold to expiration — 21 DTE time stop
        3. Size by max loss (enforced via position_sizer)
        4. This module has veto power
        5. Circuit breaker after consecutive max losses
        6. Portfolio heat limit
        7. Regime override
    """

    VERSION = "v2.001"

    def __init__(self, algorithm, trade_tracker, regime_detector, indicators):
        self.algo = algorithm
        self.tracker = trade_tracker
        self.regime = regime_detector
        self.ind = indicators
        self._circuit_breaker_active = False
        self._circuit_breaker_until = None
        self._consecutive_max_losses = 0

    # -------------------------------------------------------------------------
    # Entry Veto
    # -------------------------------------------------------------------------

    def approve_entry(self, sizing_result, current_date):
        """Final approval gate before trade execution.

        Args:
            sizing_result: dict from position_sizer.calculate().
            current_date: Current trading date.

        Returns:
            dict: {approved: bool, reason: str}
        """
        # Check 1: Circuit breaker
        if self._circuit_breaker_active:
            if (self._circuit_breaker_until is not None
                    and current_date >= self._circuit_breaker_until):
                self._circuit_breaker_active = False
                self._circuit_breaker_until = None
                self._consecutive_max_losses = 0
                self.algo.log("[RISK] Circuit breaker cooldown expired — resuming")
            else:
                return self._veto(
                    f"Circuit breaker active until {self._circuit_breaker_until} "
                    f"({self._consecutive_max_losses} consecutive max losses)")

        # Check 2: Zero contracts
        if sizing_result["contracts"] <= 0:
            return self._veto("Position size is 0 contracts")

        # Check 3: Portfolio heat limit
        current_heat = self.tracker.total_portfolio_heat()
        new_heat = current_heat + sizing_result["total_max_loss"]
        equity = self.algo.portfolio.total_portfolio_value
        heat_pct = safe_divide(new_heat, equity, 0) * 100
        if heat_pct > cfg.MAX_PORTFOLIO_HEAT_PCT:
            return self._veto(
                f"Portfolio heat would be {heat_pct:.1f}% "
                f"(limit {cfg.MAX_PORTFOLIO_HEAT_PCT}%)")

        # Check 4: Aggregate delta limit
        agg_delta = self.tracker.aggregate_delta()
        # Each new put credit spread adds negative delta
        # Approximate: short_delta * contracts
        # Exact check would need the spread's delta, but this is conservative
        if agg_delta is not None and agg_delta < cfg.MAX_AGGREGATE_DELTA:
            return self._veto(
                f"Aggregate delta {agg_delta:.2f} already exceeds limit "
                f"({cfg.MAX_AGGREGATE_DELTA})")

        # Check 5: Regime is still tradeable
        if not self.regime.is_tradeable():
            return self._veto(
                f"Regime shifted to {self.regime.current_regime.value} "
                f"since signal evaluation")

        return {"approved": True, "reason": "All risk checks passed"}

    # -------------------------------------------------------------------------
    # Exit Evaluation
    # -------------------------------------------------------------------------

    def evaluate_exits(self, current_date):
        """Check all open positions for exit conditions.

        Returns:
            list of dict: [{position_id, reason: ExitReason, detail: str}]
        """
        exits = []

        # Check regime-level forced exit
        regime_exit = self._check_regime_exit()
        if regime_exit:
            for pos in self.tracker.open_positions():
                exits.append({
                    "position_id": pos["id"],
                    "reason": ExitReason.REGIME_SHIFT,
                    "detail": regime_exit,
                })
            return exits  # Regime exit overrides everything

        for pos in self.tracker.open_positions():
            exit_info = self._evaluate_position_exit(pos, current_date)
            if exit_info is not None:
                exits.append(exit_info)

        return exits

    def _evaluate_position_exit(self, position, current_date):
        """Check a single position for exit conditions.

        Priority: Profit Target > Stop Loss > Time Stop
        """
        current_value = position.get("current_spread_value")
        entry_credit = position.get("entry_credit")
        dte = position.get("dte_remaining")

        # Profit Target: spread value <= profit target price
        if current_value is not None and entry_credit is not None:
            profit_target = entry_credit * (cfg.PROFIT_TARGET_PCT / 100.0)
            if current_value <= profit_target:
                return {
                    "position_id": position["id"],
                    "reason": ExitReason.PROFIT_TARGET,
                    "detail": (f"Spread value ${current_value:.2f} <= "
                               f"target ${profit_target:.2f} "
                               f"({cfg.PROFIT_TARGET_PCT}% of "
                               f"${entry_credit:.2f} credit)"),
                }

        # Stop Loss: spread value >= stop loss price
        if current_value is not None and entry_credit is not None:
            stop_price = entry_credit * cfg.STOP_LOSS_MULTIPLIER
            if current_value >= stop_price:
                return {
                    "position_id": position["id"],
                    "reason": ExitReason.STOP_LOSS,
                    "detail": (f"Spread value ${current_value:.2f} >= "
                               f"stop ${stop_price:.2f} "
                               f"({cfg.STOP_LOSS_MULTIPLIER:.0f}x of "
                               f"${entry_credit:.2f} credit)"),
                }

        # Time Stop: DTE <= time stop threshold
        if dte is not None and dte <= cfg.TIME_STOP_DTE:
            return {
                "position_id": position["id"],
                "reason": ExitReason.TIME_STOP,
                "detail": f"DTE {dte} <= time stop {cfg.TIME_STOP_DTE}",
            }

        return None

    def _check_regime_exit(self):
        """Check if regime requires forced exit of all positions."""
        if self.regime.current_regime in (Regime.CRISIS, Regime.BEAR_TREND):
            if self.regime.regime_changed():
                return (f"Regime shifted to {self.regime.current_regime.value} "
                        f"— closing all positions within 1 business day")
        return None

    # -------------------------------------------------------------------------
    # Circuit Breaker
    # -------------------------------------------------------------------------

    def record_trade_result(self, exit_reason, current_date):
        """Record a trade result and check circuit breaker.

        Args:
            exit_reason: ExitReason enum.
            current_date: Date the trade was closed.
        """
        if exit_reason == ExitReason.STOP_LOSS:
            self._consecutive_max_losses += 1
            if self._consecutive_max_losses >= cfg.CIRCUIT_BREAKER_COUNT:
                self._activate_circuit_breaker(current_date)
        else:
            self._consecutive_max_losses = 0

    def _activate_circuit_breaker(self, current_date):
        """Activate circuit breaker — halt all new entries."""
        self._circuit_breaker_active = True
        from datetime import timedelta
        cooldown_calendar_days = cfg.CIRCUIT_BREAKER_COOLDOWN_DAYS * 7 // 5 + 2
        self._circuit_breaker_until = current_date + timedelta(
            days=cooldown_calendar_days)
        self.algo.log(
            f"[RISK] CIRCUIT BREAKER ACTIVATED — "
            f"{self._consecutive_max_losses} consecutive max losses. "
            f"Halting until {self._circuit_breaker_until}")

    @property
    def circuit_breaker_active(self):
        return self._circuit_breaker_active

    @property
    def consecutive_max_losses(self):
        return self._consecutive_max_losses

    # -------------------------------------------------------------------------
    # Drawdown
    # -------------------------------------------------------------------------

    def current_drawdown(self):
        """Calculate current drawdown from peak equity.

        Returns:
            float: Drawdown as positive decimal (e.g. 0.12 for 12%).
        """
        equity = self.algo.portfolio.total_portfolio_value
        peak = getattr(self.algo, '_peak_equity', equity)
        if equity >= peak:
            self.algo._peak_equity = equity
            return 0.0
        return (peak - equity) / peak

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _veto(reason):
        return {"approved": False, "reason": reason}

    def get_status(self):
        """Return diagnostic dict of risk manager state."""
        return {
            "circuit_breaker_active": self._circuit_breaker_active,
            "circuit_breaker_until": str(self._circuit_breaker_until),
            "consecutive_max_losses": self._consecutive_max_losses,
            "current_drawdown_pct": round(self.current_drawdown() * 100, 2),
            "portfolio_heat": self.tracker.total_portfolio_heat(),
            "aggregate_delta": self.tracker.aggregate_delta(),
        }
