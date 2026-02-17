# diagnostics.py — Optimus Diagnostics & Analytics
# Version: v2.001
#
# Daily dashboard, entry evaluation logging, unfavourable market logging,
# and performance analytics. Post-trade analysis, not real-time decisions.

import config as cfg
from shared.utils import format_currency, format_pct, safe_divide


class Diagnostics:
    """Generates structured diagnostic output for logging and analysis.

    Output types (per HLD Section 9):
        - Entry condition logging (every daily evaluation)
        - Trade parameter logging (on fills)
        - Exit logging (on closes)
        - Unfavourable market logging
        - Daily dashboard summary
    """

    VERSION = "v2.001"

    def __init__(self, algorithm, indicators, regime_detector,
                 trade_tracker, risk_manager):
        self.algo = algorithm
        self.ind = indicators
        self.regime = regime_detector
        self.tracker = trade_tracker
        self.risk = risk_manager

    # -------------------------------------------------------------------------
    # Daily Dashboard (HLD 9.5)
    # -------------------------------------------------------------------------

    def daily_dashboard(self):
        """Generate the daily dashboard summary string."""
        regime_status = self.regime.get_status()
        iv_rank = self.ind.iv_rank()
        vix = self.ind.vix_level()
        open_count = self.tracker.open_position_count()
        agg_pnl = self.tracker.aggregate_pnl()
        agg_delta = self.tracker.aggregate_delta()
        agg_theta = self.tracker.aggregate_theta()
        equity = self.algo.portfolio.total_portfolio_value
        heat = self.tracker.total_portfolio_heat()
        heat_pct = safe_divide(heat, equity, 0) * 100
        nearest_dte = self.tracker.nearest_expiry_dte()
        risk_status = self.risk.get_status()
        last_3 = self.tracker.last_n_results(3)

        lines = [
            f"[DAILY DASHBOARD] {self.algo.time.strftime('%Y-%m-%d')}",
            f"  Regime: {regime_status['regime']} | "
            f"VIX: {vix:.1f if vix else 'N/A'} | "
            f"IV Rank: {iv_rank:.0f}% " if iv_rank else "IV Rank: N/A",
            f"  Open Positions: {open_count} | "
            f"Aggregate P/L: {format_currency(agg_pnl)}",
            f"  Aggregate Delta: {agg_delta:.2f} | "
            f"Aggregate Theta: {format_currency(agg_theta)}/day",
            f"  Portfolio Heat: {format_pct(heat_pct)} of equity",
        ]

        if nearest_dte is not None:
            alert = " — ALERT: approaching time stop" if nearest_dte <= cfg.TIME_STOP_DTE + 7 else ""
            lines.append(f"  Nearest Expiry: {nearest_dte} DTE{alert}")

        cb_status = "ON" if risk_status["circuit_breaker_active"] else "OFF"
        last_3_str = ", ".join(last_3) if last_3 else "no trades"
        lines.append(f"  Circuit Breaker: {cb_status} (last 3: {last_3_str})")
        lines.append(f"  Drawdown: {risk_status['current_drawdown_pct']:.1f}%")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Unfavourable Market Logging (HLD 9.4)
    # -------------------------------------------------------------------------

    def log_no_trade(self, underlying, entry_signal=None, reason=None):
        """Log when market conditions are unfavourable.

        Args:
            underlying: Ticker string.
            entry_signal: EntrySignal from signal_engine (optional).
            reason: Override reason string (optional).
        """
        open_count = self.tracker.open_position_count()
        agg_delta = self.tracker.aggregate_delta()
        agg_theta = self.tracker.aggregate_theta()
        equity = self.algo.portfolio.total_portfolio_value
        heat = self.tracker.total_portfolio_heat()
        heat_pct = safe_divide(heat, equity, 0) * 100

        last_entry_days = self.tracker.business_days_since_last_entry(
            underlying, self.algo.time.date())

        lines = [
            f"[DAILY SUMMARY] {self.algo.time.strftime('%Y-%m-%d')} | "
            f"NO TRADES ELIGIBLE",
        ]

        if entry_signal is not None and entry_signal.first_failure:
            lines.append(f"  {underlying}: BLOCKED — {entry_signal.first_failure}")
        elif reason:
            lines.append(f"  {underlying}: BLOCKED — {reason}")

        lines.extend([
            f"  Open Positions: {open_count} (within risk limits)",
            f"  Aggregate Delta: {agg_delta:.2f}",
            f"  Aggregate Theta: {format_currency(agg_theta)}/day",
            f"  Portfolio Heat: {format_pct(heat_pct)} of equity",
            f"  Days Since Last Entry: {last_entry_days or 'N/A'}",
        ])

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Entry Evaluation Logging (HLD 9.1)
    # -------------------------------------------------------------------------

    def log_entry_eval(self, entry_signal):
        """Format an entry evaluation from the signal engine.

        The EntrySignal already has a to_log() method; this adds
        additional context from other modules.
        """
        return entry_signal.to_log()

    # -------------------------------------------------------------------------
    # Performance Summary
    # -------------------------------------------------------------------------

    def performance_summary(self):
        """Generate a full performance summary for logging."""
        stats = self.tracker.all_time_stats()
        if stats["total"] == 0:
            return "[PERFORMANCE] No closed trades yet"

        lines = [
            f"[PERFORMANCE SUMMARY]",
            f"  Total Trades: {stats['total']}",
            f"  Wins: {stats['wins']} | Losses: {stats['losses']}",
            f"  Win Rate: {stats['win_rate']:.1f}%",
            f"  Profit Factor: {stats['profit_factor']:.2f}",
            f"  Total P/L: {format_currency(stats['total_pnl'])}",
        ]
        return "\n".join(lines)
